"""API do Gab's FinLab.

FastAPI fino: serve o front estático e devolve JSON. Todo o cálculo de
valuation interativo acontece no navegador; aqui ficam coleta, normalização
contábil, score e o proxy dos agentes de IA.
"""

from __future__ import annotations

import statistics
from typing import Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import (agents, b3data, bdrs, cache, cvm, etfs, ipe, market, metrics,
               regime, scoring, universe, valuation)
from .settings import DEMO_MODE, TTL_CVM, TTL_QUOTE, WEB_DIR

app = FastAPI(title="Gab's FinLab", version="2.0", docs_url="/api/docs")


@app.middleware("http")
async def _sem_cache_heuristico(request, call_next):
    """Força o navegador a revalidar HTML e assets a cada visita.

    Sem Cache-Control, os navegadores aplicam "frescor heurístico" e reutilizam
    JS/CSS antigos do cache sem perguntar ao servidor — depois de um git pull,
    a página carrega com metade dos scripts desatualizados e quebra de formas
    silenciosas. `no-cache` não desliga o cache: só exige a revalidação
    (respostas 304 continuam baratas).
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets") or not path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------------------
# Camada de dados
# ---------------------------------------------------------------------------

def _fundamentals(ticker: str) -> dict:
    # A versão na chave sobe SEMPRE que o formato do payload muda. O cache vive
    # em disco com TTL de 24 h: sem o bump, quem der git pull passa um dia
    # inteiro vendo o painel novo alimentado pelo blob antigo — que aqui
    # significaria classificar o regime sem os campos que o classificador lê.
    return cache.memoize(f"fund:v4:{ticker}", TTL_CVM, lambda: metrics.fundamentals(ticker)) or {}


def _overview_rows() -> dict:
    """Monta a tabela da tela principal: mercado + fundamentos + score."""
    def build():
        tickers = universe.TICKERS
        series = market.price_series(tickers)
        quotes = market.brapi_quotes(tickers)

        rows = []
        for comp in universe.UNIVERSE:
            fund = _fundamentals(comp.ticker)
            if not fund:
                continue
            brapi = quotes.get(comp.ticker)
            snap = metrics.market_snapshot(comp.ticker, series.get(comp.ticker, []), brapi, fund)
            mult = metrics.multiples(fund, snap, brapi)
            sc = scoring.score(fund.get("indicadores", {}), fund.get("financial", False))
            rows.append({
                "ticker": comp.ticker,
                "name": comp.name,
                "sector": comp.sector,
                "financial": fund.get("financial", False),
                "last_year": fund.get("last_year"),
                "price": snap.get("price"),
                "price_date": snap.get("price_date"),
                "price_source": snap.get("price_source"),
                "market_cap": snap.get("market_cap"),
                "perf": snap.get("perf"),
                "multiples": mult,
                "score": sc.get("total"),
                "score_band": scoring.band(sc.get("total")),
                "grade": scoring.grade(sc.get("total")),
                "cobertura": sc.get("cobertura"),
                "parcial": sc.get("parcial"),
                "pilares": [{"key": p["key"], "label": p["label"], "score": p["score"]}
                            for p in sc.get("pilares", [])],
            })

        rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["ticker"]))
        for i, row in enumerate(rows, start=1):
            row["rank"] = i

        return {
            "rows": rows,
            "sector_stats": _sector_stats(rows),
            "demo": DEMO_MODE,
            "cvm_disponivel": cvm.available(),
        }

    return _com_diagnostico(cache.memoize("overview:v4", TTL_QUOTE, build) or {"rows": []})


def _com_diagnostico(payload: dict) -> dict:
    """Acrescenta o estado das fontes a um payload vindo do cache.

    Isto NÃO pode entrar no blob memoizado: o cache vive em disco e sobrevive
    ao restart, então quem acabou de preencher o BRAPI_TOKEN e reiniciou
    continuaria vendo "rodando sem token" pelo resto do TTL — exatamente o
    contrário do que o painel deveria dizer.
    """
    out = dict(payload)
    out["providers"] = market.provider_status()
    out["source"] = market.source_label()
    return out


def _sector_stats(rows: list[dict]) -> dict:
    """Mediana dos múltiplos e do score por setor, para comparação de pares."""
    out: dict[str, dict] = {}
    keys = ["pl", "pvp", "ev_ebitda", "dy", "roe", "mg_ebitda", "nd_ebitda"]
    for sector in universe.SECTORS:
        grupo = [r for r in rows if r["sector"] == sector]
        if not grupo:
            continue
        stats: dict[str, Optional[float]] = {}
        for key in keys:
            vals = [r["multiples"].get(key) for r in grupo]
            vals = [v for v in vals if v is not None and -1e6 < v < 1e6]
            # P/L e EV/EBITDA negativos não entram na mediana do setor:
            # empresa com prejuízo distorce a referência de "caro/barato".
            if key in ("pl", "ev_ebitda", "pvp"):
                vals = [v for v in vals if v > 0]
            stats[key] = round(statistics.median(vals), 3) if vals else None
        notas = [r["score"] for r in grupo if r["score"] is not None]
        stats["score"] = round(statistics.median(notas), 1) if notas else None
        stats["n"] = len(grupo)
        out[sector] = stats
    return out


# ---------------------------------------------------------------------------
# Rotas de dados
# ---------------------------------------------------------------------------

@app.get("/api/universe")
def api_universe():
    payload = universe.as_payload()
    payload["bdrs"] = [{"ticker": b.ticker, "name": b.name, "sector": b.sector}
                       for b in bdrs.UNIVERSE]
    payload["bdr_sectors"] = bdrs.SECTORS
    return payload


@app.get("/api/overview")
def api_overview():
    return _overview_rows()


@app.get("/api/macro")
def api_macro():
    return market.macro()


@app.get("/api/config")
def api_config():
    return {
        "providers": agents.provider_list(),
        "agents": agents.agent_list(),
        "market_providers": market.provider_status(),
        "demo": DEMO_MODE,
        "source": market.source_label(),
    }


@app.get("/api/company/{ticker}")
def api_company(ticker: str):
    ticker = ticker.upper().strip()
    comp = universe.get(ticker)
    if comp is None:
        if bdrs.get(ticker):
            return _bdr_payload(ticker)
        raise HTTPException(status_code=404, detail=f"Ticker fora do universo coberto: {ticker}")

    fund = _fundamentals(ticker)
    if not fund:
        raise HTTPException(status_code=404, detail=f"Sem dados para {ticker}")

    series = market.price_series([ticker]).get(ticker, [])
    brapi = market.brapi_fundamentals(ticker) or market.brapi_quotes([ticker]).get(ticker)
    snap = metrics.market_snapshot(ticker, series, brapi, fund)
    mult = metrics.multiples(fund, snap, brapi)
    sc = scoring.score(fund.get("indicadores", {}), fund.get("financial", False))
    macro_data = market.macro()
    # O regime vem antes das premissas: é ele que diz se a média de 3 anos
    # descreve o run-rate desta empresa ou o de outra que ela já foi.
    reg = regime.classificar(fund)
    prem = valuation.assumptions(fund, snap, macro_data, brapi, reg=reg)

    overview = _overview_rows()
    stats = (overview.get("sector_stats") or {}).get(comp.sector, {})
    pares = [r for r in overview.get("rows", []) if r["sector"] == comp.sector]

    return {
        "fundamentals": fund,
        "market": snap,
        "multiples": mult,
        "score": sc,
        "assumptions": prem,
        "macro": macro_data,
        "sector_stats": stats,
        "sector_label": universe.SECTORS[comp.sector]["label"],
        "peers": [{"ticker": p["ticker"], "name": p["name"], "score": p["score"],
                   "multiples": p["multiples"], "price": p["price"], "perf": p["perf"]}
                  for p in pares],
        "price_series": [{"d": d, "p": p} for d, p in series[-500:]],
        "consenso": _consenso(brapi),
        "itr": cvm.latest_quarter(comp.cd_cvm),
        "trimestral": cvm.quarterly_series(comp.cd_cvm),
        "ltm": cvm.ltm_series(comp.cd_cvm),
        "ipe": ipe.documentos(comp.cd_cvm),
        "regime": reg,
        "source": snap.get("price_source"),
    }


def _consenso(brapi: Optional[dict]) -> dict:
    """Preço-alvo e recomendação de analistas, quando a BRAPI fornece."""
    if not brapi:
        return {}
    fd = brapi.get("financialData")
    if not isinstance(fd, dict):
        return {}
    return {
        "alvo_medio": fd.get("targetMeanPrice"),
        "alvo_alto": fd.get("targetHighPrice"),
        "alvo_baixo": fd.get("targetLowPrice"),
        "recomendacao": fd.get("recommendationKey"),
        "analistas": fd.get("numberOfAnalystOpinions"),
    }


# ---------------------------------------------------------------------------
# ETFs
# ---------------------------------------------------------------------------

def _etf_rows() -> dict:
    def build():
        uni = etfs.universe()
        tickers = [e["ticker"] for e in uni]
        series = market.asset_series(tickers)
        boletim = b3data.bdi()

        rows = []
        for etf in uni:
            tk = etf["ticker"]
            perf = market.performance(series.get(tk, []))
            liq = (boletim.get(tk) or {}).get("avg_vol")
            rows.append({
                **etf,
                "price": perf.get("price"),
                "price_date": perf.get("date"),
                "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
                "liquidez": liq,
                "liquidez_faixa": etfs.liquidity_band(liq),
                "pregoes": (boletim.get(tk) or {}).get("days", 0),
            })
        # Mais líquidos primeiro dentro de cada categoria.
        rows.sort(key=lambda r: -(r["liquidez"] or 0))
        return {"rows": rows, "categories": etfs.CATEGORIES}
    return _com_diagnostico(cache.memoize("etfs:rows:v1", TTL_QUOTE, build) or {"rows": []})


@app.get("/api/etfs")
def api_etfs():
    return _etf_rows()


@app.get("/api/etf/{ticker}")
def api_etf(ticker: str):
    ticker = ticker.upper().strip()
    etf = etfs.get(ticker)
    if etf is None:
        raise HTTPException(status_code=404, detail=f"ETF fora da lista B3: {ticker}")

    series = market.asset_series([ticker]).get(ticker, [])
    perf = market.performance(series)
    boletim = b3data.bdi()
    liq = (boletim.get(ticker) or {}).get("avg_vol")

    todos = _etf_rows().get("rows", [])
    pares = [r for r in todos if r["categoria"] == etf["categoria"] and r["ticker"] != ticker]

    return {
        **etf,
        "price": perf.get("price"),
        "price_date": perf.get("date"),
        "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
        "liquidez": liq,
        "liquidez_faixa": etfs.liquidity_band(liq),
        "pregoes": (boletim.get(ticker) or {}).get("days", 0),
        "price_series": [{"d": d, "p": p} for d, p in series[-500:]],
        "peers": [{k: p[k] for k in ("ticker", "nome", "taxa_adm", "liquidez",
                                     "price", "perf", "pl", "curado")}
                  for p in pares[:15]],
        "categoria_meta": etfs.CATEGORIES.get(etf["categoria"], {}),
        "source": market.source_label(),
    }


# ---------------------------------------------------------------------------
# BDRs
# ---------------------------------------------------------------------------

def _bdr_rows() -> dict:
    def build():
        tickers = bdrs.TICKERS
        series = market.asset_series(tickers)
        quotes = market.brapi_quotes(tickers)
        boletim = b3data.bdi()

        rows = []
        for bdr in bdrs.UNIVERSE:
            tk = bdr.ticker
            perf = market.performance(series.get(tk, []))
            price = perf.get("price")
            quote = quotes.get(tk)
            if quote and quote.get("regularMarketPrice"):
                price = float(quote["regularMarketPrice"])
                chg = quote.get("regularMarketChangePercent")
                if chg is not None:
                    perf["day"] = float(chg) / 100.0
            liq = (boletim.get(tk) or {}).get("avg_vol")
            dy = quote.get("dividendYield") if quote else None
            rows.append({
                "ticker": tk, "name": bdr.name, "us_ticker": bdr.us_ticker,
                "sector": bdr.sector, "bank": bdr.bank,
                "price": price,
                "price_date": perf.get("date"),
                "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
                "liquidez": liq,
                "liquidez_faixa": etfs.liquidity_band(liq),
                "dy": (float(dy) / 100.0) if dy is not None else None,
            })
        rows.sort(key=lambda r: -(r["liquidez"] or 0))
        return {"rows": rows, "sectors": {k: v for k, v in bdrs.SECTORS.items()}}
    saida = _com_diagnostico(cache.memoize("bdrs:rows:v1", TTL_QUOTE, build) or {"rows": []})
    saida["brapi"] = bool(market.BRAPI_TOKEN)
    return saida


@app.get("/api/bdrs")
def api_bdrs():
    return _bdr_rows()


def _bdr_payload(ticker: str) -> dict:
    """Payload no formato de /api/company, para o painel reusar a tela."""
    bdr = bdrs.get(ticker)
    if bdr is None:
        raise HTTPException(status_code=404, detail=f"BDR fora do universo: {ticker}")

    # Só resultados COM dados entram no cache de 24h: uma falha transitória do
    # Yahoo não pode condenar o BDR a um dia inteiro sem fundamentos.
    chave_bundle = f"bdr:bundle:v2:{ticker}"
    bundle = cache.get(chave_bundle, TTL_CVM)
    if not bundle or not bundle.get("fonte"):
        bundle = bdrs.fetch_fundamentals(ticker) or {}
        if bundle.get("fonte"):
            cache.set(chave_bundle, bundle)
    fund = bundle.get("fund") or bdrs.fundamentals_from_modules(bdr, None)
    yahoo_info = bundle.get("info") or {}

    series = market.asset_series([ticker]).get(ticker, [])
    quote = market.brapi_quotes([ticker]).get(ticker)
    perf = market.performance(series)
    price = perf.get("price")
    source = market.source_label()
    if quote and quote.get("regularMarketPrice"):
        price = float(quote["regularMarketPrice"])
        source = "BRAPI"
        chg = quote.get("regularMarketChangePercent")
        if chg is not None:
            perf["day"] = float(chg) / 100.0

    macro_data = market.macro()
    prem = valuation.bdr_assumptions(fund, {"price": price}, macro_data, quote, yahoo_info)

    snap = {
        "price": price,
        "price_date": perf.get("date"),
        "price_source": source,
        "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
        "shares": prem.get("shares"),
        "shares_quote": prem.get("shares"),
        "unit_ratio": 1,
        "shares_source": "sintético: mcap USD ÷ preço do BDR",
        "market_cap": prem.get("mcap_usd"),
        "market_cap_source": "BRAPI (convertido a USD pela PTAX)" if prem.get("mcap_usd") else None,
        "points": len(series or []),
    }

    base = fund.get("base", {})
    mcap_usd = prem.get("mcap_usd")
    dl = base.get("divida_liquida")
    ev = (mcap_usd + dl) if (mcap_usd is not None and dl is not None
                             and not fund.get("financial")) else None
    dy = bdrs.yahoo_dividend_yield(yahoo_info)
    if dy is None and quote and quote.get("dividendYield") is not None:
        try:
            dy = float(quote["dividendYield"]) / 100.0
        except (TypeError, ValueError):
            dy = None
    mult = {
        "pl": metrics.div(mcap_usd, base.get("lucro_liquido")),
        "pvp": metrics.div(mcap_usd, base.get("patrimonio_liquido")),
        "ev_ebitda": metrics.div(ev, base.get("ebitda")),
        "ev_ebit": metrics.div(ev, base.get("ebit")),
        "psr": metrics.div(mcap_usd, base.get("receita")),
        "dy": dy,
        "roe": fund.get("indicadores", {}).get("roe"),
        "mg_ebitda": fund.get("indicadores", {}).get("mg_ebitda"),
        "nd_ebitda": fund.get("indicadores", {}).get("nd_ebitda"),
        "ev": ev, "lpa": None, "vpa": None,
        "fcf_yield": metrics.div(base.get("fcl"), mcap_usd),
    }

    sc = scoring.score(fund.get("indicadores", {}), fund.get("financial", False))

    todos = _bdr_rows().get("rows", [])
    pares = [r for r in todos if r["sector"] == bdr.sector]

    return {
        "fundamentals": fund,
        "market": snap,
        "multiples": mult,
        "score": sc,
        "assumptions": prem,
        "macro": macro_data,
        "sector_stats": {},
        "sector_label": bdrs.SECTORS[bdr.sector]["label"],
        "peers": [{"ticker": p["ticker"], "name": p["name"], "score": None,
                   "multiples": {"dy": p.get("dy")}, "price": p["price"],
                   "perf": p["perf"], "liquidez": p.get("liquidez")}
                  for p in pares if p["ticker"] != ticker],
        "price_series": [{"d": d, "p": p} for d, p in series[-500:]],
        "consenso": _consenso_bdr(yahoo_info, price) or _consenso(quote),
        "source": source,
        "fonte_fundamentos": bundle.get("fonte"),
        "bdr": True,
    }


def _consenso_bdr(info: dict, preco_bdr) -> dict:
    """Preço-alvo de analistas do Yahoo, convertido para 'por BDR'.

    O alvo vem em USD por ação de origem; convertê-lo pela mesma identidade do
    valuation (alvo/preço de origem × preço do BDR) devolve um número na moeda
    e na escala que o usuário vê na tela.
    """
    if not info or not preco_bdr:
        return {}
    atual = info.get("currentPrice") or info.get("regularMarketPrice")
    alvo = info.get("targetMeanPrice")
    try:
        atual = float(atual)
        alvo_m = float(alvo)
    except (TypeError, ValueError):
        return {}
    if atual <= 0:
        return {}

    def conv(chave):
        try:
            return round(float(info[chave]) / atual * preco_bdr, 2)
        except (TypeError, ValueError, KeyError):
            return None

    return {
        "alvo_medio": round(alvo_m / atual * preco_bdr, 2),
        "alvo_alto": conv("targetHighPrice"),
        "alvo_baixo": conv("targetLowPrice"),
        "recomendacao": info.get("recommendationKey"),
        "analistas": info.get("numberOfAnalystOpinions"),
        "fonte": "Yahoo Finance · convertido para R$ por BDR",
    }


# ---------------------------------------------------------------------------
# Agentes
# ---------------------------------------------------------------------------

@app.post("/api/llm/models")
def api_llm_models(body: dict = Body(...)):
    """Modelos que a chave informada pode usar naquele provedor."""
    provider = (body.get("provider") or "").strip()
    api_key = (body.get("api_key") or "").strip()
    try:
        return agents.list_models(provider, api_key)
    except agents.LLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/agents/chat")
def api_agent_chat(body: dict = Body(...)):
    """Conversa livre com a mesa, no contexto do ativo aberto na tela."""
    slot = body.get("slot") or {}
    api_key = (slot.get("api_key") or "").strip()
    model = (slot.get("model") or "").strip()
    if not api_key or not model:
        raise HTTPException(status_code=400,
                            detail="Configure um slot com chave e modelo em ⚙ Modelos de IA.")

    pergunta = (body.get("pergunta") or "").strip()
    if not pergunta:
        raise HTTPException(status_code=400, detail="Escreva uma pergunta.")

    # Quem fala: um especialista, a mesa junta (None) ou a conclusão da rodada.
    agente = (body.get("agente") or "").strip() or None
    if agente and agente != "sintese" and agente not in agents.AGENTS:
        raise HTTPException(status_code=400, detail=f"Agente desconhecido: {agente}")
    if agente == "sintese":
        pergunta = agents.monta_pergunta_sintese(pergunta, body.get("respostas") or [])

    ticker = (body.get("ticker") or "").upper().strip()
    tela = (body.get("tela") or "").strip().lower()
    if ticker and (universe.get(ticker) or bdrs.get(ticker)):
        payload = api_company(ticker)
        contexto = agents.build_context(
            payload,
            body.get("assumptions") or payload["assumptions"],
            body.get("resultado") or {},
            payload.get("macro") or {},
        )
    elif tela in ("acoes", "etfs", "bdrs"):
        # Telas de lista: a mesa enxerga a tabela inteira que está na tela —
        # é o que permite perguntar sobre o conjunto ("quais para uma carteira?").
        macro_data = market.macro()
        if tela == "acoes":
            contexto = agents.contexto_lista_acoes(_overview_rows(), macro_data,
                                                   universe.SECTORS)
        elif tela == "etfs":
            contexto = agents.contexto_lista_etfs(_etf_rows(), macro_data,
                                                  etfs.CATEGORIES)
        else:
            contexto = agents.contexto_lista_bdrs(_bdr_rows(), macro_data,
                                                  bdrs.SECTORS)
        if ticker:
            # ETF aberto: fora do universo de valuation, mas o ativo em foco
            # entra no contexto para a conversa não fingir que não o vê.
            contexto = f"O usuário está com {ticker} aberto na tela.\n\n" + contexto
    else:
        # Sem ativo nem tela conhecida: a conversa ainda tem o macro do dia.
        macro_data = market.macro()
        linhas = ["Nenhum ativo aberto no painel — o usuário está numa tela de lista.",
                  "MACRO DO DIA"]
        linhas += [f"  {k.upper()}: {v.get('value')} ({v.get('source')})"
                   for k, v in (macro_data or {}).items() if isinstance(v, dict)]
        contexto = "\n".join(linhas)

    try:
        texto = agents.chat_conversa(slot.get("provider"), api_key, model, contexto,
                                     body.get("historico") or [], pergunta, agente)
    except agents.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"texto": texto, "modelo": model, "provedor": slot.get("provider"),
            "ticker": ticker or None, "agente": agente}


@app.post("/api/agents/run")
def api_agent_run(body: dict = Body(...)):
    agent_key = body.get("agent")
    slot = body.get("slot") or {}
    if agent_key not in agents.AGENTS:
        raise HTTPException(status_code=400, detail=f"Agente desconhecido: {agent_key}")

    provider = slot.get("provider")
    api_key = (slot.get("api_key") or "").strip()
    model = (slot.get("model") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400,
                            detail="Slot sem chave de API. Configure em ⚙ Modelos de IA.")
    if not model:
        raise HTTPException(status_code=400, detail="Slot sem modelo definido.")

    ticker = (body.get("ticker") or "").upper().strip()
    if not universe.get(ticker) and not bdrs.get(ticker):
        raise HTTPException(status_code=400, detail=f"Ticker inválido: {ticker}")

    payload = api_company(ticker)
    contexto = agents.build_context(
        payload,
        body.get("assumptions") or payload["assumptions"],
        body.get("resultado") or {},
        payload.get("macro") or {},
    )
    pergunta = (body.get("pergunta") or "").strip()
    user = f"CONTEXTO\n========\n{contexto}\n"

    # O Radar de Contexto abre a rodada e o que ele levantou entra aqui. Vem
    # cercado e rotulado: é a única parte do contexto que NÃO saiu das
    # demonstrações, e os outros agentes precisam saber disso para não tratar
    # post de rede social como se fosse fato relevante.
    radar = (body.get("radar") or "").strip()
    if radar and agent_key != "contexto":
        user += (
            "\nLEVANTAMENTO EXTERNO (do Radar de Contexto)\n"
            "===========================================\n"
            "ATENÇÃO: o bloco abaixo NÃO veio das demonstrações. Ele foi levantado no X e na "
            "imprensa por outro agente, e pode conter boato, opinião de quem está posicionado "
            "e informação falsa. Trate cada item como HIPÓTESE A CONFERIR, nunca como fato "
            "estabelecido. Quando citar algo daqui, diga que é não verificado. Se um item "
            "contradiz as demonstrações acima, as demonstrações vencem.\n\n"
            f"{radar[:6000]}\n")

    # Cético e Moderador leem a rodada: sem as falas, não há o que contestar
    # nem o que mapear. Vem depois do contexto de propósito — o que os agentes
    # disseram é matéria de discussão, não fonte.
    falas = body.get("falas") or {}
    if falas and agents.AGENTS[agent_key].get("le_a_mesa"):
        blocos = []
        for chave, texto in falas.items():
            nome = (agents.AGENTS.get(chave) or {}).get("label", chave)
            if texto and chave != agent_key:
                blocos.append(f"--- {nome} ---\n{str(texto)[:4000]}")
        if blocos:
            user += ("\nFALAS DA MESA\n=============\n"
                     "O que os outros agentes escreveram nesta rodada. Isto é OPINIÃO deles, "
                     "não dado: o CONTEXTO acima é que manda.\n\n" + "\n\n".join(blocos) + "\n")

    if pergunta:
        user += f"\nPERGUNTA ADICIONAL DO USUÁRIO\n============================\n{pergunta}\n"

    try:
        texto = agents.chat(provider, api_key, model,
                            agents.AGENTS[agent_key]["system"], user,
                            buscar=bool(agents.AGENTS[agent_key].get("busca_ao_vivo")))
    except agents.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    resposta = {"agent": agent_key, "ticker": ticker, "texto": texto,
                "modelo": model, "provedor": provider}
    if agent_key == "premissas":
        proposta = agents.parse_assumption_json(texto)
        if proposta:
            resposta["proposta"] = proposta
    return resposta


# ---------------------------------------------------------------------------
# Manutenção
# ---------------------------------------------------------------------------

@app.post("/api/cache/clear")
def api_cache_clear():
    removed = cache.clear()
    cvm.limpar_cache()
    cvm._shares_table.cache_clear()
    return {"ok": True, "arquivos_removidos": removed}


@app.get("/api/health")
def api_health():
    return {"ok": True, "cvm": cvm.available(), "demo": DEMO_MODE,
            "fonte_mercado": market.source_label(), "tickers": len(universe.TICKERS)}


# ---------------------------------------------------------------------------
# Front-end
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/empresa")
def empresa():
    return FileResponse(WEB_DIR / "empresa.html")


@app.get("/etfs")
def etfs_page():
    return FileResponse(WEB_DIR / "etfs.html")


@app.get("/etf")
def etf_page():
    return FileResponse(WEB_DIR / "etf.html")


@app.get("/bdrs")
def bdrs_page():
    return FileResponse(WEB_DIR / "bdrs.html")


@app.exception_handler(404)
def not_found(_request, exc):
    return JSONResponse(status_code=404, content={"detail": getattr(exc, "detail", "não encontrado")})


app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
