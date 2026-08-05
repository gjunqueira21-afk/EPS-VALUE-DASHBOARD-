"""Leitura dos demonstrativos da CVM já processados pelo pipeline existente.

Fonte: valuation_cvm/data/processed/*.parquet (DFP consolidado, plano de
contas padronizado da CVM). Este módulo transforma as linhas contábeis em
séries anuais por empresa — a base fundamentalista do painel, que funciona
mesmo sem internet.

Convenções:
  * Valores em R$ nominais (coluna VL_CONTA_AJUSTADO já vem convertida).
  * Códigos CD_CONTA têm prioridade sobre descrição textual: a CVM
    padroniza os níveis 1–3, então o código é muito mais confiável.
  * Nada é inventado: conta ausente vira None e o front-end mostra "—".
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Optional

import pandas as pd

from .settings import CVM_PROCESSED_DIR

STATEMENTS = ("dre", "bpa", "bpp", "dfc_mi")
MAX_YEARS = 10
MAX_TRIMESTRES = 12

# As mesmas contas servem o anual e o trimestral de propósito: o 4T sai da
# diferença entre o exercício fechado (DFP) e o acumulado até o 3T (ITR), e
# subtrair linhas diferentes daria um número plausível e errado.
CONTA_RECEITA = (["3.01"], ["RECEITA DE VENDA", "RECEITA LIQUIDA",
                            "RECEITAS DA INTERMEDIACAO", "RECEITA OPERACIONAL"])
CONTA_LUCRO = (["3.11", "3.09"], ["LUCRO/PREJUIZO CONSOLIDADO DO PERIODO",
                                  "LUCRO/PREJUIZO DO PERIODO", "LUCRO LIQUIDO"])


# ---------------------------------------------------------------------------
# Carregamento
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _frames(tipo: str = "dfp") -> dict[str, pd.DataFrame]:
    """Carrega os quatro demonstrativos uma única vez por processo.

    `tipo` é o sufixo do pipeline: "dfp" (anual) ou "itr" (trimestral). O
    sufixo era fixo em _dfp — o achado 00.3 do diagnóstico: o pipeline em
    valuation_cvm já baixa e processa o ITR, e o painel simplesmente não lia.
    """
    out: dict[str, pd.DataFrame] = {}
    for st in STATEMENTS:
        fp = CVM_PROCESSED_DIR / f"{st}_{tipo}.parquet"
        if not fp.exists():
            out[st] = pd.DataFrame()
            continue
        df = pd.read_parquet(fp)
        df["CD_CVM"] = df["CD_CVM"].astype(str).str.strip()
        df["CD_CONTA"] = df["CD_CONTA"].astype(str).str.strip()
        df["DS_NORM"] = df["DS_CONTA"].map(_norm)
        out[st] = df
    return out


@lru_cache(maxsize=1)
def _shares_table() -> pd.DataFrame:
    """Quantidade de ações por CNPJ, a partir do capital social da CVM."""
    fp = CVM_PROCESSED_DIR / "capital_social.csv"
    if not fp.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(fp, sep=";", dtype=str, encoding="utf-8", on_bad_lines="skip")
    except UnicodeDecodeError:  # arquivos da CVM costumam vir em latin1
        df = pd.read_csv(fp, sep=";", dtype=str, encoding="latin1", on_bad_lines="skip")
    if "Tipo_Capital" not in df.columns:
        return pd.DataFrame()
    df = df[df["Tipo_Capital"].str.contains("Integralizado", na=False)].copy()
    for col in ("Quantidade_Acoes_Ordinarias", "Quantidade_Acoes_Preferenciais",
                "Quantidade_Total_Acoes"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["TOTAL"] = df["Quantidade_Total_Acoes"].fillna(
        df["Quantidade_Acoes_Ordinarias"].fillna(0) + df["Quantidade_Acoes_Preferenciais"].fillna(0)
    )
    df["CNPJ_DIG"] = df["CNPJ_Companhia"].str.replace(r"\D", "", regex=True)
    df = df[df["TOTAL"] > 0]
    return df.sort_values("Data_Referencia").groupby("CNPJ_DIG").agg(
        shares=("TOTAL", "last"), data=("Data_Referencia", "last")
    ).reset_index()


def _norm(s: object) -> str:
    txt = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", txt).strip().upper()


def available() -> bool:
    return any(not df.empty for df in _frames().values())


def quarterly_available() -> bool:
    """True quando o pipeline já gerou os parquets do ITR."""
    return any(not df.empty for df in _frames("itr").values())


def latest_quarter(cd_cvm: str) -> Optional[dict]:
    """O trimestre mais recente publicado no ITR para a empresa.

    Devolve {"fim": "AAAA-MM-DD", "receita": float|None, "lucro": float|None},
    com os valores ACUMULADOS no exercício até aquela data — é assim que a
    CVM publica a DRE do ITR. Sem ITR processado, devolve None e o painel
    segue anual, como sempre foi.
    """
    dre = _company("dre", cd_cvm, "itr")
    if dre.empty or "DT_FIM_EXERC" not in dre.columns:
        return None
    dre = dre.dropna(subset=["DT_FIM_EXERC"])
    if dre.empty:
        return None
    # Quando o parquet distingue o período (DT_INI_EXERC), fica só o
    # acumulado-padrão do ano — descarta janelas trimestrais avulsas.
    if "DT_INI_EXERC" in dre.columns:
        ini = pd.to_datetime(dre["DT_INI_EXERC"], errors="coerce")
        comeco_de_ano = (ini.dt.month == 1) & (ini.dt.day == 1)
        if comeco_de_ano.any():
            dre = dre[comeco_de_ano]
    fim = dre["DT_FIM_EXERC"].max()
    tri = dre[dre["DT_FIM_EXERC"] == fim]

    def valor(codes, keywords):
        serie = _series(tri, codes=codes, keywords=keywords)
        vals = list(serie.values())
        return float(vals[0]) if vals else None

    return {
        "fim": str(pd.Timestamp(fim).date()),
        "receita": valor(*CONTA_RECEITA),
        "lucro": valor(*CONTA_LUCRO),
    }


# ---------------------------------------------------------------------------
# Série trimestral (ITR)
# ---------------------------------------------------------------------------
#
# A DRE do ITR vem ACUMULADA no exercício: o 2T chega como jan–jun, o 3T como
# jan–set. Plotar o acumulado como se fosse trimestre isolado desenha uma
# receita que só cresce ao longo do ano — número errado com cara de certo.
# Aqui o acumulado é desfeito por diferença, e o 4T (que o ITR não publica)
# sai do exercício fechado da DFP menos o acumulado até o 3T.

def _distancia_meses(a: pd.Timestamp, b: pd.Timestamp) -> int:
    """Meses entre duas datas."""
    return (b.year - a.year) * 12 + (b.month - a.month)


def _meses(ini: pd.Timestamp, fim: pd.Timestamp) -> int:
    """Meses cobertos por uma janela [ini, fim], contando as duas pontas."""
    return _distancia_meses(ini, fim) + 1


def _indice_do_trimestre(ini: pd.Timestamp, fim: pd.Timestamp) -> int:
    """1..4 a partir do início do exercício — vale para ano fiscal não-civil."""
    return max(1, min(4, round(_meses(ini, fim) / 3)))


def _acumulado_do_exercicio(dre: pd.DataFrame) -> pd.DataFrame:
    """Mantém só as linhas acumuladas desde a abertura do exercício.

    O CSV do ITR traz, para a mesma data-fim, tanto o acumulado quanto janelas
    avulsas (o trimestre isolado). A acumulada é a de início mais antigo — o
    que também funciona para empresas de exercício fiscal não-civil, ao
    contrário de procurar literalmente 1º de janeiro.
    """
    if "DT_INI_EXERC" not in dre.columns:
        return dre
    dre = dre.dropna(subset=["DT_FIM_EXERC", "DT_INI_EXERC"]).copy()
    if dre.empty:
        return dre
    # Exercícios comparativos ("PENÚLTIMO") repetem períodos antigos com valores
    # possivelmente reapresentados; o corrente basta.
    if "ORDEM_EXERC" in dre.columns:
        corrente = dre["ORDEM_EXERC"].map(_norm).str.startswith("ULTIMO")
        if corrente.any():
            dre = dre[corrente]
    abertura = dre.groupby("DT_FIM_EXERC")["DT_INI_EXERC"].transform("min")
    return dre[dre["DT_INI_EXERC"] == abertura]


def _desacumula(acc: dict, abertura: dict, anual: dict) -> dict:
    """{data-fim: acumulado} → {data-fim: trimestre isolado}.

    `abertura` diz em que data cada exercício começou (é o que agrupa os
    trimestres do mesmo ano fiscal). `anual` é a série da DFP, usada só para
    fechar o 4T.
    """
    por_exercicio: dict = {}
    for fim in sorted(acc):
        por_exercicio.setdefault(abertura.get(fim), []).append(fim)

    out: dict = {}
    for ini, datas in por_exercicio.items():
        if ini is None:
            continue
        anterior = 0.0
        for fim in datas:
            out[fim] = acc[fim] - anterior
            anterior = acc[fim]
        # 4T: o ITR não publica. Só dá para derivar quando o último acumulado
        # é mesmo o 3T — senão a diferença junta vários trimestres num só.
        ultimo = datas[-1]
        if _indice_do_trimestre(ini, ultimo) != 3:
            continue
        fecha = ini + pd.DateOffset(years=1) - pd.Timedelta(days=1)
        if fecha.year in anual and fecha not in out:
            out[fecha] = anual[fecha.year] - acc[ultimo]
    return out


def _ltm(isolado: dict) -> dict:
    """Soma móvel de 4 trimestres, só onde os quatro são consecutivos."""
    datas = sorted(isolado)
    out: dict = {}
    for i in range(3, len(datas)):
        janela = datas[i - 3:i + 1]
        # Quatro trimestres seguidos deixam ~9 meses entre a primeira e a
        # última data-fim; buraco na série não pode virar LTM silencioso.
        if not 8 <= _distancia_meses(janela[0], janela[-1]) <= 10:
            continue
        out[datas[i]] = sum(isolado[d] for d in janela)
    return out


def quarterly_series(cd_cvm: str, max_tri: int = MAX_TRIMESTRES) -> dict:
    """Trimestres isolados e LTM por empresa, prontos para o painel.

    Devolve {"pontos": [...], "campos": [...]}; lista vazia quando o pipeline
    ainda não gerou os parquets do ITR — e aí o painel segue anual.
    """
    vazio: dict = {"pontos": [], "campos": []}
    if not cd_cvm:
        return vazio

    dre = _company("dre", cd_cvm, "itr")
    if dre.empty or "DT_FIM_EXERC" not in dre.columns:
        return vazio
    dre = _acumulado_do_exercicio(dre)
    if dre.empty:
        return vazio

    abertura = (dre.drop_duplicates("DT_FIM_EXERC")
                   .set_index("DT_FIM_EXERC")["DT_INI_EXERC"].to_dict()
                if "DT_INI_EXERC" in dre.columns else {})
    if not abertura:
        return vazio

    campos = {"receita": CONTA_RECEITA, "lucro_liquido": CONTA_LUCRO}
    acumulado = {nome: _series(dre, cod, kw, chave="DT_FIM_EXERC")
                 for nome, (cod, kw) in campos.items()}
    if not any(acumulado.values()):
        return vazio

    dre_anual = _company("dre", cd_cvm)
    anual = ({nome: _series(dre_anual, cod, kw) for nome, (cod, kw) in campos.items()}
             if not dre_anual.empty else {})

    isolado = {nome: _desacumula(serie, abertura, anual.get(nome, {}))
               for nome, serie in acumulado.items()}
    ltm = {nome: _ltm(serie) for nome, serie in isolado.items()}

    datas = sorted(set().union(*[set(s) for s in isolado.values()]))[-max_tri:]
    pontos = []
    for fim in datas:
        ini = abertura.get(fim)
        # O 4T é derivado: não tem linha própria no ITR, logo não tem abertura.
        derivado = ini is None
        if derivado:
            ini = pd.Timestamp(fim) - pd.DateOffset(years=1) + pd.Timedelta(days=1)
        tri = _indice_do_trimestre(pd.Timestamp(ini), pd.Timestamp(fim))
        ponto = {
            "fim": str(pd.Timestamp(fim).date()),
            "rotulo": f"{tri}T{str(pd.Timestamp(fim).year)[-2:]}",
            "derivado": derivado,
        }
        for nome in campos:
            ponto[nome] = isolado[nome].get(fim)
            ponto[nome + "_ltm"] = ltm[nome].get(fim)
        pontos.append(ponto)

    return {"pontos": pontos, "campos": list(campos)}


# ---------------------------------------------------------------------------
# Extração de contas
# ---------------------------------------------------------------------------

def _company(st: str, cd_cvm: str, tipo: str = "dfp") -> pd.DataFrame:
    df = _frames(tipo).get(st)
    if df is None or df.empty:
        return pd.DataFrame()
    return df[df["CD_CVM"] == str(cd_cvm).strip()]


def _series(
    sub: pd.DataFrame,
    codes: Optional[list[str]] = None,
    keywords: Optional[list[str]] = None,
    contains_all: bool = False,
    chave: str = "ANO_REFER",
) -> dict:
    """Série {período: valor} de uma conta.

    Tenta CD_CONTA exato na ordem informada; só cai para busca textual se
    nenhum código bater. Dentro de um período, prefere a conta de menor nível
    hierárquico (mais agregada).

    `chave` é a coluna que define o período: ANO_REFER no anual (um ponto por
    exercício) ou DT_FIM_EXERC no trimestral — lá o ano tem quatro pontos, e
    chavear por ano colapsaria os quatro em um.
    """
    if sub.empty:
        return {}

    for code in codes or []:
        hit = sub[sub["CD_CONTA"] == code]
        if not hit.empty:
            return _collapse(hit, chave)

    if keywords:
        keys = [_norm(k) for k in keywords]
        ds = sub["DS_NORM"]
        if contains_all:
            mask = pd.Series(True, index=sub.index)
            for k in keys:
                mask &= ds.str.contains(k, regex=False, na=False)
        else:
            mask = pd.Series(False, index=sub.index)
            for k in keys:
                mask |= ds.str.contains(k, regex=False, na=False)
        hit = sub[mask]
        if not hit.empty:
            return _collapse(hit, chave)
    return {}


def _collapse(hit: pd.DataFrame, chave: str = "ANO_REFER") -> dict:
    """Um valor por período: conta mais agregada; empate pelo maior |valor|."""
    tmp = hit.assign(
        _lvl=hit["CD_CONTA"].str.count(r"\."),
        _abs=hit["VL_CONTA_AJUSTADO"].abs(),
    ).sort_values([chave, "_lvl", "_abs"], ascending=[True, True, False])
    tmp = tmp.dropna(subset=["VL_CONTA_AJUSTADO"]).drop_duplicates(chave, keep="first")
    if chave == "ANO_REFER":
        return {int(getattr(r, chave)): float(r.VL_CONTA_AJUSTADO) for r in tmp.itertuples()}
    return {pd.Timestamp(getattr(r, chave)): float(r.VL_CONTA_AJUSTADO)
            for r in tmp.itertuples()}


def _sum_series(*series: dict[int, float]) -> dict[int, float]:
    """Soma séries ano a ano; um ano existe no resultado se existir em alguma."""
    years: set[int] = set()
    for s in series:
        years |= set(s)
    return {y: sum(s.get(y, 0.0) for s in series) for y in sorted(years)}


# ---------------------------------------------------------------------------
# Perfil contábil
# ---------------------------------------------------------------------------

def is_financial_statement(cd_cvm: str) -> bool:
    """Detecta plano de contas de instituição financeira/seguradora.

    Bancos usam 2.08 para Patrimônio Líquido e não possuem 3.01 "Receita de
    Venda de Bens"; a descrição da 3.01 traz "Intermediação Financeira" ou
    "Receitas da Intermediação".
    """
    dre = _company("dre", cd_cvm)
    if dre.empty:
        return False
    top = dre[dre["CD_CONTA"] == "3.01"]["DS_NORM"]
    if top.str.contains("INTERMEDIACAO", na=False).any():
        return True
    if top.str.contains("PREMIOS|SEGUROS|RESSEGURO", regex=True, na=False).any():
        return True
    bpp = _company("bpp", cd_cvm)
    if not bpp.empty:
        pl_codes = set(bpp[bpp["DS_NORM"].str.contains("PATRIMONIO LIQUIDO", na=False)]["CD_CONTA"])
        if "2.08" in pl_codes and "2.03" not in pl_codes:
            return True
    return False


# ---------------------------------------------------------------------------
# Séries anuais consolidadas
# ---------------------------------------------------------------------------

def annual_series(cd_cvm: str, max_years: int = MAX_YEARS) -> dict:
    """Séries anuais por empresa, prontas para o painel.

    Devolve {"years": [...], "financial": bool, "series": {campo: [valores]}}
    com None onde a conta não existe.
    """
    if not cd_cvm:
        return {"years": [], "financial": False, "series": {}, "cnpj": None}

    dre = _company("dre", cd_cvm)
    bpa = _company("bpa", cd_cvm)
    bpp = _company("bpp", cd_cvm)
    dfc = _company("dfc_mi", cd_cvm)
    if dre.empty and bpa.empty:
        return {"years": [], "financial": False, "series": {}, "cnpj": None}

    fin = is_financial_statement(cd_cvm)

    # --- DRE -------------------------------------------------------------
    receita = _series(dre, *CONTA_RECEITA)
    lucro_bruto = _series(dre, ["3.03"], ["RESULTADO BRUTO", "LUCRO BRUTO"])
    ebit = _series(dre, ["3.05"], ["RESULTADO ANTES DO RESULTADO FINANCEIRO",
                                   "RESULTADO OPERACIONAL"])
    res_fin = _series(dre, ["3.06"], ["RESULTADO FINANCEIRO"])
    lucro_liq = _series(dre, *CONTA_LUCRO)
    # Operações descontinuadas: quando vem diferente de zero, a companhia
    # segregou uma operação que está saindo — o sinal mais verificável de
    # reestruturação de portfólio.
    #
    # Casada SÓ por descrição, de propósito. O código muda de plano de contas:
    # é 3.10 na indústria e 3.12 em seguradora, e confiar no número faz o
    # leitor pegar, na BB Seguridade, uma conta que vale bilhões e não tem
    # nada a ver com desinvestimento. A descrição é padronizada pela CVM nos
    # dois planos; o código, não.
    descont = _series(dre, None, ["OPERACOES DESCONTINUADAS"])

    # --- Balanço ---------------------------------------------------------
    ativo = _series(bpa, ["1"], ["ATIVO TOTAL"])
    imobilizado = _series(bpa, ["1.02.03"], ["IMOBILIZADO"])
    intangivel = _series(bpa, ["1.02.04"], ["INTANGIVEL"])
    caixa = _series(bpa, ["1.01.01"], ["CAIXA E EQUIVALENTES"])
    aplic = _series(bpa, ["1.01.02"], ["APLICACOES FINANCEIRAS", "TITULOS E VALORES MOBILIARIOS"])
    passivo = _series(bpp, ["2"], ["PASSIVO TOTAL"])
    # PL: bancos usam 2.08, não-financeiras 2.03 — casar por descrição cobre ambos.
    pl = _series(bpp, None, ["PATRIMONIO LIQUIDO CONSOLIDADO", "PATRIMONIO LIQUIDO"])
    div_cp = _series(bpp, ["2.01.04"], None)
    div_lp = _series(bpp, ["2.02.01"], None)
    divida_bruta = _sum_series(div_cp, div_lp) if (div_cp or div_lp) else {}

    # --- Fluxo de caixa --------------------------------------------------
    fco = _series(dfc, ["6.01"], ["CAIXA LIQUIDO ATIVIDADES OPERACIONAIS"])
    capex = _capex(dfc)
    deprec = _depreciation(dfc)

    # --- Derivadas -------------------------------------------------------
    caixa_total = _sum_series(caixa, aplic) if (caixa or aplic) else {}
    divida_liq = ({y: divida_bruta.get(y, 0.0) - caixa_total.get(y, 0.0)
                   for y in divida_bruta} if divida_bruta and not fin else {})
    ebitda = ({y: ebit[y] + abs(deprec.get(y, 0.0)) for y in ebit if y in deprec}
              if (ebit and deprec and not fin) else {})
    fcl = {y: fco[y] - abs(capex.get(y, 0.0)) for y in fco if y in capex} if (fco and capex) else {}

    fields = {
        "receita": receita,
        "lucro_bruto": lucro_bruto,
        "ebit": ebit,
        "ebitda": ebitda,
        "depreciacao": {y: abs(v) for y, v in deprec.items()},
        "resultado_financeiro": res_fin,
        "lucro_liquido": lucro_liq,
        "descontinuadas": descont,
        "ativo_total": ativo,
        "imobilizado": imobilizado,
        "intangivel": intangivel,
        "passivo_total": passivo,
        "patrimonio_liquido": pl,
        "caixa": caixa,
        "aplicacoes": aplic,
        "caixa_total": caixa_total,
        "divida_bruta": divida_bruta,
        "divida_liquida": divida_liq,
        "fco": fco,
        "capex": {y: -abs(v) for y, v in capex.items()},
        "fcl": fcl,
    }

    all_years = sorted({y for s in fields.values() for y in s})
    years = all_years[-max_years:]
    series = {k: [v.get(y) for y in years] for k, v in fields.items()}

    cnpj = None
    for frame in (dre, bpa, bpp):
        if not frame.empty:
            cnpj = str(frame["CNPJ_CIA"].iloc[-1])
            break

    return {
        "years": years,
        "financial": fin,
        "series": series,
        "cnpj": cnpj,
        "denom": str(dre["DENOM_CIA"].iloc[-1]) if not dre.empty else None,
        "last_year": years[-1] if years else None,
    }


_DA_RE = r"DEPRECIA|AMORTIZ|EXAUST"
_DA_EXCLUDE = r"DESPESAS ANTECIPADAS|AGIO|MAIS-VALIA|DIREITO DE USO CONTRAPRESTA"


def _depreciation(dfc: pd.DataFrame) -> dict[int, float]:
    """Depreciação, amortização e exaustão a partir do DFC.

    A CVM não padroniza código para D&A: a linha vive em 6.01.01.xx com
    descrição livre. Estratégia, por ano:
      1. linha que cite depreciação E amortização (a consolidada típica);
      2. senão, a de maior valor absoluto que cite qualquer um dos termos.
    Descrições que claramente não são D&A do imobilizado são descartadas.
    """
    if dfc.empty:
        return {}
    base = dfc[dfc["CD_CONTA"].str.startswith("6.01.01")]
    if base.empty:
        base = dfc[dfc["CD_CONTA"].str.startswith("6.01")]
    hit = base[
        base["DS_NORM"].str.contains(_DA_RE, regex=True, na=False)
        & ~base["DS_NORM"].str.contains(_DA_EXCLUDE, regex=True, na=False)
    ].dropna(subset=["VL_CONTA_AJUSTADO"])
    if hit.empty:
        return {}
    hit = hit.assign(
        _both=(hit["DS_NORM"].str.contains("DEPRECIA", na=False)
               & hit["DS_NORM"].str.contains("AMORTIZ", na=False)).astype(int),
        _abs=hit["VL_CONTA_AJUSTADO"].abs(),
    ).sort_values(["ANO_REFER", "_both", "_abs"], ascending=[True, False, False])
    hit = hit.drop_duplicates("ANO_REFER", keep="first")
    return {int(r.ANO_REFER): float(r.VL_CONTA_AJUSTADO) for r in hit.itertuples()}


_CAPEX_RE = (r"IMOBILIZAD|INTANGIVE|ATIVO FIXO|ATIVOS FIXOS|PROPRIEDADE PARA INVESTIMENTO"
             r"|PROPRIEDADES PARA INVESTIMENTO|ATIVO NAO CIRCULANTE|ATIVO PERMANENTE")
_CAPEX_EXCLUDE = (r"VENDA|ALIENACAO|RECEBIMENTO|BAIXA|RESGATE|REDUCAO|RECURSOS PROVENIENTES"
                  r"|DESIMOBILIZ|CAIXA LIQUIDO")


def _capex(dfc: pd.DataFrame) -> dict[int, float]:
    """CAPEX (investimento em imobilizado + intangível), como valor negativo.

    O código 6.02.01 NÃO é padronizado pela CVM — em várias empresas ele é
    "Aumento em Títulos e Valores Mobiliários" ou só parte do imobilizado.
    Por isso somamos todas as linhas de aquisição de imobilizado/intangível
    dentro das atividades de investimento (6.02.xx), excluindo alienações.
    """
    if dfc.empty:
        return {}
    sub = dfc[dfc["CD_CONTA"].str.startswith("6.02.")]
    if sub.empty:
        return {}
    hit = sub[
        sub["DS_NORM"].str.contains(_CAPEX_RE, regex=True, na=False)
        & ~sub["DS_NORM"].str.contains(_CAPEX_EXCLUDE, regex=True, na=False)
    ].dropna(subset=["VL_CONTA_AJUSTADO"])
    if hit.empty:
        return {}
    out: dict[int, float] = {}
    for year, grp in hit.groupby("ANO_REFER"):
        # Evita dupla contagem quando a empresa detalha a conta em sub-níveis:
        # fica só com o nível hierárquico mais agregado presente no ano.
        lvl = grp["CD_CONTA"].str.count(r"\.")
        grp = grp[lvl == lvl.min()]
        neg = grp[grp["VL_CONTA_AJUSTADO"] < 0]["VL_CONTA_AJUSTADO"].sum()
        total = neg if neg < 0 else -grp["VL_CONTA_AJUSTADO"].abs().sum()
        if total != 0:
            out[int(year)] = float(total)
    return out


def shares_outstanding(cnpj: Optional[str]) -> Optional[float]:
    """Total de ações integralizadas (capital social da CVM)."""
    if not cnpj:
        return None
    tbl = _shares_table()
    if tbl.empty:
        return None
    digits = re.sub(r"\D", "", str(cnpj))
    hit = tbl[tbl["CNPJ_DIG"] == digits]
    if hit.empty:
        return None
    return float(hit.iloc[0]["shares"])


def shares_from_eps(cd_cvm: Optional[str]) -> Optional[float]:
    """Ações implícitas no lucro por ação publicado (conta 3.99 da DRE).

    Fallback para as empresas ausentes do arquivo de capital social:
    se a companhia informa LPA básico, o número de ações sai de
    lucro líquido ÷ LPA. É a média ponderada do exercício, o que basta
    para múltiplos de mercado.
    """
    if not cd_cvm:
        return None
    dre = _company("dre", cd_cvm)
    if dre.empty:
        return None

    lpa = _series(dre, ["3.99.01.01"], None)
    if not lpa:
        lpa = _series(dre, ["3.99.01.02"], None)
    lucro = _series(dre, ["3.11", "3.09"], ["LUCRO/PREJUIZO CONSOLIDADO DO PERIODO",
                                            "LUCRO/PREJUIZO DO PERIODO", "LUCRO LIQUIDO"])
    if not lpa or not lucro:
        return None

    for year in sorted(set(lpa) & set(lucro), reverse=True):
        eps, li = lpa[year], lucro[year]
        if not eps or not li or abs(eps) < 1e-9:
            continue
        shares = li / eps
        if shares <= 0:
            continue
        # A CVM publica o LPA já em R$/ação, mas o pipeline aplica a escala
        # do balanço (milhares) a todas as linhas — inflando a conta 3.99 em
        # 1.000×. Uma companhia aberta com menos de 5 milhões de ações é
        # implausível, então essa é a assinatura do erro de escala.
        if shares < 5e6:
            shares *= 1000.0
        if shares < 1e6:
            continue
        return float(shares)
    return None
