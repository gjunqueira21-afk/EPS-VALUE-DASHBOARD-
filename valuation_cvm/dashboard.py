"""
Dashboard Bloomberg-style para análise fundamentalista de empresas brasileiras.

Uso:
    cd valuation_cvm
    streamlit run dashboard.py

Requer dados processados em data/processed/
Execute primeiro:
    python -m src.main --start-year 2019 --end-year 2025
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Path setup — permite rodar como `streamlit run dashboard.py`
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.company_mapper import filter_company_by_name_or_cvm, load_company_registry
from src.config import DEMONSTRATIVOS, PROCESSED_DIR, TIPOS_DOC, get_processed_path
from src.financial_statements import (
    build_company_snapshot,
    load_processed_statement,
)
from src.valuation_dcf import calculate_dcf
from src.valuation_epv import calculate_epv
from src.valuation_metrics import calculate_basic_metrics


# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="EPS VALUE TERMINAL",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# CSS Bloomberg-style
# ---------------------------------------------------------------------------

BLOOMBERG_CSS = """
<style>
/* ── Base ────────────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    background-color: #000000 !important;
    color: #C8C8C8 !important;
    font-family: 'Courier New', Courier, monospace !important;
}
.stApp { background-color: #000000; }
.main .block-container { padding-top: 0.5rem; padding-bottom: 2rem; }

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background-color: #080808 !important;
    border-right: 1px solid #FF6600;
}
section[data-testid="stSidebar"] * { color: #C8C8C8 !important; }
section[data-testid="stSidebar"] .stTextInput input {
    background: #111 !important;
    border: 1px solid #333 !important;
    color: #FFF !important;
}
section[data-testid="stSidebar"] .stTextInput input:focus {
    border-color: #FF6600 !important;
}

/* ── Header ──────────────────────────────────────────────────────────────── */
.bb-header {
    background: linear-gradient(90deg, #1a0800 0%, #050505 60%, #000 100%);
    border-bottom: 2px solid #FF6600;
    padding: 10px 18px 8px 18px;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 20px;
}
.bb-logo {
    background: #FF6600;
    color: #000;
    font-size: 18px;
    font-weight: 900;
    padding: 4px 10px;
    letter-spacing: 2px;
}
.bb-title-block {}
.bb-title {
    color: #FF6600;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
    margin: 0;
}
.bb-subtitle {
    color: #666;
    font-size: 10px;
    letter-spacing: 2px;
    margin: 0;
}

/* ── Metric cards ────────────────────────────────────────────────────────── */
.mc {
    background: #090909;
    border: 1px solid #1A1A1A;
    border-top: 2px solid #FF6600;
    padding: 10px 14px;
    border-radius: 2px;
    margin-bottom: 6px;
    min-height: 68px;
}
.mc-lbl {
    color: #777;
    font-size: 9px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 5px;
}
.mc-val { font-size: 18px; font-weight: 700; color: #FFF; }
.mc-val.pos { color: #00CC44; }
.mc-val.neg { color: #FF3333; }
.mc-val.neu { color: #FF6600; }
.mc-val.nd  { color: #555; font-size: 14px; }

/* ── Section titles ──────────────────────────────────────────────────────── */
.sec-title {
    color: #FF6600;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    border-bottom: 1px solid #1A1A1A;
    padding-bottom: 5px;
    margin-top: 18px;
    margin-bottom: 10px;
}

/* ── Info / warn boxes ───────────────────────────────────────────────────── */
.info-box {
    background: #05050F;
    border-left: 3px solid #2196F3;
    padding: 10px 14px;
    margin: 8px 0;
    font-size: 12px;
    line-height: 1.8;
}
.warn-box {
    background: #0F0800;
    border-left: 3px solid #FFAA00;
    padding: 10px 14px;
    margin: 8px 0;
    font-size: 12px;
    line-height: 1.8;
}
.ok-box {
    background: #030F05;
    border-left: 3px solid #00CC44;
    padding: 10px 14px;
    margin: 8px 0;
    font-size: 12px;
    line-height: 1.8;
}

/* ── Status dots ─────────────────────────────────────────────────────────── */
.dot-ok   { color: #00CC44; }
.dot-warn { color: #FFAA00; }
.dot-err  { color: #FF3333; }

/* ── Tabs ────────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: #000 !important;
    border-bottom: 1px solid #222 !important;
    gap: 2px;
}
.stTabs [data-baseweb="tab"] {
    background: #0A0A0A !important;
    color: #666 !important;
    font-size: 10px !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase !important;
    padding: 7px 18px !important;
    border: 1px solid #111 !important;
}
.stTabs [aria-selected="true"] {
    color: #FF6600 !important;
    background: #0F0400 !important;
    border-bottom: 2px solid #FF6600 !important;
}

/* ── DataFrames ──────────────────────────────────────────────────────────── */
.dataframe, .stDataFrame { background: #090909 !important; }
thead tr th {
    background: #111 !important;
    color: #FF6600 !important;
    font-size: 11px !important;
    border: 1px solid #222 !important;
}
tbody tr td {
    background: #090909 !important;
    color: #C8C8C8 !important;
    font-size: 11px !important;
    border: 1px solid #141414 !important;
}
tbody tr:hover td { background: #111 !important; }

/* ── Inputs ──────────────────────────────────────────────────────────────── */
input, select, textarea {
    background: #0A0A0A !important;
    border: 1px solid #2A2A2A !important;
    color: #EEE !important;
}
.stSlider > div > div > div { background: #FF6600 !important; }
.stButton > button {
    background: #FF6600 !important;
    color: #000 !important;
    font-weight: 700 !important;
    font-size: 11px !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase !important;
    border: none !important;
    padding: 6px 20px !important;
}
.stButton > button:hover { background: #FF8A33 !important; }

/* ── Selectbox ───────────────────────────────────────────────────────────── */
.stSelectbox > div > div {
    background: #0A0A0A !important;
    border: 1px solid #2A2A2A !important;
    color: #EEE !important;
}

/* ── Expander ────────────────────────────────────────────────────────────── */
.streamlit-expanderHeader {
    background: #0A0A0A !important;
    color: #FF6600 !important;
    font-size: 11px !important;
}
</style>
"""

st.markdown(BLOOMBERG_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Plotly theme
# ---------------------------------------------------------------------------

_LAYOUT = dict(
    paper_bgcolor="#000000",
    plot_bgcolor="#080808",
    font=dict(family="Courier New, Courier, monospace", color="#C8C8C8", size=11),
    title_font=dict(color="#FF6600", size=13, family="Courier New"),
    xaxis=dict(gridcolor="#141414", linecolor="#2A2A2A", tickcolor="#555",
               tickfont=dict(color="#777", size=10), showgrid=True),
    yaxis=dict(gridcolor="#141414", linecolor="#2A2A2A", tickcolor="#555",
               tickfont=dict(color="#777", size=10), showgrid=True),
    legend=dict(bgcolor="#0A0A0A", bordercolor="#2A2A2A", borderwidth=1,
                font=dict(color="#C8C8C8", size=10)),
    margin=dict(l=55, r=20, t=45, b=45),
    hovermode="x unified",
)

_COLORS = {
    "orange":  "#FF6600",
    "green":   "#00CC44",
    "blue":    "#2196F3",
    "red":     "#FF3333",
    "yellow":  "#FFD600",
    "cyan":    "#00BCD4",
    "purple":  "#9C27B0",
    "white":   "#FFFFFF",
}


def _bar_chart(years, values, name, color="#FF6600", title="", y_suffix="B"):
    colors = [_COLORS["red"] if v is not None and v < 0 else color for v in values]
    clean = [v if v is not None else 0 for v in values]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=years, y=clean, name=name,
        marker_color=colors,
        text=[f"{v:.1f}{y_suffix}" for v in clean],
        textposition="outside",
        textfont=dict(color="#AAA", size=9),
    ))
    fig.update_layout(**_LAYOUT, title=title, showlegend=False)
    return fig


def _line_chart(years, series, title=""):
    """series: list of (name, values, color)"""
    fig = go.Figure()
    for name, values, color in series:
        clean = [v if v is not None else None for v in values]
        fig.add_trace(go.Scatter(
            x=years, y=clean,
            name=name, mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(color=color, size=5, symbol="circle"),
            connectgaps=False,
        ))
    fig.update_layout(**_LAYOUT, title=title)
    return fig


# ---------------------------------------------------------------------------
# Helpers de formatação
# ---------------------------------------------------------------------------

def _float(val):
    """Converte para float seguro."""
    if val is None:
        return None
    try:
        v = float(val)
        return None if (v != v) else v  # isnan check
    except (TypeError, ValueError):
        return None


def fmt_brl(val, scale=1e9, suffix="B"):
    v = _float(val)
    if v is None:
        return "N/D"
    return f"R$ {v / scale:,.2f}{suffix}"


def fmt_pct(val):
    v = _float(val)
    if v is None:
        return "N/D"
    return f"{v * 100:.2f}%"


def _color_cls(val, positive_good=True):
    v = _float(val)
    if v is None:
        return "nd"
    if v > 0:
        return "pos" if positive_good else "neg"
    if v < 0:
        return "neg" if positive_good else "pos"
    return "neu"


def mc(label, value_str, css_class="neu"):
    """Renderiza um metric card."""
    return f"""
<div class="mc">
  <div class="mc-lbl">{label}</div>
  <div class="mc-val {css_class}">{value_str}</div>
</div>"""


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=120)
def _load_registry():
    return load_company_registry()


@st.cache_data(ttl=120)
def _check_data():
    """Verifica disponibilidade de arquivos processados."""
    result = {}
    for tipo in TIPOS_DOC:
        for stmt in DEMONSTRATIVOS:
            key = f"{tipo}_{stmt}"
            p = get_processed_path(stmt.lower(), tipo.lower(), "parquet")
            result[key] = p.exists()
    return result


@st.cache_data(ttl=60)
def _snapshot(cd_cvm: str, tipo_doc: str):
    return build_company_snapshot(cd_cvm, tipo_doc=tipo_doc)


@st.cache_data(ttl=60)
def _load_stmt(stmt: str, tipo_doc: str):
    return load_processed_statement(stmt, tipo_doc)


@st.cache_data(ttl=60)
def _company_history(cd_cvm: str, tipo_doc: str) -> pd.DataFrame:
    """Série histórica de métricas por ano fiscal."""
    dre = _load_stmt("DRE", tipo_doc)
    bpa = _load_stmt("BPA", tipo_doc)
    bpp = _load_stmt("BPP", tipo_doc)
    dfc = _load_stmt("DFC_MI", tipo_doc)

    if dre.empty:
        return pd.DataFrame()

    def _filter(df):
        if df.empty or "CD_CVM" not in df.columns:
            return pd.DataFrame()
        sub = df[df["CD_CVM"].astype(str).str.strip() == str(cd_cvm).strip()].copy()
        if not sub.empty and "ANO_REFER" not in sub.columns and "DT_FIM_EXERC" in sub.columns:
            sub["ANO_REFER"] = pd.to_datetime(sub["DT_FIM_EXERC"], errors="coerce").dt.year
        return sub

    dre_c = _filter(dre)
    bpa_c = _filter(bpa)
    bpp_c = _filter(bpp)
    dfc_c = _filter(dfc)

    if dre_c.empty or "ANO_REFER" not in dre_c.columns:
        return pd.DataFrame()

    years = sorted(dre_c["ANO_REFER"].dropna().unique())

    def _pick(df, year, *kws):
        if df.empty or "ANO_REFER" not in df.columns:
            return None
        sub = df[df["ANO_REFER"] == year]
        if sub.empty:
            return None
        vc = "VL_CONTA_AJUSTADO" if "VL_CONTA_AJUSTADO" in sub.columns else "VL_CONTA"
        if "DS_CONTA" not in sub.columns or vc not in sub.columns:
            return None
        ds = sub["DS_CONTA"].fillna("").str.upper()
        for kw in kws:
            mask = ds.str.contains(kw.upper(), regex=False, na=False)
            if mask.any():
                s2 = sub[mask]
                if "CD_CONTA" in s2.columns:
                    s2 = s2.assign(_l=s2["CD_CONTA"].astype(str).str.count(r"\.")
                                   ).sort_values("_l")
                vals = s2[vc].dropna()
                if not vals.empty:
                    return float(vals.iloc[0])
        return None

    rows = []
    for y in years:
        rows.append({
            "ano":        y,
            "receita":    _pick(dre_c, y, "receita líquida", "receita de venda"),
            "lucro_bruto":_pick(dre_c, y, "lucro bruto"),
            "ebit":       _pick(dre_c, y, "resultado operacional", "ebit", "lucro operacional"),
            "lucro_liq":  _pick(dre_c, y, "lucro líquido", "resultado líquido do período"),
            "ativo":      _pick(bpa_c, y, "ativo total"),
            "pl":         _pick(bpp_c, y, "patrimônio líquido"),
            "fcop":       _pick(dfc_c, y, "caixa gerado", "caixa líquido nas atividades operacionais",
                                "fluxo de caixa das atividades operacionais"),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# UI components
# ---------------------------------------------------------------------------

def render_header():
    st.markdown("""
<div class="bb-header">
  <div class="bb-logo">EPS</div>
  <div class="bb-title-block">
    <div class="bb-title">VALUE TERMINAL</div>
    <div class="bb-subtitle">ANÁLISE FUNDAMENTALISTA · DADOS CVM ABERTOS · B3 · BRASIL</div>
  </div>
</div>""", unsafe_allow_html=True)


def render_overview(company_name, cd_cvm, m):
    st.markdown(
        f'<div class="sec-title">📊 {company_name} &nbsp;|&nbsp; CD_CVM: {cd_cvm}</div>',
        unsafe_allow_html=True,
    )

    # Row 1 — P&L
    c = st.columns(4)
    c[0].markdown(mc("Receita Líquida",    fmt_brl(m.get("receita_liquida")), "neu"), unsafe_allow_html=True)
    c[1].markdown(mc("Lucro Bruto",         fmt_brl(m.get("lucro_bruto")),     _color_cls(m.get("lucro_bruto"))), unsafe_allow_html=True)
    c[2].markdown(mc("EBIT",                fmt_brl(m.get("ebit")),            _color_cls(m.get("ebit"))), unsafe_allow_html=True)
    c[3].markdown(mc("Lucro Líquido",       fmt_brl(m.get("lucro_liquido")),   _color_cls(m.get("lucro_liquido"))), unsafe_allow_html=True)

    # Row 2 — Balance
    c2 = st.columns(4)
    c2[0].markdown(mc("Caixa Total",        fmt_brl(m.get("caixa_total")),     "pos"), unsafe_allow_html=True)
    c2[1].markdown(mc("Dívida Bruta",       fmt_brl(m.get("divida_bruta")),    _color_cls(m.get("divida_bruta"), False)), unsafe_allow_html=True)
    c2[2].markdown(mc("Dívida Líquida",     fmt_brl(m.get("divida_liquida")),  _color_cls(m.get("divida_liquida"), False)), unsafe_allow_html=True)
    c2[3].markdown(mc("Patrimônio Líquido", fmt_brl(m.get("patrimonio_liquido")), _color_cls(m.get("patrimonio_liquido"))), unsafe_allow_html=True)

    # Row 3 — Margins
    c3 = st.columns(4)
    c3[0].markdown(mc("Margem Bruta",   fmt_pct(m.get("margem_bruta")),  _color_cls(m.get("margem_bruta"))), unsafe_allow_html=True)
    c3[1].markdown(mc("Margem EBIT",    fmt_pct(m.get("margem_ebit")),   _color_cls(m.get("margem_ebit"))), unsafe_allow_html=True)
    c3[2].markdown(mc("Margem Líquida", fmt_pct(m.get("margem_liquida")),_color_cls(m.get("margem_liquida"))), unsafe_allow_html=True)
    c3[3].markdown(mc("Ativo Total",    fmt_brl(m.get("ativo_total")),   "neu"), unsafe_allow_html=True)

    # Row 4 — Returns
    c4 = st.columns(4)
    c4[0].markdown(mc("ROE",          fmt_pct(m.get("roe")),       _color_cls(m.get("roe"))), unsafe_allow_html=True)
    c4[1].markdown(mc("ROA",          fmt_pct(m.get("roa")),       _color_cls(m.get("roa"))), unsafe_allow_html=True)
    c4[2].markdown(mc("ROIC (aprox)", fmt_pct(m.get("roic_aprox")),_color_cls(m.get("roic_aprox"))), unsafe_allow_html=True)
    c4[3].markdown(mc("FCL (aprox)",  fmt_brl(m.get("fcl_aprox")), _color_cls(m.get("fcl_aprox"))), unsafe_allow_html=True)


def _stmt_table(df, title, date_key):
    st.markdown(f'<div class="sec-title">{title}</div>', unsafe_allow_html=True)
    if df.empty:
        st.markdown('<div class="warn-box">Sem dados disponíveis para este demonstrativo.</div>',
                    unsafe_allow_html=True)
        return

    vc = "VL_CONTA_AJUSTADO" if "VL_CONTA_AJUSTADO" in df.columns else "VL_CONTA"

    # Date picker
    if "DT_FIM_EXERC" in df.columns:
        datas = sorted(df["DT_FIM_EXERC"].unique(), reverse=True)[:8]
        sel_date = st.selectbox("Período:", datas, key=date_key)
        sub = df[df["DT_FIM_EXERC"] == sel_date].copy()
    else:
        sub = df.copy()

    cols_show = [c for c in ["CD_CONTA", "DS_CONTA", vc] if c in sub.columns]
    disp = sub[cols_show].copy()
    if vc in disp.columns:
        disp[vc] = disp[vc].apply(
            lambda x: f"R$ {x/1e6:,.2f} M" if pd.notna(x) else "–"
        )
        disp = disp.rename(columns={vc: "VALOR (R$ M)", "DS_CONTA": "CONTA"})

    st.dataframe(disp, use_container_width=True, hide_index=True, height=420)


def _epv_tab(m):
    st.markdown('<div class="sec-title">EPV — EARNINGS POWER VALUE (Greenwald)</div>', unsafe_allow_html=True)
    st.markdown("""
<div class="info-box">
<b>Fórmula:</b>&nbsp; NOPAT = EBIT × (1 − alíquota) &nbsp;|&nbsp; EPV = NOPAT / WACC &nbsp;|&nbsp; EPV Equity = EPV − Dívida Líquida
</div>""", unsafe_allow_html=True)

    ebit_ref = _float(m.get("ebit")) or 0.0
    nd_ref   = _float(m.get("divida_liquida")) or 0.0

    col_in, col_out = st.columns(2)

    with col_in:
        st.markdown("**Parâmetros**")
        ebit_m = st.number_input("EBIT normalizado (R$ milhões)", value=round(ebit_ref / 1e6, 1),
                                  step=100.0, key="epv_ebit")
        tax    = st.slider("Alíquota efetiva (IRPJ+CSLL)", 0.0, 0.50, 0.34, 0.01, format="%.2f", key="epv_tax")
        wacc   = st.slider("WACC", 0.06, 0.25, 0.12, 0.005, format="%.3f", key="epv_wacc")
        nd_m   = st.number_input("Dívida Líquida (R$ milhões)", value=round(nd_ref / 1e6, 1),
                                  step=100.0, key="epv_nd")
        shr_m  = st.number_input("Ações em circulação (milhões) — externo",
                                  value=0.0, step=10.0, key="epv_shr",
                                  help="Número de ações: B3 / brapi.dev. Deixe 0 para não calcular por ação.")

    with col_out:
        st.markdown("**Resultado**")
        res = calculate_epv(
            ebit_normalized=ebit_m * 1e6,
            tax_rate=tax,
            wacc=wacc,
            net_debt=nd_m * 1e6,
        )
        if shr_m > 0 and res.get("epv_equity"):
            res["epv_per_share"] = res["epv_equity"] / (shr_m * 1e6)

        flags_str = "  ·  ".join(res.get("flags", []))

        st.markdown(mc("NOPAT",          fmt_brl(res.get("nopat")),          _color_cls(res.get("nopat"))),          unsafe_allow_html=True)
        st.markdown(mc("EPV Enterprise", fmt_brl(res.get("epv_enterprise")), _color_cls(res.get("epv_enterprise"))), unsafe_allow_html=True)
        st.markdown(mc("EPV Equity",     fmt_brl(res.get("epv_equity")),     _color_cls(res.get("epv_equity"))),     unsafe_allow_html=True)

        if res.get("epv_per_share"):
            st.markdown(mc("EPV por Ação", f"R$ {res['epv_per_share']:,.2f}", _color_cls(res.get("epv_per_share"))),
                        unsafe_allow_html=True)

        st.markdown(f"`STATUS: {flags_str}`")

        nopat = res.get("nopat")
        epv_e = res.get("epv_enterprise")
        epv_q = res.get("epv_equity")
        if nopat and epv_e and epv_q:
            st.markdown(f"""
<div class="info-box">
  NOPAT = {ebit_m:.1f}M × (1 − {tax:.2f}) = R$ {nopat/1e6:.1f}M<br>
  EPV   = {nopat/1e6:.1f}M ÷ {wacc:.3f} = R$ {epv_e/1e9:.2f}B<br>
  Equity = {epv_e/1e9:.2f}B − {nd_m/1e3:.2f}B = R$ {epv_q/1e9:.2f}B
</div>""", unsafe_allow_html=True)


def _dcf_tab(m):
    st.markdown('<div class="sec-title">DCF — DISCOUNTED CASH FLOW</div>', unsafe_allow_html=True)
    st.markdown("""
<div class="info-box">
<b>Fórmula:</b>&nbsp; EV = Σ FCL_t/(1+WACC)^t + TV/(1+WACC)^n
&nbsp;|&nbsp; TV = FCL_n × (1+g) / (WACC − g) &nbsp;|&nbsp; Equity = EV − Dívida Líquida
</div>""", unsafe_allow_html=True)

    fcl_ref = _float(m.get("fcl_aprox")) or 0.0
    nd_ref  = _float(m.get("divida_liquida")) or 0.0

    col_in, col_out = st.columns([1, 1])

    with col_in:
        st.markdown("**Parâmetros**")
        base_fcl = st.number_input("FCL Base (R$ milhões)", value=round(fcl_ref / 1e6, 1),
                                    step=100.0, key="dcf_fcl")

        st.markdown("*Taxas de crescimento por fase:*")
        cg1, cg2 = st.columns(2)
        with cg1:
            g12 = st.slider("Anos 1–2",  0.0, 0.35, 0.10, 0.01, format="%.2f", key="dcf_g12")
            g34 = st.slider("Anos 3–4",  0.0, 0.25, 0.08, 0.01, format="%.2f", key="dcf_g34")
        with cg2:
            g5  = st.slider("Ano 5",     0.0, 0.20, 0.05, 0.01, format="%.2f", key="dcf_g5")
            g_t = st.slider("g terminal",0.0, 0.07, 0.03, 0.005, format="%.3f", key="dcf_gt")

        wacc = st.slider("WACC", 0.06, 0.25, 0.12, 0.005, format="%.3f", key="dcf_wacc")
        nd_m = st.number_input("Dívida Líquida (R$ milhões)", value=round(nd_ref / 1e6, 1),
                                step=100.0, key="dcf_nd")
        shr_dcf = st.number_input("Ações em circulação (milhões) — externo",
                                   value=0.0, step=10.0, key="dcf_shr",
                                   help="Deixe 0 para não calcular por ação.")

    with col_out:
        st.markdown("**Resultado**")
        growth_rates = [g12, g12, g34, g34, g5]

        if wacc <= g_t:
            st.error(f"WACC ({wacc:.3f}) deve ser maior que g terminal ({g_t:.3f})!")
        elif base_fcl == 0:
            st.warning("Informe o FCL Base para calcular o DCF.")
        else:
            dcf = calculate_dcf(
                base_fcf=base_fcl * 1e6,
                growth_rates=growth_rates,
                terminal_growth=g_t,
                wacc=wacc,
                net_debt=nd_m * 1e6,
            )

            ev  = dcf.get("enterprise_value")
            eq  = dcf.get("equity_value")
            vpt = dcf.get("vp_valor_terminal")
            pct = dcf.get("premissas", {}).get("pct_ev_de_valor_terminal")

            if shr_dcf > 0 and eq:
                eq_per_shr = eq / (shr_dcf * 1e6)
            else:
                eq_per_shr = None

            flags_str = "  ·  ".join(dcf.get("flags", []))

            st.markdown(mc("Enterprise Value",  fmt_brl(ev),  _color_cls(ev)),  unsafe_allow_html=True)
            st.markdown(mc("Equity Value",       fmt_brl(eq),  _color_cls(eq)),  unsafe_allow_html=True)
            st.markdown(mc("VP Valor Terminal",  fmt_brl(vpt), "neu"),           unsafe_allow_html=True)

            if pct is not None:
                cls = "pos" if pct < 75 else "neg"
                st.markdown(mc("% EV do Valor Terminal", f"{pct:.1f}%", cls), unsafe_allow_html=True)

            if eq_per_shr:
                st.markdown(mc("Equity por Ação", f"R$ {eq_per_shr:,.2f}", _color_cls(eq_per_shr)),
                            unsafe_allow_html=True)

            st.markdown(f"`STATUS: {flags_str}`")

            # Projection table
            fcfs = dcf.get("fcfs_projetados", [])
            vps  = dcf.get("vp_fcfs", [])
            if fcfs:
                proj = pd.DataFrame({
                    "Ano":             list(range(1, len(fcfs) + 1)),
                    "FCL Projetado":   [f"R$ {v/1e6:,.1f}M" for v in fcfs],
                    "VP do FCL":       [f"R$ {v/1e6:,.1f}M" for v in vps],
                    "g Aplicada":      [f"{r:.1%}" for r in growth_rates],
                })
                st.dataframe(proj, use_container_width=True, hide_index=True)

    # Sensitivity
    if base_fcl != 0 and wacc > g_t:
        st.markdown('<div class="sec-title">Sensibilidade do Enterprise Value (R$ Bilhões)</div>',
                    unsafe_allow_html=True)

        waccs = [max(0.07, wacc + dw) for dw in [-0.02, -0.01, 0, 0.01, 0.02]]
        gs    = [g for g in [max(0.01, g_t - 0.01), g_t, min(g_t + 0.01, 0.07)]
                 if g < wacc - 0.01]

        if gs:
            rows = []
            for w in waccs:
                row = {"WACC \\ g": f"{w:.2%}"}
                for g in gs:
                    if w > g + 0.005:
                        d = calculate_dcf(base_fcl * 1e6, growth_rates, g, w, nd_m * 1e6)
                        ev_s = d.get("enterprise_value")
                        row[f"g={g:.1%}"] = f"{ev_s/1e9:.1f}B" if ev_s else "N/D"
                    else:
                        row[f"g={g:.1%}"] = "—"
                rows.append(row)
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Welcome screen
# ---------------------------------------------------------------------------

def _welcome(avail):
    st.markdown("""
<div class="info-box">
  <b>EPS VALUE TERMINAL</b><br><br>
  Bem-vindo ao terminal de análise fundamentalista.<br>
  🔍 Use a barra lateral para buscar uma empresa por <b>nome</b>, <b>CD_CVM</b> ou <b>CNPJ</b>.<br>
  📊 Veja DRE, Balanço, DFC, métricas e histórico gráfico.<br>
  💹 Calcule EPV e DCF com parâmetros totalmente ajustáveis.
</div>""", unsafe_allow_html=True)

    st.markdown('<div class="sec-title">Dados Disponíveis no Cache Local</div>', unsafe_allow_html=True)
    total_empresas = 0
    for tipo in TIPOS_DOC:
        cols_row = st.columns(len(DEMONSTRATIVOS))
        for idx, stmt in enumerate(DEMONSTRATIVOS):
            key = f"{tipo}_{stmt}"
            ok = avail.get(key, False)
            with cols_row[idx]:
                if ok:
                    try:
                        df_tmp = pd.read_parquet(
                            get_processed_path(stmt.lower(), tipo.lower(), "parquet"),
                            columns=["CD_CVM"],
                        )
                        n_co = df_tmp["CD_CVM"].nunique()
                        n_rc = len(df_tmp)
                        total_empresas = max(total_empresas, n_co)
                        st.markdown(
                            f'<div class="mc"><div class="mc-lbl">{tipo}/{stmt}</div>'
                            f'<div class="mc-val pos">{n_rc:,} reg</div>'
                            f'<div style="color:#FF6600;font-size:10px">{n_co:,} empresas</div></div>',
                            unsafe_allow_html=True,
                        )
                    except Exception:
                        st.markdown(
                            f'<div class="mc"><div class="mc-lbl">{tipo}/{stmt}</div>'
                            f'<div class="mc-val pos">✓ OK</div></div>',
                            unsafe_allow_html=True,
                        )
                else:
                    st.markdown(
                        f'<div class="mc"><div class="mc-lbl">{tipo}/{stmt}</div>'
                        f'<div class="mc-val nd">Não baixado</div></div>',
                        unsafe_allow_html=True,
                    )


# ---------------------------------------------------------------------------
# No-data / demo mode
# ---------------------------------------------------------------------------

def _demo_mode():
    st.markdown("""
<div class="warn-box">
  <b>⚠ NENHUM DADO PROCESSADO ENCONTRADO</b><br><br>
  Execute o pipeline CVM no seu computador:<br><br>
  <code>cd valuation_cvm</code><br>
  <code>python -m src.main --start-year 2019 --end-year 2025</code><br><br>
  O pipeline baixa os dados diretamente da CVM (pode levar 20–60 minutos dependendo
  da sua conexão). Após concluir, reinicie este dashboard.
</div>""", unsafe_allow_html=True)

    st.markdown('<div class="sec-title">Prévia — Dados Hipotéticos de Demonstração</div>',
                unsafe_allow_html=True)

    st.markdown("""
<div class="info-box">
  ℹ Os valores abaixo são <b>hipotéticos</b> apenas para ilustrar o layout.
  Dados reais aparecem após executar o pipeline CVM.
</div>""", unsafe_allow_html=True)

    demo_snap = {
        "receita_liquida": 55_000_000_000,
        "lucro_bruto":     22_000_000_000,
        "ebit":            13_000_000_000,
        "lucro_liquido":    8_500_000_000,
        "caixa_equivalentes":  10_000_000_000,
        "aplicacoes_financeiras": 5_000_000_000,
        "divida_bruta":    32_000_000_000,
        "patrimonio_liquido": 45_000_000_000,
        "ativo_total":    130_000_000_000,
        "fluxo_caixa_operacional": 11_000_000_000,
        "capex":           3_200_000_000,
    }
    m_demo = calculate_basic_metrics(demo_snap)
    m_demo["caixa_total"] = (demo_snap.get("caixa_equivalentes") or 0) + (demo_snap.get("aplicacoes_financeiras") or 0)
    m_demo["divida_liquida"] = demo_snap["divida_bruta"] - m_demo["caixa_total"]

    render_overview("EMPRESA DEMONSTRAÇÃO S.A.", "00000", m_demo)

    anos = [2019, 2020, 2021, 2022, 2023, 2024]
    receitas = [38e9, 35e9, 43e9, 52e9, 56e9, 55e9]
    ebits    = [9e9,  7e9, 11e9, 14e9, 15e9, 13e9]
    lucros   = [5e9,  4e9,  8e9,  9.5e9, 10e9, 8.5e9]

    fig = _line_chart(
        anos,
        [
            ("Receita Líquida", [v/1e9 for v in receitas], _COLORS["orange"]),
            ("EBIT",            [v/1e9 for v in ebits],    _COLORS["green"]),
            ("Lucro Líquido",   [v/1e9 for v in lucros],   _COLORS["blue"]),
        ],
        title="Evolução Financeira (R$ Bilhões) — DEMONSTRAÇÃO",
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    render_header()

    # --- Sidebar ---
    with st.sidebar:
        st.markdown('<div class="sec-title">🔍 Buscar Empresa</div>', unsafe_allow_html=True)

        query = st.text_input(
            "",
            placeholder="Nome, CD_CVM ou CNPJ...",
            key="q",
            label_visibility="collapsed",
        )

        tipo_doc = st.selectbox(
            "Tipo de relatório",
            ["DFP — Anual", "ITR — Trimestral"],
            key="tipo",
        )
        tipo_doc = tipo_doc.split(" ")[0]

        st.markdown("---")

        avail = _check_data()
        has_data = any(avail.values())

        st.markdown('<div class="sec-title">Status dos Dados</div>', unsafe_allow_html=True)
        for tipo in TIPOS_DOC:
            ok_cnt = sum(v for k, v in avail.items() if k.startswith(tipo))
            total  = sum(1 for k in avail if k.startswith(tipo))
            if ok_cnt == total:
                cls, ico = "dot-ok",   "●"
            elif ok_cnt > 0:
                cls, ico = "dot-warn", "◑"
            else:
                cls, ico = "dot-err",  "○"
            st.markdown(f'<span class="{cls}">{ico} {tipo}: {ok_cnt}/{total} arquivos</span>',
                        unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("""
<div style="font-size:10px;color:#555;line-height:2">
Para baixar os dados:<br>
<code style="color:#777">cd valuation_cvm</code><br>
<code style="color:#777">python -m src.main \\</code><br>
<code style="color:#777"> --start-year 2019 \\</code><br>
<code style="color:#777"> --end-year 2025</code><br><br>
Dados: <a href="https://dados.cvm.gov.br" style="color:#FF6600">dados.cvm.gov.br</a>
</div>""", unsafe_allow_html=True)

    # --- Main area ---
    if not has_data:
        _demo_mode()
        return

    # Search
    selected_cd_cvm  = None
    selected_company = None

    if query:
        registry = _load_registry()
        if registry.empty:
            st.markdown('<div class="warn-box">Cadastro de empresas não encontrado.</div>',
                        unsafe_allow_html=True)
        else:
            matches = filter_company_by_name_or_cvm(query, df=registry)

            if matches.empty:
                st.markdown(
                    f'<div class="warn-box">Nenhuma empresa encontrada para <b>"{query}"</b>.</div>',
                    unsafe_allow_html=True,
                )
            else:
                if len(matches) > 1:
                    st.markdown('<div class="sec-title">Resultados da Busca</div>', unsafe_allow_html=True)
                    opts = [
                        f"{row.get('DENOM_CIA','N/D')}  (CD_CVM: {row.get('CD_CVM','?')})"
                        for _, row in matches.iterrows()
                    ]
                    idx = st.selectbox("Selecione:", range(len(opts)),
                                       format_func=lambda i: opts[i], key="sel_co")
                    row = matches.iloc[idx]
                else:
                    row = matches.iloc[0]

                selected_cd_cvm  = str(row.get("CD_CVM", "")).strip()
                selected_company = str(row.get("DENOM_CIA", "N/D")).strip()

    if not selected_cd_cvm:
        _welcome(avail)
        return

    # --- Company dashboard ---
    with st.spinner(f"Carregando dados de {selected_company}..."):
        snap = _snapshot(selected_cd_cvm, tipo_doc)
        m    = calculate_basic_metrics(snap)
        m["caixa_total"]    = (snap.get("caixa_equivalentes") or 0) + (snap.get("aplicacoes_financeiras") or 0) or None
        m["divida_liquida"] = snap.get("divida_liquida")

    render_overview(selected_company, selected_cd_cvm, m)

    tab_hist, tab_dre, tab_bpa, tab_bpp, tab_dfc, tab_epv, tab_dcf = st.tabs(
        ["HISTÓRICO", "DRE", "ATIVO", "PASSIVO+PL", "FLUXO CAIXA", "EPV", "DCF"]
    )

    # ── Histórico ───────────────────────────────────────────────────────────
    with tab_hist:
        hist = _company_history(selected_cd_cvm, tipo_doc)

        if hist.empty:
            st.markdown('<div class="warn-box">Histórico não disponível. Verifique se há dados processados suficientes.</div>',
                        unsafe_allow_html=True)
        else:
            anos = hist["ano"].tolist()

            def _b(col):
                return [(_float(v) / 1e9 if _float(v) is not None else None) for v in hist[col]]

            # Revenue / EBIT / Net Income
            fig1 = _line_chart(
                anos,
                [
                    ("Receita Líquida", _b("receita"),    _COLORS["orange"]),
                    ("EBIT",            _b("ebit"),       _COLORS["green"]),
                    ("Lucro Líquido",   _b("lucro_liq"),  _COLORS["blue"]),
                ],
                title=f"{selected_company} — Resultado (R$ Bilhões)",
            )
            st.plotly_chart(fig1, use_container_width=True)

            # FCOP bar
            fcop_vals = _b("fcop")
            if any(v is not None for v in fcop_vals):
                fig2 = _bar_chart(anos, fcop_vals, "FCOP", _COLORS["cyan"],
                                  f"{selected_company} — Fluxo de Caixa Operacional (R$ Bilhões)")
                st.plotly_chart(fig2, use_container_width=True)

            # Equity / Assets
            pl_vals = _b("pl")
            at_vals = _b("ativo")
            if any(v is not None for v in pl_vals):
                fig3 = _line_chart(
                    anos,
                    [
                        ("Patrimônio Líquido", pl_vals, _COLORS["yellow"]),
                        ("Ativo Total",        at_vals, _COLORS["purple"]),
                    ],
                    title=f"{selected_company} — Patrimônio e Ativo (R$ Bilhões)",
                )
                st.plotly_chart(fig3, use_container_width=True)

            # Raw table
            st.markdown('<div class="sec-title">Tabela Histórica</div>', unsafe_allow_html=True)
            disp = hist.copy()
            for col in ["receita", "lucro_bruto", "ebit", "lucro_liq", "ativo", "pl", "fcop"]:
                if col in disp.columns:
                    disp[col] = disp[col].apply(
                        lambda x: f"R$ {x/1e9:.2f}B" if pd.notna(x) and x != 0 else "–"
                    )
            disp.columns = [c.upper().replace("_", " ") for c in disp.columns]
            st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── DRE ─────────────────────────────────────────────────────────────────
    with tab_dre:
        dre_df = _load_stmt("DRE", tipo_doc)
        co_dre = dre_df[dre_df["CD_CVM"].astype(str).str.strip() == selected_cd_cvm].copy() \
            if not dre_df.empty else pd.DataFrame()
        _stmt_table(co_dre, f"DRE — Demonstração do Resultado — {selected_company}", "dt_dre")

    # ── BPA ──────────────────────────────────────────────────────────────────
    with tab_bpa:
        bpa_df = _load_stmt("BPA", tipo_doc)
        co_bpa = bpa_df[bpa_df["CD_CVM"].astype(str).str.strip() == selected_cd_cvm].copy() \
            if not bpa_df.empty else pd.DataFrame()
        _stmt_table(co_bpa, f"BPA — Balanço Patrimonial Ativo — {selected_company}", "dt_bpa")

    # ── BPP ──────────────────────────────────────────────────────────────────
    with tab_bpp:
        bpp_df = _load_stmt("BPP", tipo_doc)
        co_bpp = bpp_df[bpp_df["CD_CVM"].astype(str).str.strip() == selected_cd_cvm].copy() \
            if not bpp_df.empty else pd.DataFrame()
        _stmt_table(co_bpp, f"BPP — Balanço Patrimonial Passivo + PL — {selected_company}", "dt_bpp")

    # ── DFC ──────────────────────────────────────────────────────────────────
    with tab_dfc:
        dfc_df = _load_stmt("DFC_MI", tipo_doc)
        co_dfc = dfc_df[dfc_df["CD_CVM"].astype(str).str.strip() == selected_cd_cvm].copy() \
            if not dfc_df.empty else pd.DataFrame()
        _stmt_table(co_dfc, f"DFC — Demonstração de Fluxo de Caixa — {selected_company}", "dt_dfc")

    # ── EPV ──────────────────────────────────────────────────────────────────
    with tab_epv:
        _epv_tab(m)

    # ── DCF ──────────────────────────────────────────────────────────────────
    with tab_dcf:
        _dcf_tab(m)


if __name__ == "__main__":
    main()
