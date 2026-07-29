"""Testes do Gab's FinLab.

Rodar: python -m pytest finlab/tests -q

Cobrem o que quebra silenciosamente: extração contábil da CVM, escalas
(units, LPA em milhares), consistência dos múltiplos, curvas do score e o
proxy de LLM nos três formatos de API. O motor de valuation em JavaScript
tem teste próprio em finlab/tests/test_engine.py (roda no navegador).
"""

from __future__ import annotations

import json
import sys
import threading
import http.server
import socketserver
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from finlab.backend import agents, cvm, metrics, scoring, universe, valuation  # noqa: E402
from finlab.backend import market  # noqa: E402


# ---------------------------------------------------------------------------
# Universo
# ---------------------------------------------------------------------------

def test_universo_tem_90_acoes_sem_duplicatas():
    assert len(universe.UNIVERSE) == 90
    tickers = [c.ticker for c in universe.UNIVERSE]
    assert len(set(tickers)) == 90


def test_todo_setor_declarado_tem_empresa():
    usados = {c.sector for c in universe.UNIVERSE}
    assert usados == set(universe.SECTORS)


def test_metricas_do_setor_sao_conhecidas():
    for key, meta in universe.SECTORS.items():
        assert 1 <= len(meta["metrics"]) <= 4, key
        for m in meta["metrics"]:
            assert m in universe.METRIC_LABELS, (key, m)
            assert m in universe.METRIC_FORMAT, (key, m)


def test_units_tem_razao_maior_que_um():
    for ticker, ratio in universe.UNIT_RATIO.items():
        assert universe.get(ticker) is not None, ticker
        assert ratio >= 2
        assert ticker.endswith("11"), "só units terminam em 11"


# ---------------------------------------------------------------------------
# Extração da CVM
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not cvm.available(), reason="parquets da CVM ausentes")
def test_series_anuais_da_petrobras():
    dados = cvm.annual_series("009512")
    assert dados["years"], "sem exercícios"
    assert not dados["financial"]
    serie = dados["series"]
    receita = [v for v in serie["receita"] if v is not None]
    assert receita and min(receita) > 1e11, "receita da Petrobras acima de R$ 100 bi"
    # EBITDA precisa ser coerente com EBIT + D&A no mesmo ano
    for i, ano in enumerate(dados["years"]):
        ebit, da, ebitda = serie["ebit"][i], serie["depreciacao"][i], serie["ebitda"][i]
        if None in (ebit, da, ebitda):
            continue
        assert abs(ebitda - (ebit + abs(da))) < 1.0, ano


@pytest.mark.skipif(not cvm.available(), reason="parquets da CVM ausentes")
def test_capex_sempre_negativo_e_fcl_bate_com_fco_menos_capex():
    for ticker in ("VALE3", "WEGE3", "EQTL3", "SUZB3", "MGLU3"):
        comp = universe.get(ticker)
        dados = cvm.annual_series(comp.cd_cvm)
        serie = dados["series"]
        for i in range(len(dados["years"])):
            capex, fco, fcl = serie["capex"][i], serie["fco"][i], serie["fcl"][i]
            if capex is not None:
                assert capex <= 0, (ticker, dados["years"][i])
            if None not in (capex, fco, fcl):
                assert abs(fcl - (fco - abs(capex))) < 1.0, (ticker, dados["years"][i])


@pytest.mark.skipif(not cvm.available(), reason="parquets da CVM ausentes")
def test_bancos_sao_detectados_e_nao_ganham_ebitda():
    for ticker in ("ITUB4", "BBAS3", "BBDC4"):
        comp = universe.get(ticker)
        dados = cvm.annual_series(comp.cd_cvm)
        assert dados["financial"], ticker
        assert all(v is None for v in dados["series"]["ebitda"]), ticker
        assert all(v is None for v in dados["series"]["divida_liquida"]), ticker


@pytest.mark.skipif(not cvm.available(), reason="parquets da CVM ausentes")
def test_acoes_implicitas_no_lpa_corrigem_a_escala():
    """A conta 3.99 vem inflada em 1.000× pelo pipeline; o fallback corrige."""
    # Raia Drogasil: ~1,65 bilhão de ações.
    acoes = cvm.shares_from_eps("005258")
    assert acoes is not None
    assert 1e9 < acoes < 3e9, acoes


@pytest.mark.skipif(not cvm.available(), reason="parquets da CVM ausentes")
def test_capital_social_bate_com_ordem_de_grandeza_conhecida():
    casos = {"33.000.167/0001-01": (10e9, 15e9),   # Petrobras
             "33.592.510/0001-54": (4e9, 5e9),     # Vale
             "60.872.504/0001-23": (9e9, 13e9)}    # Itaú Unibanco
    for cnpj, (lo, hi) in casos.items():
        acoes = cvm.shares_outstanding(cnpj)
        assert acoes is not None and lo < acoes < hi, (cnpj, acoes)


# ---------------------------------------------------------------------------
# Métricas e múltiplos
# ---------------------------------------------------------------------------

def test_last_valid_pega_o_ultimo_nao_nulo():
    assert metrics.last_valid([1, None, 3, None], [2020, 2021, 2022, 2023]) == (3.0, 2022)
    assert metrics.last_valid([None, None], [2020, 2021]) == (None, None)
    assert metrics.last_valid([], []) == (None, None)


def test_cagr_exige_pontas_positivas():
    anos = [2020, 2021, 2022, 2023]
    assert metrics.cagr([100, 110, 121, 133.1], anos, 3) == pytest.approx(0.1, abs=1e-4)
    assert metrics.cagr([-10, 5, 8, 12], anos, 3) is None       # base negativa
    assert metrics.cagr([100, 110], [2022, 2023], 3) is None    # série curta


def test_div_protege_denominador():
    assert metrics.div(10, 2) == 5
    assert metrics.div(10, 0) is None
    assert metrics.div(None, 2) is None


def test_positive_years():
    assert metrics.positive_years([1, 2, -1, 4, 5]) == pytest.approx(0.8)
    assert metrics.positive_years([1, 2]) is None  # amostra insuficiente


def test_unit_divide_o_valor_de_mercado():
    fund = {"base": {"lucro_liquido": 1e9, "patrimonio_liquido": 5e9, "divida_liquida": None,
                     "ebitda": None, "ebit": None, "receita": None, "fcl": None},
            "indicadores": {}, "financial": True, "cnpj": None, "cd_cvm": None}
    serie = [("2026-01-02", 30.0), ("2026-01-03", 30.0)]

    snap_unit = metrics.market_snapshot("SANB11", serie, None, fund)
    snap_normal = metrics.market_snapshot("BBDC4", serie, None, fund)
    assert snap_unit["unit_ratio"] == 2
    assert snap_normal["unit_ratio"] == 1
    if snap_unit["shares"] and snap_normal["shares"]:
        assert snap_unit["shares_quote"] == snap_unit["shares"] / 2


def test_multiplos_sao_consistentes_com_os_insumos():
    fund = {"base": {"lucro_liquido": 200.0, "patrimonio_liquido": 1000.0,
                     "divida_liquida": 300.0, "ebitda": 400.0, "ebit": 350.0,
                     "receita": 2000.0, "fcl": 150.0},
            "indicadores": {"roe": 0.2, "mg_ebitda": 0.2, "nd_ebitda": 0.75},
            "financial": False}
    snap = {"market_cap": 2000.0, "shares_quote": 100.0, "shares": 100.0}
    mult = metrics.multiples(fund, snap, None)
    assert mult["pl"] == pytest.approx(10.0)
    assert mult["pvp"] == pytest.approx(2.0)
    assert mult["ev"] == pytest.approx(2300.0)
    assert mult["ev_ebitda"] == pytest.approx(5.75)
    assert mult["lpa"] == pytest.approx(2.0)
    assert mult["vpa"] == pytest.approx(10.0)


def test_financeira_nao_recebe_enterprise_value():
    fund = {"base": {"lucro_liquido": 100.0, "patrimonio_liquido": 500.0,
                     "divida_liquida": None, "ebitda": None, "ebit": None,
                     "receita": 900.0, "fcl": None},
            "indicadores": {}, "financial": True}
    mult = metrics.multiples(fund, {"market_cap": 1000.0, "shares_quote": 10.0}, None)
    assert mult["ev"] is None
    assert mult["ev_ebitda"] is None


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------

def test_curva_interpola_e_satura():
    ancoras = [(0.0, 0.0), (0.10, 50.0), (0.20, 100.0)]
    assert scoring.curve(0.05, ancoras) == pytest.approx(25.0)
    assert scoring.curve(0.15, ancoras) == pytest.approx(75.0)
    assert scoring.curve(-1.0, ancoras) == 0.0      # abaixo do piso
    assert scoring.curve(9.0, ancoras) == 100.0     # acima do teto
    assert scoring.curve(None, ancoras) is None


def test_curva_de_alavancagem_premia_menos_divida():
    assert scoring.curve(0.5, scoring.ND_EBITDA) > scoring.curve(3.5, scoring.ND_EBITDA)
    assert scoring.curve(-0.5, scoring.ND_EBITDA) > 95.0     # caixa líquido
    assert scoring.curve(-2.0, scoring.ND_EBITDA) == 100.0   # caixa líquido alto satura


def test_score_fica_entre_0_e_100_e_reporta_cobertura():
    otima = {"roe": 0.30, "roic": 0.25, "mg_liquida": 0.25, "nd_ebitda": -0.5,
             "nd_equity": -0.2, "mg_ebitda": 0.45, "cagr_receita_3a": 0.25,
             "cagr_ebitda_3a": 0.25, "cash_conversion": 1.0, "fcf_margin": 0.18,
             "consistencia_lucro": 1.0}
    pessima = {k: (-0.2 if "cagr" in k or "margin" in k or k.startswith("mg") or k in
                   ("roe", "roic", "cash_conversion") else 6.0) for k in otima}
    pessima["consistencia_lucro"] = 0.0

    boa = scoring.score(otima)
    ruim = scoring.score(pessima)
    assert 90 <= boa["total"] <= 100
    assert 0 <= ruim["total"] <= 20
    assert boa["cobertura"] == pytest.approx(1.0)
    assert not boa["parcial"]


def test_score_com_dado_faltando_nao_e_punido_mas_marca_cobertura():
    parcial = scoring.score({"roe": 0.20})
    assert parcial["total"] is not None
    assert parcial["cobertura"] < 0.3
    assert parcial["parcial"] is True


def test_score_sem_indicador_algum_nao_inventa_nota():
    assert scoring.score({})["total"] is None
    assert scoring.grade(None) == "—"
    assert scoring.band(None) == "none"


def test_perfil_financeiro_usa_outros_pilares():
    pilares = {p["key"] for p in scoring.score({"roe": 0.2}, financial=True)["pilares"]}
    assert "caixa" not in pilares          # conversão de caixa não se aplica a banco
    assert "rentabilidade" in pilares


# ---------------------------------------------------------------------------
# Premissas de valuation
# ---------------------------------------------------------------------------

def _fund_teste():
    return {
        "sector": "INDUSTRIA_TECH", "financial": False,
        "base": {"divida_bruta": 1000.0, "divida_liquida": 500.0, "caixa": 500.0},
        "indicadores": {"cagr_receita_3a": 0.08},
        "series": {"fcl": [100.0, 120.0, 140.0], "ebit": [200.0, 220.0, 240.0]},
    }


def test_premissas_respeitam_wacc_maior_que_perpetuidade():
    macro = {"selic": {"value": 14.15}, "ipca": {"value": 4.6}, "cdi": {"value": 14.15},
             "prefixado_10a": {"value": 14.8}, "ntnb_10a": {"value": 8.1}}
    prem = valuation.assumptions(_fund_teste(), {"market_cap": 5000.0, "shares_quote": 100.0,
                                                 "price": 40.0}, macro)
    assert prem["g_terminal"] < prem["wacc"] - 0.01
    assert prem["rf"] == pytest.approx(0.148)
    assert prem["rf_modo"] == "pre10"
    assert set(prem["rf_opcoes"]) == {"pre10", "ntnb", "selic"}
    assert prem["fcf_base"] == pytest.approx(120.0)     # média dos 3 últimos
    assert prem["ebit_normalizado"] == pytest.approx(220.0)
    assert len(prem["growth"]) == 5


def test_premissas_sem_curva_caem_para_a_selic():
    prem = valuation.assumptions(_fund_teste(), {"market_cap": 5000.0, "shares_quote": 100.0},
                                 {"selic": {"value": 14.15}, "ipca": {"value": 4.6}})
    assert prem["rf_modo"] == "selic"
    assert prem["rf"] == pytest.approx(0.1415)


def test_dcf_nao_se_aplica_a_instituicao_financeira():
    fund = _fund_teste()
    fund["financial"] = True
    prem = valuation.assumptions(fund, {"market_cap": 1.0, "shares_quote": 1.0}, {})
    assert prem["aplicavel"] is False
    assert "financeira" in prem["motivo_nao_aplicavel"].lower()


def test_estrutura_de_capital_vem_do_mercado_quando_ha_dado():
    prem = valuation.assumptions(_fund_teste(), {"market_cap": 3000.0, "shares_quote": 100.0}, {})
    assert prem["wd"] == pytest.approx(1000.0 / 4000.0)
    prem_sem = valuation.assumptions(_fund_teste(), {}, {})
    assert prem_sem["wd"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Utilidades de mercado
# ---------------------------------------------------------------------------

def test_numero_pt_br():
    assert market._pt_number("14,15%") == pytest.approx(14.15)
    assert market._pt_number("5.1177") == pytest.approx(5.1177)
    assert market._pt_number("175.335") == pytest.approx(175335.0)
    assert market._pt_number("1.234.567") == pytest.approx(1234567.0)
    assert market._pt_number("") is None
    assert market._pt_number(None) is None


def test_performance_calcula_janelas_e_respeita_tolerancia():
    from datetime import date, timedelta
    hoje = date(2026, 7, 27)
    serie = []
    for i in range(400, -1, -1):
        d = hoje - timedelta(days=i)
        serie.append((d.isoformat(), 100.0 * (1.0005 ** (400 - i))))
    perf = market.performance(serie, hoje)
    assert perf["price"] == pytest.approx(serie[-1][1])
    for janela in ("day", "week", "m3", "m12", "ytd"):
        assert perf[janela] is not None, janela
        assert perf[janela] > 0

    # Série curta: janelas longas não podem ser inventadas.
    curta = serie[-20:]
    perf_curta = market.performance(curta, hoje)
    assert perf_curta["week"] is not None
    assert perf_curta["m3"] is None
    assert perf_curta["m12"] is None
    assert perf_curta["ytd"] is None


def test_performance_sem_serie():
    assert market.performance([])["price"] is None


# ---------------------------------------------------------------------------
# Proxy de LLM
# ---------------------------------------------------------------------------

class _MockHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        corpo = json.loads(self.rfile.read(tamanho) or b"{}")
        self.server.recebido[self.path] = {"body": corpo, "headers": dict(self.headers)}

        if self.path.startswith("/openai"):
            payload = {"choices": [{"message": {"content": "OK-OPENAI"}}]}
        elif self.path.startswith("/anthropic"):
            payload = {"content": [{"type": "text", "text": "OK-"},
                                   {"type": "text", "text": "ANTHROPIC"}]}
        elif self.path.startswith("/status/"):
            codigo = int(self.path.rsplit("/", 1)[-1])
            self.send_response(codigo)
            self.end_headers()
            self.wfile.write(b"erro simulado")
            return
        else:
            payload = {"candidates": [{"content": {"parts": [{"text": "OK-GEMINI"}]}}]}

        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def mock_llm(monkeypatch):
    servidor = socketserver.TCPServer(("127.0.0.1", 0), _MockHandler)
    servidor.recebido = {}
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}"

    monkeypatch.setitem(agents.PROVIDERS["openrouter"], "url", base + "/openai")
    monkeypatch.setitem(agents.PROVIDERS["anthropic"], "url", base + "/anthropic")
    monkeypatch.setitem(agents.PROVIDERS["google"], "url", base + "/gemini")
    yield servidor, base
    servidor.shutdown()


def test_proxy_llm_nos_tres_formatos(mock_llm):
    servidor, _ = mock_llm
    assert agents.chat("openrouter", "sk-x", "m", "SYS", "USER") == "OK-OPENAI"
    assert agents.chat("anthropic", "sk-x", "m", "SYS", "USER") == "OK-ANTHROPIC"
    assert agents.chat("google", "sk-x", "m", "SYS", "USER") == "OK-GEMINI"

    aberto = servidor.recebido["/openai"]
    assert aberto["headers"]["Authorization"] == "Bearer sk-x"
    assert aberto["body"]["messages"][0]["content"] == "SYS"

    claude = servidor.recebido["/anthropic"]
    assert claude["headers"]["x-api-key"] == "sk-x"
    assert claude["body"]["system"] == "SYS"

    gemini_path = next(p for p in servidor.recebido if p.startswith("/gemini"))
    gemini = servidor.recebido[gemini_path]
    assert gemini["headers"]["x-goog-api-key"] == "sk-x"


def test_proxy_llm_traduz_erros(mock_llm, monkeypatch):
    _, base = mock_llm
    for codigo, trecho in ((401, "rejeitada"), (429, "Limite"), (500, "HTTP 500")):
        monkeypatch.setitem(agents.PROVIDERS["openrouter"], "url", f"{base}/status/{codigo}")
        with pytest.raises(agents.LLMError, match=trecho):
            agents.chat("openrouter", "sk-x", "m", "s", "u")


def test_proxy_llm_exige_chave_e_provedor_valido():
    with pytest.raises(agents.LLMError, match="Chave"):
        agents.chat("openrouter", "", "m", "s", "u")
    with pytest.raises(agents.LLMError, match="desconhecido"):
        agents.chat("nao-existe", "k", "m", "s", "u")


def test_parser_de_premissas_do_agente_quant():
    texto = (
        "Analisando o momento:\n```json\n"
        '{"premissas": {"rf": 0.148, "beta": 1.1, "growth": [0.09, 0.08, 0.07, 0.06, 0.05],'
        ' "g_terminal": 0.04}, "justificativa": "ok", "confianca": "media"}\n```\n'
    )
    proposta = agents.parse_assumption_json(texto)
    assert proposta["premissas"]["beta"] == 1.1
    assert len(proposta["premissas"]["growth"]) == 5
    assert agents.parse_assumption_json("sem json nenhum") is None
    assert agents.parse_assumption_json("") is None


def test_contexto_dos_agentes_nao_estoura_com_dados_faltando():
    payload = {"fundamentals": {"name": "X", "ticker": "XPTO3", "sector": "VAREJO",
                                "financial": False, "last_year": 2025,
                                "base": {}, "indicadores": {}, "series": {}, "years": []},
               "market": {"perf": {}}, "multiples": {}, "score": {}}
    texto = agents.build_context(payload, {}, {}, {})
    assert "XPTO3" in texto
    assert "sem dado" in texto


def test_todos_os_agentes_tem_prompt_e_descricao():
    for key, agente in agents.AGENTS.items():
        assert agente["system"].strip()
        assert agente["label"] and agente["desc"] and agente["icon"]
        assert "português" in agente["system"].lower()
    assert {a["key"] for a in agents.agent_list()} == set(agents.AGENTS)
    assert {p["key"] for p in agents.provider_list()} == set(agents.PROVIDERS)
