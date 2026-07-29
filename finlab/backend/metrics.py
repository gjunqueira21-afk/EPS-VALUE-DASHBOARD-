"""Métricas fundamentalistas derivadas das séries da CVM + dados de mercado.

Regra geral do módulo: nada é estimado silenciosamente. Se a conta não
existe, o campo vem `None` e o painel mostra "—". Cada indicador carrega o
ano-base de onde saiu, porque nem toda empresa tem o mesmo último exercício
publicado.
"""

from __future__ import annotations

from typing import Optional

from . import cvm, market, universe
from .settings import DEMO_MODE

# Alíquota efetiva usada no NOPAT do ROIC (IRPJ 25% + CSLL 9%).
TAX_RATE = 0.34


# ---------------------------------------------------------------------------
# Helpers de série
# ---------------------------------------------------------------------------

def last_valid(values: list, years: list[int]) -> tuple[Optional[float], Optional[int]]:
    """Último valor não-nulo de uma série anual, com o ano correspondente."""
    for value, year in zip(reversed(values or []), reversed(years or [])):
        if value is not None:
            return float(value), int(year)
    return None, None


def div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def cagr(values: list, years: list[int], span: int = 3) -> Optional[float]:
    """CAGR entre o último ano válido e o ano `span` exercícios antes.

    Só é calculado quando ambas as pontas são positivas — CAGR com base
    negativa não tem interpretação econômica.
    """
    pairs = [(y, v) for y, v in zip(years or [], values or []) if v is not None]
    if len(pairs) < span + 1:
        return None
    end_year, end = pairs[-1]
    start_candidates = [(y, v) for y, v in pairs if y <= end_year - span]
    if not start_candidates:
        return None
    start_year, start = start_candidates[-1]
    n = end_year - start_year
    if n <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / n) - 1


def positive_years(values: list, window: int = 5) -> Optional[float]:
    """Fração dos últimos `window` exercícios com valor positivo."""
    vals = [v for v in (values or []) if v is not None][-window:]
    if len(vals) < 3:
        return None
    return sum(1 for v in vals if v > 0) / len(vals)


# ---------------------------------------------------------------------------
# Fundamentos por empresa
# ---------------------------------------------------------------------------

def fundamentals(ticker: str) -> dict:
    """Séries + indicadores contábeis de uma empresa (sem dados de mercado)."""
    comp = universe.get(ticker)
    if comp is None:
        return {}
    data = cvm.annual_series(comp.cd_cvm) if comp.cd_cvm else {
        "years": [], "financial": False, "series": {}, "cnpj": None}

    years = data.get("years") or []
    series = data.get("series") or {}
    fin = bool(data.get("financial")) or universe.is_financial(ticker)

    def lv(key):
        return last_valid(series.get(key, []), years)

    receita, ano_receita = lv("receita")
    ebit, _ = lv("ebit")
    ebitda, _ = lv("ebitda")
    da, _ = lv("depreciacao")
    lucro, ano_lucro = lv("lucro_liquido")
    lucro_bruto, _ = lv("lucro_bruto")
    pl, _ = lv("patrimonio_liquido")
    ativo, _ = lv("ativo_total")
    div_bruta, _ = lv("divida_bruta")
    div_liq, _ = lv("divida_liquida")
    caixa, _ = lv("caixa_total")
    fco, _ = lv("fco")
    capex, _ = lv("capex")
    fcl, _ = lv("fcl")

    capital_investido = None
    if pl is not None and div_bruta is not None:
        capital_investido = pl + div_bruta

    ind = {
        "mg_bruta": div(lucro_bruto, receita),
        "mg_ebitda": None if fin else div(ebitda, receita),
        "mg_ebit": div(ebit, receita),
        "mg_liquida": div(lucro, receita),
        "roe": div(lucro, pl),
        "roa": div(lucro, ativo),
        "roic": None if fin else div((ebit * (1 - TAX_RATE)) if ebit is not None else None,
                                     capital_investido),
        "nd_ebitda": None if fin else div(div_liq, ebitda),
        "nd_equity": None if fin else div(div_liq, pl),
        "alavancagem": div(ativo, pl) if fin else None,
        "cash_conversion": None if fin else div(fco, ebitda),
        "fcf_margin": None if fin else div(fcl, receita),
        "cagr_receita_3a": cagr(series.get("receita", []), years, 3),
        "cagr_lucro_3a": cagr(series.get("lucro_liquido", []), years, 3),
        "cagr_ebitda_3a": None if fin else cagr(series.get("ebitda", []), years, 3),
        "consistencia_lucro": positive_years(series.get("lucro_liquido", []), 5),
    }

    return {
        "ticker": comp.ticker,
        "name": comp.name,
        "sector": comp.sector,
        "cd_cvm": comp.cd_cvm,
        "cnpj": data.get("cnpj"),
        "denom": data.get("denom") or comp.cvm_name,
        "financial": fin,
        "years": years,
        "series": series,
        "last_year": data.get("last_year"),
        "base": {
            "receita": receita, "ano_receita": ano_receita,
            "ebit": ebit, "ebitda": ebitda, "depreciacao": da,
            "lucro_liquido": lucro, "ano_lucro": ano_lucro,
            "lucro_bruto": lucro_bruto,
            "patrimonio_liquido": pl, "ativo_total": ativo,
            "divida_bruta": div_bruta, "divida_liquida": div_liq, "caixa": caixa,
            "fco": fco, "capex": capex, "fcl": fcl,
            "capital_investido": capital_investido,
        },
        "indicadores": ind,
    }


# ---------------------------------------------------------------------------
# Mercado + múltiplos
# ---------------------------------------------------------------------------

def _demo_price(ticker: str, base_equity: Optional[float]) -> float:
    """Preço sintético determinístico para o modo demonstração."""
    seed = sum((i + 1) * ord(ch) for i, ch in enumerate(ticker))
    return round(8 + (seed % 730) / 10.0, 2)


def market_snapshot(ticker: str, series: list[tuple[str, float]],
                    brapi: Optional[dict], fund: dict) -> dict:
    """Preço, performance, ações em circulação e valor de mercado."""
    perf = market.performance(series)
    price = perf.get("price")
    source = "histórico"

    if brapi:
        live = brapi.get("regularMarketPrice")
        if live:
            price = float(live)
            source = "BRAPI"
            chg = brapi.get("regularMarketChangePercent")
            if chg is not None:
                perf["day"] = float(chg) / 100.0
            perf["price"] = price
    elif price is not None:
        source = market.source_label()

    if price is None and DEMO_MODE:
        price = _demo_price(ticker, fund.get("base", {}).get("patrimonio_liquido"))
        source = "demo"

    # `shares` = ações emitidas pela companhia (base contábil).
    # `shares_quote` = papéis equivalentes ao que é negociado: em units,
    # divide-se pelo número de ações que compõem cada unit.
    shares = None
    shares_source = None
    if brapi and brapi.get("sharesOutstanding"):
        shares, shares_source = float(brapi["sharesOutstanding"]), "BRAPI"
    if not shares:
        shares = cvm.shares_outstanding(fund.get("cnpj"))
        shares_source = "capital social CVM" if shares else None
    if not shares:
        shares = cvm.shares_from_eps(fund.get("cd_cvm"))
        shares_source = "implícito no LPA (CVM)" if shares else None

    ratio = universe.unit_ratio(ticker)
    shares_quote = (shares / ratio) if shares else None

    market_cap = None
    cap_source = None
    if brapi and brapi.get("marketCap"):
        market_cap, cap_source = float(brapi["marketCap"]), "BRAPI"
    elif price is not None and shares_quote:
        sufixo = f" ÷ {ratio} (unit)" if ratio > 1 else ""
        market_cap = price * shares_quote
        cap_source = f"preço × ações{sufixo} · {shares_source}"

    return {
        "price": price,
        "price_date": perf.get("date"),
        "price_source": source,
        "perf": {k: perf.get(k) for k in ("day", "week", "m3", "m12", "ytd")},
        "shares": shares,
        "shares_quote": shares_quote,
        "unit_ratio": ratio,
        "shares_source": shares_source,
        "market_cap": market_cap,
        "market_cap_source": cap_source,
        "points": len(series or []),
    }


def multiples(fund: dict, snap: dict, brapi: Optional[dict]) -> dict:
    """Múltiplos de mercado. EV usa dívida líquida contábil da CVM."""
    base = fund.get("base", {})
    ind = fund.get("indicadores", {})
    cap = snap.get("market_cap")
    fin = fund.get("financial")

    ev = None
    if cap is not None and not fin:
        nd = base.get("divida_liquida")
        ev = cap + nd if nd is not None else None

    dy = None
    if brapi:
        raw = brapi.get("dividendYield")
        if raw is not None:
            # A BRAPI devolve o DY em pontos percentuais (ex.: 8.4 = 8,4%).
            dy = float(raw) / 100.0

    # Por papel negociado (unit, quando for o caso), para comparar com o preço.
    lpa = div(base.get("lucro_liquido"), snap.get("shares_quote"))
    vpa = div(base.get("patrimonio_liquido"), snap.get("shares_quote"))

    return {
        "pl": div(cap, base.get("lucro_liquido")),
        "pvp": div(cap, base.get("patrimonio_liquido")),
        "ev_ebitda": div(ev, base.get("ebitda")),
        "ev_ebit": div(ev, base.get("ebit")),
        "psr": div(cap, base.get("receita")),
        "dy": dy,
        "roe": ind.get("roe"),
        "mg_ebitda": ind.get("mg_ebitda"),
        "nd_ebitda": ind.get("nd_ebitda"),
        "ev": ev,
        "lpa": lpa,
        "vpa": vpa,
        "fcf_yield": div(base.get("fcl"), cap),
    }
