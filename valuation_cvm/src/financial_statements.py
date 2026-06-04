"""
Módulo para carregar, filtrar e construir snapshots financeiros de empresas.
"""

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import PROCESSED_DIR, get_processed_path
from .logger import logger


# ---------------------------------------------------------------------------
# Carregamento de demonstrativos processados
# ---------------------------------------------------------------------------

def load_processed_statement(statement: str, tipo_doc: str) -> pd.DataFrame:
    """
    Carrega o parquet processado de um demonstrativo.

    Exemplo:
        load_processed_statement("DRE", "DFP")
        load_processed_statement("BPA", "ITR")
    """
    parquet_path = get_processed_path(statement.lower(), tipo_doc.lower(), "parquet")

    if not parquet_path.exists():
        logger.warning(
            "Arquivo processado não encontrado: %s. "
            "Execute o pipeline primeiro: python -m src.main",
            parquet_path,
        )
        return pd.DataFrame()

    df = pd.read_parquet(parquet_path)
    logger.info("Carregado %s: %d registros.", parquet_path.name, len(df))
    return df


# ---------------------------------------------------------------------------
# Extração de contas contábeis
# ---------------------------------------------------------------------------

def extract_account(
    df: pd.DataFrame,
    cd_cvm: Optional[str] = None,
    account_keywords: Optional[List[str]] = None,
    cd_conta: Optional[str] = None,
    exact_match: bool = False,
) -> pd.DataFrame:
    """
    Busca contas em um demonstrativo filtradas por empresa, palavras-chave ou código.

    Parâmetros:
        df:               DataFrame do demonstrativo
        cd_cvm:           CD_CVM da empresa (string)
        account_keywords: Lista de palavras-chave para buscar em DS_CONTA
        cd_conta:         Código exato da conta (ex.: "3.01")
        exact_match:      Se True, exige que TODAS as keywords estejam presentes

    Exemplos:
        extract_account(dre, cd_cvm="9512", account_keywords=["receita", "venda"])
        extract_account(dre, cd_cvm="9512", account_keywords=["lucro líquido"])
        extract_account(bpp, cd_cvm="9512", account_keywords=["empréstimos"])
    """
    if df.empty:
        return pd.DataFrame()

    mask = pd.Series([True] * len(df), index=df.index)

    # Filtro por empresa
    if cd_cvm is not None and "CD_CVM" in df.columns:
        mask &= df["CD_CVM"].astype(str).str.strip() == str(cd_cvm).strip()

    # Filtro por código de conta
    if cd_conta is not None and "CD_CONTA" in df.columns:
        mask &= df["CD_CONTA"].astype(str).str.strip() == str(cd_conta).strip()

    # Filtro por palavras-chave em DS_CONTA
    if account_keywords and "DS_CONTA" in df.columns:
        ds_upper = df["DS_CONTA"].fillna("").str.upper()
        if exact_match:
            kw_mask = pd.Series([True] * len(df), index=df.index)
            for kw in account_keywords:
                kw_mask &= ds_upper.str.contains(kw.upper(), regex=False, na=False)
        else:
            kw_mask = pd.Series([False] * len(df), index=df.index)
            for kw in account_keywords:
                kw_mask |= ds_upper.str.contains(kw.upper(), regex=False, na=False)
        mask &= kw_mask

    result = df[mask].copy()
    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Demonstrativo mais recente de uma empresa
# ---------------------------------------------------------------------------

def get_latest_company_statement(
    cd_cvm: str,
    statement: str,
    tipo_doc: str = "DFP",
) -> pd.DataFrame:
    """
    Retorna o demonstrativo mais recente da empresa.

    Filtra por CD_CVM e retorna apenas a última data de referência disponível.
    """
    df = load_processed_statement(statement, tipo_doc)
    if df.empty:
        return pd.DataFrame()

    company_df = df[df["CD_CVM"].astype(str).str.strip() == str(cd_cvm).strip()].copy()
    if company_df.empty:
        logger.warning("Empresa CD_CVM='%s' não encontrada em %s %s.", cd_cvm, tipo_doc, statement)
        return pd.DataFrame()

    # Usar VERSAO mais recente para o último período
    date_col = "DT_REFER" if "DT_REFER" in company_df.columns else "DT_FIM_EXERC"
    if date_col in company_df.columns:
        last_date = company_df[date_col].max()
        company_df = company_df[company_df[date_col] == last_date].copy()

    return company_df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Helpers internos de extração de valor
# ---------------------------------------------------------------------------

def _get_value(
    df: pd.DataFrame,
    cd_cvm: str,
    keywords: List[str],
    date_col: str = "DT_REFER",
    value_col: str = "VL_CONTA_AJUSTADO",
) -> Optional[float]:
    """
    Extrai o valor de uma conta para a data mais recente disponível.
    Retorna None se não encontrar.
    """
    sub = extract_account(df, cd_cvm=cd_cvm, account_keywords=keywords)
    if sub.empty or value_col not in sub.columns:
        return None

    if date_col in sub.columns:
        last_date = sub[date_col].max()
        sub = sub[sub[date_col] == last_date]

    # Se múltiplas linhas, pega a de maior VL_CONTA_AJUSTADO absoluto
    # (situação de contas com agrupamentos diferentes)
    vals = sub[value_col].dropna()
    if vals.empty:
        return None

    # Prefere a conta de menor nível hierárquico (CD_CONTA mais curto = mais agregado)
    if "CD_CONTA" in sub.columns:
        sub_sorted = sub.assign(
            _lvl=sub["CD_CONTA"].astype(str).str.count(r"\.")
        ).sort_values("_lvl")
        first_val = sub_sorted.iloc[0][value_col]
        if pd.notna(first_val):
            return float(first_val)

    return float(vals.iloc[0])


# ---------------------------------------------------------------------------
# Snapshot financeiro
# ---------------------------------------------------------------------------

def build_company_snapshot(cd_cvm: str, tipo_doc: str = "DFP") -> Dict:
    """
    Constrói um resumo financeiro consolidado da empresa.

    Tenta extrair as principais linhas das demonstrações:
    DRE, BPA, BPP e DFC_MI.

    Retorna dicionário com valores e flags de qualidade.
    """
    cd_cvm = str(cd_cvm).strip()

    dre = load_processed_statement("DRE", tipo_doc)
    bpa = load_processed_statement("BPA", tipo_doc)
    bpp = load_processed_statement("BPP", tipo_doc)
    dfc = load_processed_statement("DFC_MI", tipo_doc)

    def get(df: pd.DataFrame, keys: List[str]) -> Optional[float]:
        if df.empty:
            return None
        return _get_value(df, cd_cvm, keys)

    # DRE
    receita = get(dre, ["receita líquida", "receita de venda", "receita operacional líquida"])
    lucro_bruto = get(dre, ["lucro bruto"])
    ebit = get(dre, ["resultado operacional", "ebit", "lucro operacional"])
    lucro_liq = get(dre, ["lucro líquido", "resultado líquido do período"])

    # BPA
    caixa = get(bpa, ["caixa e equivalentes", "disponibilidades", "caixa"])
    aplicacoes = get(bpa, ["aplicações financeiras", "títulos e valores", "investimentos financeiros"])
    ativo_total = get(bpa, ["ativo total"])

    # BPP
    passivo_total = get(bpp, ["passivo total"])
    pl = get(bpp, ["patrimônio líquido", "total do patrimônio líquido"])
    divida_cp = get(bpp, ["empréstimos e financiamentos", "debentures", "dívida", "debêntures"])

    # BPP — dívida de longo prazo
    divida_lp = get(bpp, ["empréstimos e financiamentos de longo prazo"])

    divida_bruta = None
    if divida_cp is not None or divida_lp is not None:
        divida_bruta = (divida_cp or 0.0) + (divida_lp or 0.0)

    # DFC
    fcop = get(dfc, ["caixa gerado", "caixa líquido nas atividades operacionais",
                      "fluxo de caixa das atividades operacionais"])
    capex = get(dfc, ["aquisição de imobilizado", "capex", "investimentos em ativo imobilizado",
                      "pagamento pela aquisição de imobilizado e intangível"])

    # Dívida líquida
    caixa_total = (caixa or 0.0) + (aplicacoes or 0.0)
    divida_liq: Optional[float] = None
    if divida_bruta is not None:
        divida_liq = divida_bruta - caixa_total

    snapshot = {
        # Demonstração de resultado
        "receita_liquida": receita,
        "lucro_bruto": lucro_bruto,
        "ebit": ebit,
        "lucro_liquido": lucro_liq,
        # Balanço
        "caixa_equivalentes": caixa,
        "aplicacoes_financeiras": aplicacoes,
        "ativo_total": ativo_total,
        "passivo_total": passivo_total,
        "patrimonio_liquido": pl,
        "divida_bruta": divida_bruta,
        "divida_liquida": divida_liq,
        # Fluxo de caixa
        "fluxo_caixa_operacional": fcop,
        "capex": capex,
        # Flags de qualidade
        "has_revenue": receita is not None,
        "has_gross_profit": lucro_bruto is not None,
        "has_ebit": ebit is not None,
        "has_net_income": lucro_liq is not None,
        "has_cash": caixa is not None,
        "has_debt": divida_bruta is not None,
        "has_equity": pl is not None,
        "has_operating_cash_flow": fcop is not None,
        "has_capex": capex is not None,
        # Meta
        "cd_cvm": cd_cvm,
        "tipo_doc": tipo_doc,
    }

    # Log de flags
    missing = [k.replace("has_", "") for k, v in snapshot.items() if k.startswith("has_") and not v]
    if missing:
        logger.warning("Snapshot CD_CVM=%s: dados ausentes para: %s", cd_cvm, ", ".join(missing))
    else:
        logger.info("Snapshot CD_CVM=%s: todos os dados principais encontrados.", cd_cvm)

    return snapshot
