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


# ---------------------------------------------------------------------------
# Carregamento
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _frames() -> dict[str, pd.DataFrame]:
    """Carrega os quatro demonstrativos uma única vez por processo."""
    out: dict[str, pd.DataFrame] = {}
    for st in STATEMENTS:
        fp = CVM_PROCESSED_DIR / f"{st}_dfp.parquet"
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


# ---------------------------------------------------------------------------
# Extração de contas
# ---------------------------------------------------------------------------

def _company(st: str, cd_cvm: str) -> pd.DataFrame:
    df = _frames().get(st)
    if df is None or df.empty:
        return pd.DataFrame()
    return df[df["CD_CVM"] == str(cd_cvm).strip()]


def _series(
    sub: pd.DataFrame,
    codes: Optional[list[str]] = None,
    keywords: Optional[list[str]] = None,
    contains_all: bool = False,
) -> dict[int, float]:
    """Série {ano: valor} de uma conta.

    Tenta CD_CONTA exato na ordem informada; só cai para busca textual se
    nenhum código bater. Dentro de um ano, prefere a conta de menor nível
    hierárquico (mais agregada).
    """
    if sub.empty:
        return {}

    for code in codes or []:
        hit = sub[sub["CD_CONTA"] == code]
        if not hit.empty:
            return _collapse(hit)

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
            return _collapse(hit)
    return {}


def _collapse(hit: pd.DataFrame) -> dict[int, float]:
    """Um valor por ano: conta mais agregada; empate resolvido pelo maior |valor|."""
    tmp = hit.assign(
        _lvl=hit["CD_CONTA"].str.count(r"\."),
        _abs=hit["VL_CONTA_AJUSTADO"].abs(),
    ).sort_values(["ANO_REFER", "_lvl", "_abs"], ascending=[True, True, False])
    tmp = tmp.dropna(subset=["VL_CONTA_AJUSTADO"]).drop_duplicates("ANO_REFER", keep="first")
    return {int(r.ANO_REFER): float(r.VL_CONTA_AJUSTADO) for r in tmp.itertuples()}


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
    receita = _series(dre, ["3.01"], ["RECEITA DE VENDA", "RECEITA LIQUIDA",
                                      "RECEITAS DA INTERMEDIACAO", "RECEITA OPERACIONAL"])
    lucro_bruto = _series(dre, ["3.03"], ["RESULTADO BRUTO", "LUCRO BRUTO"])
    ebit = _series(dre, ["3.05"], ["RESULTADO ANTES DO RESULTADO FINANCEIRO",
                                   "RESULTADO OPERACIONAL"])
    res_fin = _series(dre, ["3.06"], ["RESULTADO FINANCEIRO"])
    lucro_liq = _series(dre, ["3.11", "3.09"], ["LUCRO/PREJUIZO CONSOLIDADO DO PERIODO",
                                                "LUCRO/PREJUIZO DO PERIODO", "LUCRO LIQUIDO"])

    # --- Balanço ---------------------------------------------------------
    ativo = _series(bpa, ["1"], ["ATIVO TOTAL"])
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
        "ativo_total": ativo,
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
