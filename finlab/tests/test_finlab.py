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

    def _responde(self, payload, codigo=200):
        data = json.dumps(payload).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.server.recebido[self.path.split("?")[0]] = {"headers": dict(self.headers)}

        if self.path.startswith("/models/openai"):
            self._responde({"data": [{"id": "gpt-teste"}, {"id": "text-embedding-3"},
                                     {"id": "whisper-1"}, {"id": "gpt-teste"}]})
        elif self.path.startswith("/models/anthropic"):
            self._responde({"data": [{"id": "claude-teste", "display_name": "Claude Teste"}]})
        elif self.path.startswith("/models/google"):
            self._responde({"models": [
                {"name": "models/gemini-teste", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
            ]})
        elif self.path.startswith("/models/vazio"):
            self._responde({"data": []})
        elif self.path.startswith("/models/quebrado"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"nao sou json")
        elif self.path.startswith("/models/status/"):
            self.send_response(int(self.path.rsplit("/", 1)[-1]))
            self.end_headers()
            self.wfile.write(b"erro simulado")
        else:
            self._responde({"erro": "rota desconhecida"}, 404)

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        corpo = json.loads(self.rfile.read(tamanho) or b"{}")
        self.server.recebido[self.path] = {"body": corpo, "headers": dict(self.headers)}

        if self.path.startswith("/vazio/raciocinio"):
            # modelo de raciocínio: content vazio, texto no campo à parte
            payload = {"choices": [{"message": {"content": "",
                                                "reasoning": "VEIO-DO-RACIOCINIO"}}]}
        elif self.path.startswith("/vazio/truncado"):
            payload = {"choices": [{"message": {"content": ""},
                                    "finish_reason": "length"}]}
        elif self.path.startswith("/vazio/nulo"):
            payload = {"choices": [{"message": {"content": None}}]}
        elif self.path.startswith("/vazio/anthropic"):
            payload = {"content": [], "stop_reason": "max_tokens"}
        elif self.path.startswith("/vazio/gemini"):
            payload = {"candidates": [{"content": {"parts": []},
                                       "finishReason": "SAFETY"}]}
        elif self.path.startswith("/openai"):
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


def test_lista_de_modelos_le_a_api_do_provedor(mock_llm, monkeypatch):
    servidor, base = mock_llm
    monkeypatch.setitem(agents._MODEL_ENDPOINTS, "openrouter",
                        (base + "/models/openai", "bearer"))
    monkeypatch.setitem(agents._MODEL_ENDPOINTS, "anthropic",
                        (base + "/models/anthropic", "anthropic"))
    monkeypatch.setitem(agents._MODEL_ENDPOINTS, "google",
                        (base + "/models/google", "google"))

    r = agents.list_models("openrouter", "sk-x")
    assert r["fonte"] == "api" and r["aviso"] is None
    # embedding e whisper não servem para chat; duplicata some
    assert r["models"] == ["gpt-teste"]
    assert servidor.recebido["/models/openai"]["headers"]["Authorization"] == "Bearer sk-x"

    r = agents.list_models("anthropic", "sk-x")
    assert r["models"] == ["claude-teste"]
    assert servidor.recebido["/models/anthropic"]["headers"]["x-api-key"] == "sk-x"

    r = agents.list_models("google", "sk-x")
    # o prefixo "models/" some e o que só faz embedding fica de fora
    assert r["models"] == ["gemini-teste"]
    assert servidor.recebido["/models/google"]["headers"]["x-goog-api-key"] == "sk-x"


def test_lista_de_modelos_cai_no_catalogo_local_sem_quebrar(mock_llm, monkeypatch):
    _, base = mock_llm
    catalogo = agents.PROVIDERS["openrouter"]["models"]

    sem_chave = agents.list_models("openrouter", "")
    assert sem_chave["models"] == catalogo
    assert sem_chave["fonte"] == "catálogo local" and "Sem chave" in sem_chave["aviso"]

    casos = [("/models/status/401", "401"), ("/models/status/500", "HTTP 500"),
             ("/models/quebrado", "inesperada"), ("/models/vazio", "não listou")]
    for rota, trecho in casos:
        monkeypatch.setitem(agents._MODEL_ENDPOINTS, "openrouter", (base + rota, "bearer"))
        r = agents.list_models("openrouter", "sk-x")
        assert r["models"] == catalogo, rota
        assert trecho in r["aviso"], rota

    # provedor fora do ar: nada de exceção vazando para a tela
    monkeypatch.setitem(agents._MODEL_ENDPOINTS, "openrouter",
                        ("http://127.0.0.1:9/models", "bearer"))
    r = agents.list_models("openrouter", "sk-x")
    assert r["models"] == catalogo and "Não foi possível" in r["aviso"]

    with pytest.raises(agents.LLMError, match="desconhecido"):
        agents.list_models("nao-existe", "sk-x")


def test_conversa_leva_historico_e_contexto_nos_tres_formatos(mock_llm):
    servidor, _ = mock_llm
    hist = [{"role": "user", "content": "e a margem?"},
            {"role": "assistant", "content": "subiu"},
            {"role": "system", "content": "   "}]

    assert agents.chat_conversa(
        "openrouter", "sk-x", "m", "CTX", hist, "e a dívida?") == "OK-OPENAI"
    corpo = servidor.recebido["/openai"]["body"]
    assert corpo["messages"][0]["role"] == "system"
    assert "CTX" in corpo["messages"][0]["content"]
    # mensagem em branco não vira turno; a pergunta entra por último
    assert [m["role"] for m in corpo["messages"][1:]] == ["user", "assistant", "user"]
    assert corpo["messages"][-1]["content"] == "e a dívida?"

    assert agents.chat_conversa(
        "anthropic", "sk-x", "m", "CTX", hist, "e a dívida?") == "OK-ANTHROPIC"
    corpo = servidor.recebido["/anthropic"]["body"]
    assert "CTX" in corpo["system"]
    assert [m["role"] for m in corpo["messages"]] == ["user", "assistant", "user"]

    assert agents.chat_conversa(
        "google", "sk-x", "m", "CTX", hist, "e a dívida?") == "OK-GEMINI"
    rota = next(p for p in servidor.recebido if p.startswith("/gemini"))
    corpo = servidor.recebido[rota]["body"]
    assert "CTX" in corpo["systemInstruction"]["parts"][0]["text"]
    # o Gemini chama o papel do assistente de "model"
    assert [c["role"] for c in corpo["contents"]] == ["user", "model", "user"]


def test_conversa_nao_devolve_bolha_vazia(mock_llm, monkeypatch):
    """O bug do balão em branco: modelo de raciocínio ou resposta truncada
    devolviam string vazia, e a tela mostrava uma bolha sem nada dentro."""
    _, base = mock_llm

    # texto no campo de raciocínio é aproveitado em vez de virar vazio
    monkeypatch.setitem(agents.PROVIDERS["openrouter"], "url", base + "/vazio/raciocinio")
    assert agents.chat_conversa(
        "openrouter", "k", "m", "CTX", [], "e ai?") == "VEIO-DO-RACIOCINIO"

    # sem texto em lugar nenhum, o erro explica o motivo
    casos = [("/vazio/truncado", "limite de tokens"), ("/vazio/nulo", "vazia")]
    for rota, trecho in casos:
        monkeypatch.setitem(agents.PROVIDERS["openrouter"], "url", base + rota)
        with pytest.raises(agents.LLMError, match=trecho):
            agents.chat_conversa("openrouter", "k", "m", "CTX", [], "e ai?")

    monkeypatch.setitem(agents.PROVIDERS["anthropic"], "url", base + "/vazio/anthropic")
    with pytest.raises(agents.LLMError, match="limite de tokens"):
        agents.chat_conversa("anthropic", "k", "m", "CTX", [], "e ai?")

    monkeypatch.setitem(agents.PROVIDERS["google"], "url", base + "/vazio/gemini")
    with pytest.raises(agents.LLMError, match="SAFETY"):
        agents.chat_conversa("google", "k", "m", "CTX", [], "e ai?")


def test_cada_agente_fala_com_a_propria_especialidade(mock_llm):
    servidor, _ = mock_llm

    def sistema_de(agente):
        agents.chat_conversa("openrouter", "k", "m", "CTX", [], "e ai?", agente)
        return servidor.recebido["/openai"]["body"]["messages"][0]["content"]

    gestor = sistema_de("gestor")
    macro = sistema_de("macro")
    assert "gestor" in gestor.lower() and "posição" in gestor
    assert "economista" in macro.lower()
    assert gestor != macro

    # o quant, na conversa, escreve texto — o JSON é só da aba Mesa de IA
    quant = sistema_de("premissas")
    assert "NÃO devolva JSON" in quant

    # sem agente, é a mesa inteira falando junto
    mesa = sistema_de(None)
    assert "a mesa inteira" in mesa

    # a síntese recebe outro papel: fechar a reunião
    fim = sistema_de("sintese")
    assert "CONCLUSÃO" in fim and "fecha a reunião" in fim

    # o CONTEXTO entra em todos
    for s in (gestor, macro, quant, mesa, fim):
        assert "CTX" in s


def test_pergunta_de_sintese_carrega_o_que_a_mesa_disse():
    texto = agents.monta_pergunta_sintese("vale a pena?", [
        {"agente": "gestor", "nome": "Agente Gestor", "texto": "comprar"},
        {"agente": "macro", "nome": "Agente Macro", "texto": "juro caindo"},
        {"agente": "equity", "nome": "Vazio", "texto": "   "},
    ])
    assert "vale a pena?" in texto
    assert "--- Agente Gestor ---" in texto and "comprar" in texto
    assert "--- Agente Macro ---" in texto and "juro caindo" in texto
    # quem não respondeu não entra na conclusão
    assert "Vazio" not in texto


def test_conversa_trunca_historico_longo(mock_llm):
    servidor, _ = mock_llm
    hist = [{"role": "user", "content": f"m{i}"} for i in range(40)]
    agents.chat_conversa("openrouter", "sk-x", "m", "CTX", hist, "agora")
    corpo = servidor.recebido["/openai"]["body"]
    turnos = corpo["messages"][1:]
    assert len(turnos) == 13                     # 12 do histórico + a pergunta
    assert turnos[0]["content"] == "m28"


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


# ---------------------------------------------------------------------------
# ETFs e BDRs
# ---------------------------------------------------------------------------

def test_universo_bdr_sem_duplicatas_e_setores_validos():
    from finlab.backend import bdrs
    tickers = [b.ticker for b in bdrs.UNIVERSE]
    assert len(tickers) == len(set(tickers))
    for b in bdrs.UNIVERSE:
        assert b.sector in bdrs.SECTORS, b.ticker
        assert b.us_ticker, b.ticker


def test_bdr_peers_do_mesmo_setor():
    from finlab.backend import bdrs
    pares = bdrs.peers("AAPL34")
    assert pares and all(p.sector == "TECHNOLOGY" for p in pares)
    assert all(p.ticker != "AAPL34" for p in pares)


def test_bancos_de_bdr_marcados():
    from finlab.backend import bdrs
    assert bdrs.get("JPMC34").bank
    assert not bdrs.get("VISA34").bank      # rede de pagamento, balanço corporativo
    assert not bdrs.get("AAPL34").bank


def test_fundamentos_de_bdr_a_partir_de_modulos_mockados():
    """Payload no formato Yahoo/BRAPI vira a mesma estrutura dos fundamentos CVM."""
    from finlab.backend import bdrs

    def stmt(ano, campos):
        base = {"endDate": {"fmt": f"{ano}-09-30"}}
        base.update({k: {"raw": v} for k, v in campos.items()})
        return base

    mod = {
        "incomeStatementHistory": {"incomeStatementHistory": [
            stmt(2025, {"totalRevenue": 400e9, "grossProfit": 180e9,
                        "ebit": 120e9, "netIncome": 100e9}),
            stmt(2024, {"totalRevenue": 380e9, "grossProfit": 170e9,
                        "ebit": 114e9, "netIncome": 95e9}),
            stmt(2023, {"totalRevenue": 360e9, "grossProfit": 160e9,
                        "ebit": 108e9, "netIncome": 90e9}),
            stmt(2022, {"totalRevenue": 340e9, "grossProfit": 150e9,
                        "ebit": 102e9, "netIncome": 85e9}),
        ]},
        "balanceSheetHistory": {"balanceSheetStatements": [
            stmt(2025, {"totalStockholderEquity": 70e9, "totalAssets": 350e9,
                        "cash": 30e9, "shortTermInvestments": 30e9,
                        "shortLongTermDebt": 10e9, "longTermDebt": 90e9}),
            stmt(2024, {"totalStockholderEquity": 65e9, "totalAssets": 340e9,
                        "cash": 28e9, "shortTermInvestments": 30e9,
                        "shortLongTermDebt": 11e9, "longTermDebt": 95e9}),
        ]},
        "cashflowStatementHistory": {"cashflowStatements": [
            stmt(2025, {"totalCashFromOperatingActivities": 110e9,
                        "capitalExpenditures": -12e9, "depreciation": 11e9}),
            stmt(2024, {"totalCashFromOperatingActivities": 105e9,
                        "capitalExpenditures": -11e9, "depreciation": 10e9}),
        ]},
        "financialData": {"financialCurrency": "USD"},
    }

    bdr = bdrs.get("AAPL34")
    fund = bdrs.fundamentals_from_modules(bdr, mod)

    assert fund["currency"] == "USD"
    assert fund["years"] == [2022, 2023, 2024, 2025]
    assert fund["last_year"] == 2025
    base = fund["base"]
    assert base["receita"] == pytest.approx(400e9)
    assert base["ebitda"] == pytest.approx(120e9 + 11e9)
    assert base["divida_bruta"] == pytest.approx(100e9)
    assert base["divida_liquida"] == pytest.approx(100e9 - 60e9)
    assert base["fcl"] == pytest.approx(110e9 - 12e9)
    ind = fund["indicadores"]
    assert ind["roe"] == pytest.approx(100e9 / 70e9)
    assert ind["cagr_receita_3a"] == pytest.approx((400 / 340) ** (1 / 3) - 1, rel=1e-6)
    # dá para pontuar com esses indicadores
    sc = scoring.score(ind, fund["financial"])
    assert sc["total"] is not None and 0 <= sc["total"] <= 100


def test_fundamentos_de_bdr_sem_modulos_ficam_vazios_e_sinalizados():
    from finlab.backend import bdrs
    fund = bdrs.fundamentals_from_modules(bdrs.get("MSFT34"), None)
    assert fund["years"] == []
    assert fund["bdr"] is True
    prem = valuation.bdr_assumptions(fund, {"price": 80.0}, {}, None)
    assert prem["aplicavel"] is False
    assert "BRAPI" in prem["motivo_nao_aplicavel"]


def test_valuation_de_bdr_converte_upside_para_preco_por_bdr(monkeypatch):
    """shares sintético: equity/shares = preço_BDR × (1+upside)."""
    from finlab.backend import b3data, bdrs

    monkeypatch.setattr(b3data, "usdbrl", lambda: 5.0)

    fund = {"sector": "TECHNOLOGY", "financial": False, "bdr": True, "currency": "USD",
            "years": [2023, 2024, 2025],
            "base": {"divida_bruta": 100e9, "divida_liquida": 40e9, "caixa": 60e9},
            "indicadores": {"cagr_receita_3a": 0.06},
            "series": {"fcl": [90e9, 95e9, 100e9], "ebit": [110e9, 115e9, 120e9],
                       "ebitda": [120e9, 126e9, 133e9]}}
    quote = {"marketCap": 5.0 * 2000e9}   # US$ 2 tri em BRL
    prem = valuation.bdr_assumptions(fund, {"price": 80.0}, {}, quote)

    assert prem["aplicavel"] is True
    assert prem["mcap_usd"] == pytest.approx(2000e9)
    # identidade da conversão
    assert prem["shares"] == pytest.approx(2000e9 / 80.0)
    equity_hipotetico = 2400e9   # +20% sobre o mcap
    preco_justo = equity_hipotetico / prem["shares"]
    assert preco_justo == pytest.approx(80.0 * 1.20)
    assert prem["g_terminal"] < prem["wacc"]


def test_universo_etf_completo_e_categorizado(monkeypatch):
    from finlab.backend import b3data, etfs as met

    monkeypatch.setattr(b3data, "etf_listing", lambda: [
        {"ticker": "BOVA11", "nome": "ISHARES IBOVESPA FUNDO DE ÍNDICE",
         "categoria_b3": "ETF Renda Variável"},
        {"ticker": "XPTO11", "nome": "GESTORA MSCI GLOBAL FUNDO DE ÍNDICE",
         "categoria_b3": "ETF Renda Variável"},
        {"ticker": "BOL5", "nome": "PRODUTO ESTRANHO", "categoria_b3": ""},
    ])
    monkeypatch.setattr(b3data, "registry_for", lambda nome: {"pl": 1e9, "pl_data": "2026-07-01",
                                                              "situacao": "Em Funcionamento Normal",
                                                              "gestor": None, "administrador": None,
                                                              "inicio": None})
    uni = met.universe()
    tickers = {e["ticker"] for e in uni}
    assert "BOVA11" in tickers
    assert "XPTO11" in tickers
    assert "BOL5" not in tickers            # código fora do padrão XXXX11 sai
    assert "HASH11" in tickers              # cripto entra pela lista extra

    bova = next(e for e in uni if e["ticker"] == "BOVA11")
    assert bova["categoria"] == "INDICES_BR"
    assert bova["curado"] and bova["taxa_adm"] == 0.10
    xpto = next(e for e in uni if e["ticker"] == "XPTO11")
    assert xpto["categoria"] == "INTERNACIONAL"   # heurística de nome
    assert not xpto["curado"]
    hash11 = next(e for e in uni if e["ticker"] == "HASH11")
    assert hash11["categoria"] == "CRIPTO"


def test_faixas_de_liquidez():
    from finlab.backend import etfs as met
    assert met.liquidity_band(None) == "sem negócios"
    assert met.liquidity_band(200e6) == "muito alta"
    assert met.liquidity_band(20e6) == "alta"
    assert met.liquidity_band(2e6) == "média"
    assert met.liquidity_band(200e3) == "baixa"
    assert met.liquidity_band(5e3) == "muito baixa"


def test_toda_meta_curada_de_etf_aponta_categoria_valida():
    from finlab.backend import etfs as met
    for ticker, meta in met.ETF_META.items():
        assert meta["cat"] in met.CATEGORIES, ticker
        assert meta["tese"], ticker
        if meta["taxa_adm"] is not None:
            assert 0 < meta["taxa_adm"] < 3, ticker


# ---------------------------------------------------------------------------
# Fundamentos de BDR via Yahoo Finance
# ---------------------------------------------------------------------------

def _yahoo_raw_exemplo():
    def anos(vals):
        return {2022 + i: v for i, v in enumerate(vals)}
    return {
        "income": {
            "receita": anos([340e9, 360e9, 380e9, 400e9]),
            "lucro_bruto": anos([150e9, 160e9, 170e9, 180e9]),
            "ebit": anos([102e9, 108e9, 114e9, 120e9]),
            "ebitda": anos([113e9, 119e9, 125e9, 131e9]),
            "lucro_liquido": anos([85e9, 90e9, 95e9, 100e9]),
        },
        "balance": {
            "patrimonio_liquido": anos([60e9, 62e9, 65e9, 70e9]),
            "ativo_total": anos([330e9, 335e9, 340e9, 350e9]),
            "caixa_total": anos([55e9, 58e9, 58e9, 60e9]),
            "divida_bruta": anos([105e9, 104e9, 106e9, 100e9]),
        },
        "cashflow": {
            "fco": anos([95e9, 100e9, 105e9, 110e9]),
            "capex": anos([-10e9, -10e9, -11e9, -12e9]),
            "depreciacao": anos([10e9, 10e9, 10e9, 11e9]),
        },
        "info": {"marketCap": 3.0e12, "beta": 1.2, "dividendYield": 0.44,
                 "currentPrice": 210.0, "targetMeanPrice": 250.0,
                 "targetHighPrice": 300.0, "targetLowPrice": 180.0,
                 "numberOfAnalystOpinions": 40, "recommendationKey": "buy",
                 "financialCurrency": "USD"},
    }


def test_fundamentos_de_bdr_via_yahoo():
    from finlab.backend import bdrs
    fund = bdrs.fundamentals_from_yahoo(bdrs.get("AAPL34"), _yahoo_raw_exemplo())
    assert fund["fonte"] == "Yahoo Finance"
    assert fund["years"] == [2022, 2023, 2024, 2025]
    base = fund["base"]
    assert base["receita"] == pytest.approx(400e9)
    assert base["ebitda"] == pytest.approx(131e9)          # linha EBITDA direto
    assert base["divida_liquida"] == pytest.approx(40e9)   # 100 − 60 (caixa consolidado)
    assert base["fcl"] == pytest.approx(98e9)
    sc = scoring.score(fund["indicadores"], fund["financial"])
    assert sc["total"] is not None


def test_yahoo_ebitda_derivado_quando_linha_falta():
    from finlab.backend import bdrs
    raw = _yahoo_raw_exemplo()
    del raw["income"]["ebitda"]
    fund = bdrs.fundamentals_from_yahoo(bdrs.get("AAPL34"), raw)
    # EBIT 120 + D&A 11
    assert fund["base"]["ebitda"] == pytest.approx(131e9)


def test_yahoo_banco_nao_ganha_ebitda_nem_divida_liquida():
    from finlab.backend import bdrs
    fund = bdrs.fundamentals_from_yahoo(bdrs.get("JPMC34"), _yahoo_raw_exemplo())
    assert fund["financial"] is True
    assert all(v is None for v in fund["series"]["ebitda"])
    assert fund["indicadores"]["nd_ebitda"] is None


def test_yahoo_dy_heuristica_de_escala():
    from finlab.backend import bdrs
    assert bdrs.yahoo_dividend_yield({"dividendYield": 0.0044}) == pytest.approx(0.0044)
    assert bdrs.yahoo_dividend_yield({"dividendYield": 0.44}) == pytest.approx(0.0044)
    assert bdrs.yahoo_dividend_yield({"dividendYield": None}) is None
    assert bdrs.yahoo_dividend_yield({}) is None


def test_orquestrador_prefere_yahoo_e_cai_para_brapi(monkeypatch):
    from finlab.backend import bdrs
    monkeypatch.setattr(bdrs, "yahoo_raw", lambda b: _yahoo_raw_exemplo())
    bundle = bdrs.fetch_fundamentals("AAPL34")
    assert bundle["fonte"] == "Yahoo Finance"
    assert bundle["info"]["marketCap"] == pytest.approx(3.0e12)

    monkeypatch.setattr(bdrs, "yahoo_raw", lambda b: None)
    monkeypatch.setattr(bdrs, "raw_modules", lambda t: None)
    bundle = bdrs.fetch_fundamentals("AAPL34")
    assert bundle["fonte"] is None
    assert bundle["fund"]["years"] == []


def test_bdr_assumptions_usa_mcap_do_yahoo_direto(monkeypatch):
    from finlab.backend import b3data, bdrs
    monkeypatch.setattr(b3data, "usdbrl", lambda: 5.0)
    fund = bdrs.fundamentals_from_yahoo(bdrs.get("AAPL34"), _yahoo_raw_exemplo())
    prem = valuation.bdr_assumptions(fund, {"price": 87.15}, {}, None,
                                     yahoo_info=_yahoo_raw_exemplo()["info"])
    assert prem["mcap_usd"] == pytest.approx(3.0e12)
    assert prem["mcap_fonte"] == "Yahoo Finance"
    assert prem["beta"] == pytest.approx(1.2)
    assert prem["beta_source"] == "Yahoo Finance"
    assert prem["aplicavel"] is True
    # identidade: equity == mcap → preço justo == preço do BDR
    assert 3.0e12 / prem["shares"] == pytest.approx(87.15)


def test_consenso_de_bdr_convertido_para_reais_por_bdr():
    from finlab.backend.app import _consenso_bdr
    cons = _consenso_bdr(_yahoo_raw_exemplo()["info"], 87.15)
    # alvo médio 250 sobre preço atual 210 → mesmo upside aplicado ao BDR
    assert cons["alvo_medio"] == pytest.approx(round(250 / 210 * 87.15, 2))
    assert cons["alvo_alto"] == pytest.approx(round(300 / 210 * 87.15, 2))
    assert cons["analistas"] == 40
    assert "Yahoo" in cons["fonte"]
    assert _consenso_bdr({}, 87.15) == {}
    assert _consenso_bdr(_yahoo_raw_exemplo()["info"], None) == {}


def test_df_to_plain_converte_dataframe_do_yfinance():
    import pandas as pd
    from finlab.backend import bdrs
    df = pd.DataFrame(
        {pd.Timestamp("2025-09-30"): [400e9, 100e9],
         pd.Timestamp("2024-09-30"): [380e9, float("nan")]},
        index=["Total Revenue", "Net Income"],
    )
    out = bdrs._df_to_plain(df, bdrs._Y_INCOME)
    assert out["receita"] == {2025: 400e9, 2024: 380e9}
    assert out["lucro_liquido"] == {2025: 100e9}   # NaN descartado
    assert bdrs._df_to_plain(None, bdrs._Y_INCOME) == {}


# ---------------------------------------------------------------------------
# Contexto dos agentes por tipo de ativo
# ---------------------------------------------------------------------------

def _payload_min(**over):
    fund = {"name": "X", "ticker": "XPTO3", "sector": "VAREJO", "financial": False,
            "last_year": 2025, "base": {"receita": 400e9}, "indicadores": {},
            "series": {}, "years": []}
    fund.update(over)
    return {"fundamentals": fund, "market": {"perf": {}}, "multiples": {}, "score": {}}


def test_contexto_de_acao_br_cita_cvm_e_reais():
    texto = agents.build_context(_payload_min(), {}, {}, {})
    assert "DFP" in texto and "CVM" in texto
    assert "R$ 400,00 bi" in texto
    assert "BDR" not in texto


def test_contexto_de_bdr_declara_origem_moeda_e_cambio():
    texto = agents.build_context(
        _payload_min(ticker="AAPL34", name="Apple", bdr=True, us_ticker="AAPL",
                     currency="USD", fonte="Yahoo Finance"), {}, {}, {})
    assert "BDR" in texto
    assert "Yahoo Finance" in texto
    assert "AAPL" in texto
    # grandezas contábeis na moeda de reporte
    assert "US$ 400,00 bi" in texto
    # e o aviso de que preço está em reais
    assert "REAIS por BDR" in texto
    assert "CVM" not in texto


def test_contexto_respeita_moeda_diferente_de_dolar():
    texto = agents.build_context(
        _payload_min(bdr=True, currency="EUR", us_ticker="ASML"), {}, {}, {})
    assert "EUR 400,00 bi" in texto


def test_prompt_do_macro_cobre_acao_br_e_bdr():
    sistema = agents.AGENTS["macro"]["system"]
    assert "BDR" in sistema
    assert "Tesouro americano" in sistema
    assert "Selic" in sistema


def test_regras_comuns_nao_prometem_cvm_para_todo_ativo():
    for agente in agents.AGENTS.values():
        assert "ORIGEM DOS DADOS" in agente["system"]
