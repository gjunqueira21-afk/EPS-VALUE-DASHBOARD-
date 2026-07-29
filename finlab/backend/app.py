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

from . import agents, cache, cvm, market, metrics, scoring, universe, valuation
from .settings import DEMO_MODE, TTL_CVM, TTL_QUOTE, WEB_DIR

app = FastAPI(title="Gab's FinLab", version="2.0", docs_url="/api/docs")


# ---------------------------------------------------------------------------
# Camada de dados
# ---------------------------------------------------------------------------

def _fundamentals(ticker: str) -> dict:
    return cache.memoize(f"fund:v3:{ticker}", TTL_CVM, lambda: metrics.fundamentals(ticker)) or {}


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
            "source": market.source_label(),
            "demo": DEMO_MODE,
            "providers": market.provider_status(),
            "cvm_disponivel": cvm.available(),
        }

    return cache.memoize("overview:v4", TTL_QUOTE, build) or {"rows": []}


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
    return universe.as_payload()


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
    prem = valuation.assumptions(fund, snap, macro_data, brapi)

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
# Agentes
# ---------------------------------------------------------------------------

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
    if not universe.get(ticker):
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
    if pergunta:
        user += f"\nPERGUNTA ADICIONAL DO USUÁRIO\n============================\n{pergunta}\n"

    try:
        texto = agents.chat(provider, api_key, model,
                            agents.AGENTS[agent_key]["system"], user)
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
    cvm._frames.cache_clear()
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


@app.exception_handler(404)
def not_found(_request, exc):
    return JSONResponse(status_code=404, content={"detail": getattr(exc, "detail", "não encontrado")})


app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
