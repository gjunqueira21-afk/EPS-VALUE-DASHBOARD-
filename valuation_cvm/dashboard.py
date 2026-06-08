"""
EPS VALUE TERMINAL v2
Tema: Midnight Blue — Alta legibilidade, profissional (sem laranja)

Baseado em pesquisa de UX: TradingView dark mode, Bloomberg acessível,
WCAG 2.2 contrast ratios. Fonte: Inter/Segoe UI com figuras tabulares.

Abas:
  VISÃO GERAL · HISTÓRICO · DEMONSTRATIVOS · SAÚDE FINANCEIRA · VALUATION · MACRO BRASIL

Uso:
    cd valuation_cvm
    streamlit run dashboard.py
"""

import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.brapi_client import BrapiClient
from src.company_mapper import filter_company_by_name_or_cvm, load_company_registry
from src.config import DEMONSTRATIVOS, TIPOS_DOC, get_processed_path
from src.financial_statements import build_company_snapshot, load_processed_statement
from src.valuation_dcf import calculate_dcf
from src.valuation_epv import calculate_epv
from src.valuation_metrics import calculate_basic_metrics

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="EPS Value Terminal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Paleta Midnight Blue
# Referência: TradingView dark + Bloomberg acessível + WCAG AA 4.5:1
# ─────────────────────────────────────────────────────────────────────────────

C = {
    # Fundos
    "bg":      "#111827",   # fundo principal — dark navy, não preto puro
    "surf":    "#1F2937",   # cards e painéis
    "surf2":   "#273244",   # hover / destaque sutil
    "sidebar": "#0F172A",   # sidebar ligeiramente mais escura

    # Bordas
    "brd":     "#374151",   # borda sutil
    "brd2":    "#4B5563",   # borda visível

    # Texto — progressão clara → muted
    "t1":      "#F0F4F8",   # texto principal (branco suave, não puro — reduz halação)
    "t2":      "#9CA3AF",   # texto secundário
    "t3":      "#6B7280",   # texto desabilitado / rótulos

    # Cores semânticas
    "green":   "#10B981",   # positivo (Emerald 500 — CVD-friendly)
    "green_l": "#34D399",   # positivo claro
    "red":     "#EF4444",   # negativo
    "red_l":   "#FCA5A5",   # negativo suave
    "yellow":  "#FBBF24",   # atenção / neutral
    "yellow_l":"#FDE68A",   # atenção suave

    # Acento principal — azul (confiança, profissional)
    "blue":    "#3B82F6",   # Blue 500
    "blue_l":  "#93C5FD",   # Blue 300 — labels sobre fundo escuro
    "blue_d":  "#1D4ED8",   # Blue 700

    # Acentos secundários
    "cyan":    "#22D3EE",   # destaque de dados
    "purple":  "#A78BFA",   # destaque alternativo
    "teal":    "#2DD4BF",   # EV / valuation
}


def rgba(hex_c: str, alpha: float) -> str:
    h = hex_c.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {{
    background-color: {C['bg']} !important;
    color: {C['t1']} !important;
    font-family: 'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif !important;
    font-feature-settings: "tnum" on, "lnum" on;  /* figuras tabulares para números */
}}
.stApp {{ background-color: {C['bg']}; }}
.main .block-container {{ padding-top: 0.5rem; padding-bottom: 2rem; max-width: 100%; }}

/* ── Sidebar ────────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{
    background-color: {C['sidebar']} !important;
    border-right: 1px solid {C['brd']} !important;
}}
section[data-testid="stSidebar"] * {{ color: {C['t2']} !important; }}
section[data-testid="stSidebar"] input {{
    background: {C['surf']} !important;
    border: 1px solid {C['brd2']} !important;
    color: {C['t1']} !important;
    border-radius: 6px !important;
    font-size: 13px !important;
}}
section[data-testid="stSidebar"] input:focus {{
    border-color: {C['blue']} !important;
    box-shadow: 0 0 0 3px {rgba(C['blue'], 0.18)} !important;
    outline: none !important;
}}

/* ── Header ─────────────────────────────────────────────────────────────── */
.trm-header {{
    background: linear-gradient(135deg, #0B1120 0%, {C['bg']} 100%);
    border-bottom: 1px solid {C['brd2']};
    padding: 14px 24px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 14px;
}}
.trm-badge {{
    background: {C['blue']};
    color: #fff;
    font-size: 13px;
    font-weight: 700;
    padding: 5px 14px;
    border-radius: 5px;
    letter-spacing: 2px;
    text-transform: uppercase;
    white-space: nowrap;
}}
.trm-title {{ color: {C['t1']}; font-size: 16px; font-weight: 600; margin: 0; }}
.trm-sub   {{ color: {C['t3']}; font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; margin: 0; }}

/* ── Company strip ──────────────────────────────────────────────────────── */
.co-strip {{
    background: {C['surf']};
    border: 1px solid {C['brd']};
    border-left: 4px solid {C['blue']};
    border-radius: 0 8px 8px 0;
    padding: 12px 20px;
    margin-bottom: 18px;
    display: flex;
    align-items: center;
    gap: 20px;
}}
.co-name {{ color: {C['t1']}; font-size: 18px; font-weight: 700; }}
.co-tag  {{
    background: {rgba(C['blue'], 0.12)};
    color: {C['blue_l']};
    font-size: 11px;
    font-weight: 500;
    padding: 3px 10px;
    border-radius: 99px;
    border: 1px solid {rgba(C['blue'], 0.3)};
}}

/* ── Metric cards ───────────────────────────────────────────────────────── */
.mc {{
    background: {C['surf']};
    border: 1px solid {C['brd']};
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 8px;
    transition: border-color 0.15s, background 0.15s;
    min-height: 74px;
}}
.mc:hover {{ border-color: {C['brd2']}; background: {C['surf2']}; }}
.mc-lbl {{
    color: {C['t3']};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    margin-bottom: 7px;
}}
.mc-val {{ font-size: 19px; font-weight: 700; color: {C['t1']}; line-height: 1; }}
.mc-val.pos {{ color: {C['green']}; }}
.mc-val.neg {{ color: {C['red']}; }}
.mc-val.blu {{ color: {C['blue_l']}; }}
.mc-val.yel {{ color: {C['yellow']}; }}
.mc-val.nd  {{ color: {C['t3']}; font-size: 14px; font-weight: 400; }}
.mc-sub {{ color: {C['t3']}; font-size: 11px; margin-top: 4px; }}

/* ── Section titles ─────────────────────────────────────────────────────── */
.sec {{
    color: {C['t2']};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    border-bottom: 1px solid {C['brd']};
    padding-bottom: 6px;
    margin-top: 22px;
    margin-bottom: 12px;
}}

/* ── Alert boxes ────────────────────────────────────────────────────────── */
.box-info {{
    background: {rgba(C['blue'], 0.07)};
    border: 1px solid {rgba(C['blue'], 0.25)};
    border-radius: 8px;
    padding: 11px 16px;
    margin: 8px 0;
    font-size: 13px;
    color: {C['t2']};
    line-height: 1.7;
}}
.box-warn {{
    background: {rgba(C['yellow'], 0.07)};
    border: 1px solid {rgba(C['yellow'], 0.3)};
    border-radius: 8px;
    padding: 11px 16px;
    margin: 8px 0;
    font-size: 13px;
    color: {C['t2']};
    line-height: 1.7;
}}
.box-ok {{
    background: {rgba(C['green'], 0.07)};
    border: 1px solid {rgba(C['green'], 0.3)};
    border-radius: 8px;
    padding: 11px 16px;
    margin: 8px 0;
    font-size: 13px;
    color: {C['t2']};
    line-height: 1.7;
}}
.box-err {{
    background: {rgba(C['red'], 0.07)};
    border: 1px solid {rgba(C['red'], 0.3)};
    border-radius: 8px;
    padding: 11px 16px;
    margin: 8px 0;
    font-size: 13px;
    color: {C['t2']};
    line-height: 1.7;
}}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    background: {C['bg']} !important;
    border-bottom: 1px solid {C['brd']} !important;
    gap: 0 !important;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent !important;
    color: {C['t3']} !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    letter-spacing: 1.2px !important;
    text-transform: uppercase !important;
    padding: 10px 18px !important;
    border-bottom: 2px solid transparent !important;
    transition: color 0.15s !important;
}}
.stTabs [data-baseweb="tab"]:hover {{
    color: {C['t2']} !important;
    background: {rgba(C['blue'], 0.04)} !important;
}}
.stTabs [aria-selected="true"] {{
    color: {C['blue_l']} !important;
    border-bottom: 2px solid {C['blue']} !important;
    background: {rgba(C['blue'], 0.06)} !important;
}}

/* ── DataFrames ─────────────────────────────────────────────────────────── */
.stDataFrame {{ background: {C['surf']} !important; border-radius: 8px; overflow: hidden; }}
.stDataFrame [data-testid="stDataFrameGlideDataEditor"] {{ background: {C['surf']} !important; }}
thead tr th {{
    background: {C['surf2']} !important;
    color: {C['t2']} !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    letter-spacing: 1px !important;
    text-transform: uppercase !important;
    border-bottom: 1px solid {C['brd2']} !important;
    padding: 10px 12px !important;
}}
tbody tr td {{
    background: {C['surf']} !important;
    color: {C['t1']} !important;
    font-size: 12px !important;
    border-bottom: 1px solid {C['brd']} !important;
    padding: 9px 12px !important;
}}
tbody tr:hover td {{ background: {C['surf2']} !important; }}

/* ── Inputs ─────────────────────────────────────────────────────────────── */
.stTextInput input, .stNumberInput input {{
    background: {C['surf']} !important;
    border: 1px solid {C['brd2']} !important;
    color: {C['t1']} !important;
    border-radius: 6px !important;
    font-size: 13px !important;
}}
.stTextInput input:focus, .stNumberInput input:focus {{
    border-color: {C['blue']} !important;
    box-shadow: 0 0 0 3px {rgba(C['blue'], 0.15)} !important;
}}
.stSelectbox > div > div {{
    background: {C['surf']} !important;
    border: 1px solid {C['brd2']} !important;
    color: {C['t1']} !important;
    border-radius: 6px !important;
}}

/* ── Sliders ────────────────────────────────────────────────────────────── */
.stSlider [data-baseweb="slider"] > div:first-child {{
    background: {C['brd2']} !important;
}}
[data-testid="stThumbValue"] {{ color: {C['t2']} !important; font-size: 11px !important; }}

/* ── Buttons ────────────────────────────────────────────────────────────── */
.stButton > button {{
    background: {C['blue']} !important;
    color: #fff !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-size: 12px !important;
    letter-spacing: 0.5px !important;
    padding: 8px 22px !important;
    transition: background 0.15s !important;
}}
.stButton > button:hover {{ background: {C['blue_l']} !important; color: {C['bg']} !important; }}

/* ── Radio / Checkbox ───────────────────────────────────────────────────── */
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label {{
    color: {C['t2']} !important;
    font-size: 13px !important;
}}

/* ── Expander ───────────────────────────────────────────────────────────── */
.streamlit-expanderHeader {{
    background: {C['surf']} !important;
    color: {C['t2']} !important;
    border: 1px solid {C['brd']} !important;
    border-radius: 6px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
}}

/* ── Health score bars ──────────────────────────────────────────────────── */
.score-row {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
    padding: 8px 12px;
    background: {C['surf']};
    border-radius: 6px;
    border: 1px solid {C['brd']};
}}
.score-lbl {{ color: {C['t3']}; font-size: 11px; width: 180px; flex-shrink: 0; }}
.score-bar-bg {{
    flex: 1;
    background: {C['brd2']};
    border-radius: 4px;
    height: 7px;
    overflow: hidden;
}}
.score-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.4s; }}
.score-val {{ color: {C['t1']}; font-size: 13px; font-weight: 600; width: 70px; text-align: right; }}
.score-status {{ font-size: 11px; width: 60px; text-align: right; }}
.s-ok   {{ color: {C['green']}; }}
.s-warn {{ color: {C['yellow']}; }}
.s-err  {{ color: {C['red']}; }}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Plotly layout base
# ─────────────────────────────────────────────────────────────────────────────

_PL = dict(
    paper_bgcolor=C["bg"],
    plot_bgcolor=C["surf"],
    font=dict(family="Inter, Segoe UI, sans-serif", color=C["t2"], size=11),
    title_font=dict(color=C["t1"], size=13, family="Inter, Segoe UI, sans-serif"),
    xaxis=dict(gridcolor=C["brd"], linecolor=C["brd2"],
               tickfont=dict(color=C["t3"], size=10), showgrid=True, zeroline=False),
    yaxis=dict(gridcolor=C["brd"], linecolor=C["brd2"],
               tickfont=dict(color=C["t3"], size=10), showgrid=True, zeroline=False),
    legend=dict(bgcolor=C["surf2"], bordercolor=C["brd"], borderwidth=1,
                font=dict(color=C["t2"], size=10)),
    margin=dict(l=55, r=20, t=45, b=45),
    hovermode="x unified",
    hoverlabel=dict(bgcolor=C["surf2"], font=dict(color=C["t1"], size=12), bordercolor=C["brd2"]),
)

_SER = [C["blue"], C["green"], C["red"], C["cyan"], C["purple"], C["yellow"], C["teal"]]


def _bar(years, values, name="", color=None, title="", sfx="B"):
    color = color or C["blue"]
    vals = [v if v is not None else 0 for v in values]
    bar_c = [C["red"] if v < 0 else color for v in vals]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=years, y=vals, name=name, marker_color=bar_c,
        text=[f"{v:.1f}{sfx}" for v in vals],
        textposition="outside", textfont=dict(color=C["t3"], size=9),
    ))
    fig.update_layout(**_PL, title=title, showlegend=False)
    return fig


def _lines(years, series, title=""):
    """series: [(name, values, color), ...]"""
    fig = go.Figure()
    for name, vals, col in series:
        fig.add_trace(go.Scatter(
            x=years, y=[v if v is not None else None for v in vals],
            name=name, mode="lines+markers",
            line=dict(color=col, width=2.5),
            marker=dict(color=col, size=5, symbol="circle"),
            connectgaps=False,
        ))
    fig.update_layout(**_PL, title=title)
    return fig


def _gauge(value, max_val, title, invert=False):
    """Gauge: invert=True → baixo é bom (dívida), False → alto é bom (liquidez)."""
    val = min(max(value or 0, 0), max_val)
    thirds = max_val / 3

    if invert:
        # baixo é verde, alto é vermelho
        steps = [
            dict(range=[0, thirds],       color=rgba(C["green"], 0.15)),
            dict(range=[thirds, 2*thirds], color=rgba(C["yellow"], 0.12)),
            dict(range=[2*thirds, max_val],color=rgba(C["red"], 0.15)),
        ]
    else:
        # alto é verde, baixo é vermelho
        steps = [
            dict(range=[0, thirds],        color=rgba(C["red"], 0.15)),
            dict(range=[thirds, 2*thirds],  color=rgba(C["yellow"], 0.12)),
            dict(range=[2*thirds, max_val], color=rgba(C["green"], 0.15)),
        ]

    bar_color = C["green"] if (val < thirds and invert) or (val > 2*thirds and not invert) \
               else C["yellow"] if val < 2*thirds \
               else C["red"]

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=val,
        title={"text": title, "font": {"color": C["t2"], "size": 11, "family": "Inter"}},
        number={"font": {"color": C["t1"], "size": 22}, "suffix": "x"},
        gauge={
            "axis": {"range": [0, max_val], "tickcolor": C["t3"],
                     "tickfont": {"color": C["t3"], "size": 9}},
            "bar": {"color": bar_color, "thickness": 0.28},
            "bgcolor": C["surf2"],
            "borderwidth": 1,
            "bordercolor": C["brd"],
            "steps": steps,
        },
    ))
    fig.update_layout(
        paper_bgcolor=C["bg"], plot_bgcolor=C["bg"],
        height=200, margin=dict(l=15, r=15, t=40, b=10),
        font=dict(color=C["t2"]),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Formatação
# ─────────────────────────────────────────────────────────────────────────────

def _f(v):
    if v is None: return None
    try:
        x = float(v); return None if x != x else x
    except: return None


def fbrl(v, scale=1e6, sfx="M"):
    x = _f(v)
    return "–" if x is None else f"R$ {x/scale:,.0f}{sfx}"


def fpct(v, d=2):
    x = _f(v)
    return "–" if x is None else f"{x*100:.{d}f}%"


def fmult(v, d=1):
    x = _f(v)
    return "–" if x is None else f"{x:.{d}f}×"


def fnum(v, d=2, sfx=""):
    x = _f(v)
    return "–" if x is None else f"{x:,.{d}f}{sfx}"


def _cls(v, pos_good=True):
    x = _f(v)
    if x is None: return "nd"
    if x > 0: return "pos" if pos_good else "neg"
    if x < 0: return "neg" if pos_good else "pos"
    return "blu"


# ─────────────────────────────────────────────────────────────────────────────
# UI helpers
# ─────────────────────────────────────────────────────────────────────────────

def mc(label, val, cls="", sub=""):
    sub_html = f'<div class="mc-sub">{sub}</div>' if sub else ""
    return f"""<div class="mc">
  <div class="mc-lbl">{label}</div>
  <div class="mc-val {cls}">{val}</div>
  {sub_html}
</div>"""


def sec(title):
    st.markdown(f'<div class="sec">{title}</div>', unsafe_allow_html=True)


def box(text, kind="info"):
    st.markdown(f'<div class="box-{kind}">{text}</div>', unsafe_allow_html=True)


def score_row(label, value_str, pct_fill, color, status_str):
    """Linha de saúde financeira com barra de progresso."""
    st.markdown(f"""
<div class="score-row">
  <div class="score-lbl">{label}</div>
  <div class="score-bar-bg">
    <div class="score-bar-fill" style="width:{min(pct_fill,100):.0f}%;background:{color}"></div>
  </div>
  <div class="score-val">{value_str}</div>
  <div class="score-status s-{'ok' if color==C['green'] else 'warn' if color==C['yellow'] else 'err'}">{status_str}</div>
</div>""", unsafe_allow_html=True)


def header():
    st.markdown(f"""
<div class="trm-header">
  <div class="trm-badge">EPS</div>
  <div>
    <div class="trm-title">Value Terminal</div>
    <div class="trm-sub">Análise Fundamentalista · CVM Open Data · B3 · Brasil · {datetime.now().strftime('%d/%m/%Y')}</div>
  </div>
</div>""", unsafe_allow_html=True)


def co_strip(name, cd_cvm, tipo_doc, setor="", brapi_data=None, ticker=""):
    tags = "".join([
        f'<span class="co-tag">CD_CVM {cd_cvm}</span>',
        f'<span class="co-tag">{tipo_doc}</span>',
        f'<span class="co-tag">{setor}</span>' if setor else "",
    ])
    price_html = ""
    if brapi_data:
        preco = brapi_data.get("regularMarketPrice", 0)
        var_d = brapi_data.get("regularMarketChangePercent", 0)
        cor_v = C["green"] if var_d >= 0 else C["red"]
        sinal = "▲" if var_d >= 0 else "▼"
        price_html = (
            f'<div style="margin-left:auto;text-align:right;padding-left:24px">'
            f'<div style="color:{C["t3"]};font-size:10px;letter-spacing:1.5px;margin-bottom:2px">'
            f'{ticker.upper()}</div>'
            f'<div style="color:{C["t1"]};font-size:26px;font-weight:700;line-height:1">'
            f'R$ {preco:.2f}</div>'
            f'<div style="color:{cor_v};font-size:12px;margin-top:4px">'
            f'{sinal} {abs(var_d):.2f}% hoje</div>'
            f'</div>'
        )
    st.markdown(f"""
<div class="co-strip" style="display:flex;align-items:center;justify-content:space-between">
  <div>
    <div class="co-name">{name}</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:4px">{tags}</div>
  </div>
  {price_html}
</div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Cache / data loading
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=180)
def _registry():
    return load_company_registry()


@st.cache_data(ttl=120)
def _avail():
    return {
        f"{t}_{s}": get_processed_path(s.lower(), t.lower(), "parquet").exists()
        for t in TIPOS_DOC for s in DEMONSTRATIVOS
    }


@st.cache_data(ttl=60)
def _snap(cd, tipo):
    return build_company_snapshot(cd, tipo_doc=tipo)


@st.cache_data(ttl=3600, show_spinner=False)
def _capital_social() -> pd.DataFrame:
    """Carrega capital_social.csv — total de ações por empresa (Capital Emitido)."""
    p = Path(__file__).resolve().parent / "data" / "processed" / "capital_social.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, sep=";", encoding="latin1")
    df = df[df["Tipo_Capital"] == "Capital Emitido"].copy()
    return df[["CNPJ_Companhia", "Quantidade_Total_Acoes",
               "Quantidade_Acoes_Ordinarias", "Quantidade_Acoes_Preferenciais"]].reset_index(drop=True)


def _shares_for_cvm(cd_cvm: str) -> Optional[float]:
    """Retorna total de ações em milhões para um CD_CVM (via capital_social.csv)."""
    try:
        cad = _registry()
        if cad.empty:
            return None
        row = cad[cad["CD_CVM"].astype(str).str.strip() == str(cd_cvm).strip()]
        if row.empty:
            return None
        cnpj = row.iloc[0]["CNPJ_CIA"]
        cap = _capital_social()
        if cap.empty:
            return None
        match = cap[cap["CNPJ_Companhia"] == cnpj]
        if match.empty:
            return None
        total = float(match.iloc[0]["Quantidade_Total_Acoes"])
        return total / 1e6
    except Exception:
        return None


@st.cache_data(ttl=60)
def _stmt(stmt, tipo):
    return load_processed_statement(stmt, tipo)


@st.cache_data(ttl=60)
def _ext_snap(cd, tipo):
    """Snapshot estendido com campos adicionais para saúde financeira."""
    snap = _snap(cd, tipo)

    dre = _stmt("DRE", tipo)
    bpa = _stmt("BPA", tipo)
    bpp = _stmt("BPP", tipo)
    dfc = _stmt("DFC_MI", tipo)

    def pick(df, *kws):
        if df.empty or "CD_CVM" not in df.columns: return None
        s = df[df["CD_CVM"].astype(str).str.strip() == cd].copy()
        if s.empty: return None
        vc = "VL_CONTA_AJUSTADO" if "VL_CONTA_AJUSTADO" in s.columns else "VL_CONTA"
        if "DT_REFER" in s.columns:
            s = s[s["DT_REFER"] == s["DT_REFER"].max()]
        if "DS_CONTA" not in s.columns or vc not in s.columns: return None
        ds = s["DS_CONTA"].fillna("").str.upper()
        for kw in kws:
            m = ds.str.contains(kw.upper(), regex=False, na=False)
            if m.any():
                s2 = s[m]
                if "CD_CONTA" in s2.columns:
                    s2 = s2.assign(_l=s2["CD_CONTA"].astype(str).str.count(r"\.")
                                   ).sort_values("_l")
                v = s2[vc].dropna()
                if not v.empty: return float(v.iloc[0])
        return None

    snap["ativo_circulante"]  = pick(bpa, "ativo circulante")
    snap["passivo_circulante"]= pick(bpp, "passivo circulante")
    snap["estoques"]          = pick(bpa, "estoques", "inventário")
    snap["desp_financeiras"]  = pick(dre, "despesas financeiras", "resultado financeiro",
                                     "receitas e despesas financeiras",
                                     "resultado financeiro líquido")
    snap["depreciacao"]       = pick(dfc, "depreciação", "amortização",
                                     "depreciação, amortização e exaustão",
                                     "depreciação e amortização")
    snap["divida_cp"]         = pick(bpp, "empréstimos e financiamentos",
                                     "debêntures", "debentures")
    snap["divida_lp"]         = pick(bpp, "empréstimos e financiamentos de longo prazo")
    return snap


@st.cache_data(ttl=60)
def _history(cd, tipo):
    """Série histórica anual de métricas principais."""
    dre = _stmt("DRE", tipo)
    bpa = _stmt("BPA", tipo)
    bpp = _stmt("BPP", tipo)
    dfc = _stmt("DFC_MI", tipo)

    def flt(df):
        if df.empty or "CD_CVM" not in df.columns: return pd.DataFrame()
        s = df[df["CD_CVM"].astype(str).str.strip() == cd].copy()
        if not s.empty and "ANO_REFER" not in s.columns and "DT_FIM_EXERC" in s.columns:
            s["ANO_REFER"] = pd.to_datetime(s["DT_FIM_EXERC"], errors="coerce").dt.year
        return s

    d, b, p, f = flt(dre), flt(bpa), flt(bpp), flt(dfc)
    if d.empty or "ANO_REFER" not in d.columns: return pd.DataFrame()
    years = sorted(d["ANO_REFER"].dropna().unique())

    def pick(df, yr, *kws):
        if df.empty or "ANO_REFER" not in df.columns: return None
        s = df[df["ANO_REFER"] == yr]
        if s.empty: return None
        vc = "VL_CONTA_AJUSTADO" if "VL_CONTA_AJUSTADO" in s.columns else "VL_CONTA"
        if "DS_CONTA" not in s.columns or vc not in s.columns: return None
        ds = s["DS_CONTA"].fillna("").str.upper()
        for kw in kws:
            m = ds.str.contains(kw.upper(), regex=False, na=False)
            if m.any():
                s2 = s[m]
                if "CD_CONTA" in s2.columns:
                    s2 = s2.assign(_l=s2["CD_CONTA"].astype(str).str.count(r"\.")
                                   ).sort_values("_l")
                v = s2[vc].dropna()
                if not v.empty: return float(v.iloc[0])
        return None

    rows = []
    for y in years:
        da = pick(f, y, "depreciação", "amortização", "depreciação e amortização")
        eb = pick(d, y, "resultado antes do resultado financeiro", "resultado antes dos tributos sobre o lucro", "resultado operacional", "lucro operacional", "ebit")
        ebitda = (eb + abs(da)) if eb is not None and da is not None else None
        rows.append({
            "ano":         int(y),
            "receita":     pick(d, y, "receita líquida", "receita de venda"),
            "lucro_bruto": pick(d, y, "lucro bruto"),
            "ebit":        eb,
            "ebitda":      ebitda,
            "lucro_liq":   pick(d, y, "lucro/prejuízo consolidado do período", "resultado líquido das operações continuadas", "lucro/prejuízo do período", "lucro líquido", "resultado líquido"),
            "fcop":        pick(f, y, "caixa líquido atividades operacionais", "caixa gerado", "caixa líquido nas atividades operacionais", "fluxo de caixa das atividades operacionais", "atividades operacionais"),
            "depamort":    da,
            "ativo":       pick(b, y, "ativo total"),
            "pl":          pick(p, y, "patrimônio líquido"),
            "divida_cp":   pick(p, y, "empréstimos e financiamentos"),
            "divida_lp":   pick(p, y, "empréstimos e financiamentos de longo prazo"),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=300, show_spinner=False)
def _brapi_quote(ticker: str) -> Optional[Dict]:
    """Cotação BRAPI com cache de 5 minutos."""
    client = BrapiClient()
    return client.get_quote(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def _brapi_search(query: str) -> List[Dict]:
    """Busca tickers pelo nome da empresa, com cache de 1 hora."""
    try:
        client = BrapiClient()
        return client.search_ticker(query)
    except Exception:
        return []


_STOP_WORDS = {"SA", "S.A", "S.A.", "DO", "DA", "DE", "DOS", "DAS", "E",
               "EM", "LTDA", "CIA", "COMPANHIA", "INDUSTRIAS", "INDUSTRIA",
               "GRUPO", "HOLDING", "PARTICIPACOES", "PARTICIPAÇÕES"}


def _auto_ticker_from_name(company_name: str) -> str:
    """Tenta encontrar o ticker B3 mais relevante dado o nome da empresa CVM."""
    words = [w.rstrip(".,/") for w in company_name.upper().split()]
    search_words = [w for w in words if len(w) >= 3 and w not in _STOP_WORDS]
    search_term = search_words[0] if search_words else company_name[:20]

    results = _brapi_search(search_term)
    if not results:
        return ""

    # Filtrar apenas ações (não FIIs/BDRs) e ordenar por volume
    stocks = [r for r in results
              if not str(r.get("stock", "")).endswith("11")   # exclui FIIs
              and not str(r.get("stock", "")).endswith("34")]  # exclui BDRs
    if not stocks:
        stocks = results

    # Preferir PN (terminam em 4) ou ON (terminam em 3)
    pn = [r for r in stocks if str(r.get("stock", "")).endswith("4")]
    on = [r for r in stocks if str(r.get("stock", "")).endswith("3")]
    best_list = pn or on or stocks

    return best_list[0].get("stock", "")


@st.cache_data(ttl=1800, show_spinner=False)
def _bcb_serie(code: int, n: int = 36) -> pd.DataFrame:
    """Busca série temporal do Banco Central (api.bcb.gov.br)."""
    try:
        import requests as _req
        url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}"
               f"/dados/ultimos/{n}?formato=json")
        r = _req.get(url, timeout=10)
        if r.status_code == 200:
            df = pd.DataFrame(r.json())
            df["data"]  = pd.to_datetime(df["data"], format="%d/%m/%Y")
            df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
            return df.dropna()
    except Exception:
        pass
    return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Tab renderers
# ─────────────────────────────────────────────────────────────────────────────

def _tab_overview(m, snap, brapi_data=None, ticker_input=""):
    if brapi_data and ticker_input:
        _render_brapi_panel(brapi_data, ticker_input.upper())
        st.markdown("---")
    sec("Resultado")
    c = st.columns(4)
    c[0].markdown(mc("Receita Líquida",  fbrl(m.get("receita_liquida")),  "blu"),  unsafe_allow_html=True)
    c[1].markdown(mc("Lucro Bruto",      fbrl(m.get("lucro_bruto")),      _cls(m.get("lucro_bruto"))),  unsafe_allow_html=True)
    c[2].markdown(mc("EBIT",             fbrl(m.get("ebit")),             _cls(m.get("ebit"))),  unsafe_allow_html=True)
    c[3].markdown(mc("Lucro Líquido",    fbrl(m.get("lucro_liquido")),    _cls(m.get("lucro_liquido"))), unsafe_allow_html=True)

    sec("Balanço")
    c2 = st.columns(4)
    c2[0].markdown(mc("Caixa + Aplicações", fbrl(m.get("caixa_total")),     "pos"),  unsafe_allow_html=True)
    c2[1].markdown(mc("Dívida Bruta",       fbrl(m.get("divida_bruta")),    _cls(m.get("divida_bruta"), False)), unsafe_allow_html=True)
    c2[2].markdown(mc("Dívida Líquida",     fbrl(m.get("divida_liquida")),  _cls(m.get("divida_liquida"), False)), unsafe_allow_html=True)
    c2[3].markdown(mc("Patrimônio Líquido", fbrl(m.get("patrimonio_liquido")), _cls(m.get("patrimonio_liquido"))), unsafe_allow_html=True)

    sec("Margens")
    c3 = st.columns(4)
    c3[0].markdown(mc("Margem Bruta",   fpct(m.get("margem_bruta")),   _cls(m.get("margem_bruta"))),  unsafe_allow_html=True)
    c3[1].markdown(mc("Margem EBIT",    fpct(m.get("margem_ebit")),    _cls(m.get("margem_ebit"))),   unsafe_allow_html=True)
    c3[2].markdown(mc("Margem Líquida", fpct(m.get("margem_liquida")), _cls(m.get("margem_liquida"))), unsafe_allow_html=True)
    c3[3].markdown(mc("Ativo Total",    fbrl(m.get("ativo_total")),    "blu"),  unsafe_allow_html=True)

    sec("Retornos & Fluxo de Caixa")
    c4 = st.columns(4)
    c4[0].markdown(mc("ROE",          fpct(m.get("roe")),       _cls(m.get("roe"))),  unsafe_allow_html=True)
    c4[1].markdown(mc("ROA",          fpct(m.get("roa")),       _cls(m.get("roa"))),  unsafe_allow_html=True)
    c4[2].markdown(mc("ROIC (aprox)", fpct(m.get("roic_aprox")),_cls(m.get("roic_aprox"))), unsafe_allow_html=True)
    fcop = m.get("fluxo_caixa_operacional"); fcl = m.get("fcl_aprox")
    c4[3].markdown(mc("FCOP / FCL",
                       f"{fbrl(fcop)}  /  {fbrl(fcl)}",
                       _cls(fcl)), unsafe_allow_html=True)


def _tab_history(cd, tipo, company):
    hist = _history(cd, tipo)
    if hist.empty:
        box("Dados históricos indisponíveis. Verifique se os arquivos parquet foram gerados.", "warn")
        return

    anos = hist["ano"].tolist()

    def b(col): return [(_f(v)/1e6 if _f(v) is not None else None) for v in hist[col]]

    # Resultado
    sec("Evolução do Resultado (R$ Bilhões)")
    fig1 = _lines(anos, [
        ("Receita Líquida", b("receita"),    C["blue"]),
        ("EBITDA",          b("ebitda"),     C["cyan"]),
        ("EBIT",            b("ebit"),       C["green"]),
        ("Lucro Líquido",   b("lucro_liq"),  C["purple"]),
    ], title=f"{company} — Resultado")
    st.plotly_chart(fig1, use_container_width=True)

    # FCOP
    fcop_vals = b("fcop")
    if any(v is not None for v in fcop_vals):
        sec("Fluxo de Caixa Operacional (R$ Bilhões)")
        fig2 = _bar(anos, fcop_vals, "FCOP", C["teal"],
                    f"{company} — FCOP", sfx="B")
        st.plotly_chart(fig2, use_container_width=True)

    # PL e Ativo
    pl_vals = b("pl"); at_vals = b("ativo")
    if any(v is not None for v in pl_vals):
        sec("Patrimônio e Ativo (R$ Bilhões)")
        fig3 = _lines(anos, [
            ("Patrimônio Líquido", pl_vals, C["yellow"]),
            ("Ativo Total",        at_vals, C["t2"]),
        ], title=f"{company} — Balanço")
        st.plotly_chart(fig3, use_container_width=True)

    # Tabela
    sec("Dados Anuais")
    disp = hist[["ano", "receita", "ebitda", "ebit", "lucro_liq", "fcop", "pl", "ativo"]].copy()
    for col in ["receita", "ebitda", "ebit", "lucro_liq", "fcop", "pl", "ativo"]:
        disp[col] = disp[col].apply(
            lambda x: f"R$ {x/1e6:,.0f}M" if pd.notna(x) and x != 0 else "–"
        )
    disp.columns = ["Ano", "Receita", "EBITDA", "EBIT", "Lucro Líq.", "FCOP", "PL", "Ativo"]
    st.dataframe(disp, use_container_width=True, hide_index=True)


def _stmt_table(df, cd, title, date_key):
    sec(title)
    if df.empty:
        box("Demonstrativo não disponível.", "warn"); return

    co = df[df["CD_CVM"].astype(str).str.strip() == cd].copy() if "CD_CVM" in df.columns else pd.DataFrame()
    if co.empty:
        box("Empresa não encontrada neste demonstrativo.", "warn"); return

    vc = "VL_CONTA_AJUSTADO" if "VL_CONTA_AJUSTADO" in co.columns else "VL_CONTA"

    if "DT_FIM_EXERC" in co.columns:
        datas = sorted(co["DT_FIM_EXERC"].unique(), reverse=True)[:8]
        sel = st.selectbox("Período:", datas, key=date_key)
        co = co[co["DT_FIM_EXERC"] == sel]

    cols = [c for c in ["CD_CONTA", "DS_CONTA", vc] if c in co.columns]
    disp = co[cols].copy()
    if vc in disp.columns:
        disp[vc] = disp[vc].apply(lambda x: f"R$ {x/1e6:,.2f} M" if pd.notna(x) else "–")
        disp = disp.rename(columns={vc: "VALOR (R$ M)", "DS_CONTA": "CONTA"})

    st.dataframe(disp, use_container_width=True, hide_index=True, height=440)


def _tab_statements(cd, tipo):
    sub1, sub2, sub3, sub4 = st.tabs(["DRE", "ATIVO (BPA)", "PASSIVO + PL (BPP)", "FLUXO DE CAIXA"])
    with sub1: _stmt_table(_stmt("DRE",    tipo), cd, "Demonstração do Resultado do Exercício", "dt_dre")
    with sub2: _stmt_table(_stmt("BPA",    tipo), cd, "Balanço Patrimonial — Ativo",             "dt_bpa")
    with sub3: _stmt_table(_stmt("BPP",    tipo), cd, "Balanço Patrimonial — Passivo + PL",       "dt_bpp")
    with sub4: _stmt_table(_stmt("DFC_MI", tipo), cd, "Demonstração do Fluxo de Caixa",           "dt_dfc")


def _tab_health(snap_ext, m, hist):
    """Aba de Saúde Financeira."""

    # ── Extrair campos ──────────────────────────────────────────────────────
    ebit   = _f(m.get("ebit"))
    da     = _f(snap_ext.get("depreciacao"))
    ebitda = (ebit + abs(da)) if ebit is not None and da is not None else None
    nd     = _f(snap_ext.get("divida_liquida"))
    divbruta = _f(snap_ext.get("divida_bruta"))
    pl     = _f(m.get("patrimonio_liquido"))
    ac     = _f(snap_ext.get("ativo_circulante"))
    pc     = _f(snap_ext.get("passivo_circulante"))
    est    = _f(snap_ext.get("estoques"))
    caixa  = _f(snap_ext.get("caixa_equivalentes")) or 0
    aplic  = _f(snap_ext.get("aplicacoes_financeiras")) or 0
    caixa_t = caixa + aplic or None
    dfinanc = _f(snap_ext.get("desp_financeiras"))
    fcop   = _f(m.get("fluxo_caixa_operacional"))
    divcp  = _f(snap_ext.get("divida_cp"))
    divlp  = _f(snap_ext.get("divida_lp"))

    # ── Indicadores calculados ──────────────────────────────────────────────
    nd_ebitda    = (nd / ebitda) if nd is not None and ebitda and ebitda > 0 else None
    div_pl       = (divbruta / abs(pl)) if divbruta and pl and pl != 0 else None
    cob_juros    = (ebit / abs(dfinanc)) if ebit and dfinanc and dfinanc != 0 else None
    liq_corrente = (ac / pc) if ac and pc and pc > 0 else None
    liq_seca     = ((ac - abs(est or 0)) / pc) if ac and pc and pc > 0 else None
    liq_imediata = ((caixa_t or 0) / pc) if pc and pc > 0 else None
    anos_pagar   = (nd / fcop) if nd and nd > 0 and fcop and fcop > 0 else None
    duration_ap  = None
    if divcp is not None and divlp is not None and (divcp + divlp) > 0:
        duration_ap = (divcp * 0.5 + divlp * 3.0) / (divcp + divlp)

    # ── Layout ──────────────────────────────────────────────────────────────
    col_lev, col_liq = st.columns(2)

    with col_lev:
        sec("Alavancagem e Cobertura")

        # Gauge ND/EBITDA
        g1_val = nd_ebitda if nd_ebitda is not None and nd_ebitda > 0 else 0
        st.plotly_chart(_gauge(g1_val, 10, "Dívida Líquida / EBITDA", invert=True),
                        use_container_width=True)

        def _lev_bar(lbl, val, low_good, thr_ok, thr_warn, val_str, sfx="×"):
            if val is None:
                score_row(lbl, "N/D", 0, C["t3"], "–"); return
            if low_good:
                pct  = min(val / max(thr_warn * 1.5, 0.01) * 100, 100)
                col  = C["green"] if val < thr_ok else C["yellow"] if val < thr_warn else C["red"]
                stat = "✓ OK" if val < thr_ok else "△ Alt" if val < thr_warn else "✗ Alto"
            else:
                pct  = min(val / max(thr_warn * 1.5, 0.01) * 100, 100)
                col  = C["green"] if val > thr_ok else C["yellow"] if val > thr_warn else C["red"]
                stat = "✓ OK" if val > thr_ok else "△ Baixo" if val > thr_warn else "✗ Baixo"
            score_row(lbl, val_str, pct, col, stat)

        _lev_bar("Dívida Líquida / EBITDA", nd_ebitda, True,  2.0, 4.0,
                 fmult(nd_ebitda))
        _lev_bar("Dívida Bruta / PL",       div_pl,    True,  1.0, 2.5,
                 fmult(div_pl))
        _lev_bar("Cobertura de Juros (×)",  cob_juros, False, 3.0, 1.5,
                 fmult(cob_juros))

        sec("Métricas de Dívida")
        dm1, dm2, dm3 = st.columns(3)
        dm1.markdown(mc("Dívida Líq./EBITDA", fmult(nd_ebitda),   _cls(nd_ebitda, False) if nd_ebitda else "nd"), unsafe_allow_html=True)
        dm2.markdown(mc("Duration (aprox)",   f"{duration_ap:.1f} anos" if duration_ap else "–", "blu"), unsafe_allow_html=True)
        dm3.markdown(mc("Anos p/ Quitar¹",    f"{anos_pagar:.1f} anos" if anos_pagar else "–",
                        "pos" if anos_pagar and anos_pagar < 5 else "yel" if anos_pagar and anos_pagar < 10 else "neg"), unsafe_allow_html=True)

        st.caption("¹ Net Debt / FCOP — à taxa atual de geração de caixa operacional")

    with col_liq:
        sec("Liquidez")

        g2_val = liq_corrente if liq_corrente is not None else 0
        st.plotly_chart(_gauge(min(g2_val, 4), 4, "Liquidez Corrente", invert=False),
                        use_container_width=True)

        def _liq_bar(lbl, val, thr_ok, thr_warn, val_str):
            if val is None:
                score_row(lbl, "N/D", 0, C["t3"], "–"); return
            pct  = min(val / (thr_ok * 1.5) * 100, 100)
            col  = C["green"] if val >= thr_ok else C["yellow"] if val >= thr_warn else C["red"]
            stat = "✓ OK" if val >= thr_ok else "△ Baixa" if val >= thr_warn else "✗ Baixa"
            score_row(lbl, val_str, pct, col, stat)

        _liq_bar("Liquidez Corrente  (AC/PC)",       liq_corrente, 2.0, 1.0, fmult(liq_corrente, 2))
        _liq_bar("Liquidez Seca  (AC-Est)/PC",        liq_seca,     1.5, 0.8, fmult(liq_seca, 2))
        _liq_bar("Liquidez Imediata  Caixa/PC",       liq_imediata, 0.5, 0.2, fmult(liq_imediata, 2))

        sec("Capital de Giro & Dados")
        cg1, cg2, cg3 = st.columns(3)
        ncg = (ac - pc) if ac and pc else None
        cg1.markdown(mc("Ativo Circulante",  fbrl(ac), "blu"), unsafe_allow_html=True)
        cg2.markdown(mc("Passivo Circulante",fbrl(pc), _cls(pc, False) if pc else "nd"), unsafe_allow_html=True)
        cg3.markdown(mc("Capital de Giro",   fbrl(ncg), _cls(ncg)), unsafe_allow_html=True)

    # ── Estrutura da dívida ─────────────────────────────────────────────────
    sec("Estrutura da Dívida")
    col_struct, col_idx = st.columns(2)

    with col_struct:
        if divcp is not None or divlp is not None:
            cp_val = abs(divcp or 0)
            lp_val = abs(divlp or 0)
            total  = cp_val + lp_val
            if total > 0:
                fig_pie = go.Figure(go.Pie(
                    labels=["Curto Prazo (< 1 ano)", "Longo Prazo (> 1 ano)"],
                    values=[cp_val, lp_val],
                    marker_colors=[C["yellow"], C["blue"]],
                    hole=0.45,
                    textfont=dict(color=C["t1"], size=11),
                    insidetextfont=dict(color=C["t1"]),
                ))
                fig_pie.update_layout(
                    **{k: v for k, v in _PL.items() if k not in ["xaxis", "yaxis", "legend", "margin", "hovermode"]},
                    title="CP vs LP",
                    height=260,
                    showlegend=True,
                    legend=dict(font=dict(color=C["t2"], size=11),
                                bgcolor=C["surf2"], bordercolor=C["brd"]),
                    margin=dict(l=10, r=10, t=40, b=10),
                )
                st.plotly_chart(fig_pie, use_container_width=True)

                cp_pct = cp_val / total * 100
                lp_pct = lp_val / total * 100
                st.caption(f"CP: **{fbrl(cp_val)}** ({cp_pct:.0f}%) | "
                           f"LP: **{fbrl(lp_val)}** ({lp_pct:.0f}%) | "
                           f"Duration aprox: **{f'{duration_ap:.1f} anos' if duration_ap else '–'}**")
        else:
            box("Estrutura de dívida CP/LP não encontrada nos dados processados.", "warn")

    with col_idx:
        sec("Indexadores da Dívida (entrada manual)")
        box("Os indexadores (CDI, IPCA, prefixado, USD) constam nas notas explicativas. "
            "Informe abaixo para gerar o gráfico de composição.", "info")

        tot = 100.0
        pct_cdi   = st.number_input("% CDI",        0.0, 100.0, 50.0, 5.0, key="idx_cdi")
        pct_ipca  = st.number_input("% IPCA",       0.0, 100.0, 20.0, 5.0, key="idx_ipca")
        pct_pre   = st.number_input("% Prefixado",  0.0, 100.0, 15.0, 5.0, key="idx_pre")
        pct_usd   = st.number_input("% USD/FX",     0.0, 100.0, 10.0, 5.0, key="idx_usd")
        pct_outro = max(0, 100 - pct_cdi - pct_ipca - pct_pre - pct_usd)
        st.caption(f"Outros: {pct_outro:.0f}%")

        if sum([pct_cdi, pct_ipca, pct_pre, pct_usd, pct_outro]) > 0:
            fig_idx = go.Figure(go.Pie(
                labels=["CDI", "IPCA", "Prefixado", "USD/FX", "Outros"],
                values=[pct_cdi, pct_ipca, pct_pre, pct_usd, pct_outro],
                marker_colors=[C["blue"], C["green"], C["cyan"], C["purple"], C["t3"]],
                hole=0.45,
                textfont=dict(color=C["t1"], size=11),
            ))
            fig_idx.update_layout(
                **{k: v for k, v in _PL.items() if k not in ["xaxis", "yaxis", "legend", "margin", "hovermode"]},
                title="Composição dos Indexadores",
                height=260,
                showlegend=True,
                legend=dict(font=dict(color=C["t2"], size=11),
                            bgcolor=C["surf2"], bordercolor=C["brd"]),
                margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig_idx, use_container_width=True)

    # ── Histórico de alavancagem ────────────────────────────────────────────
    if not hist.empty and "ebitda" in hist.columns and "divida_cp" in hist.columns:
        sec("Histórico de Alavancagem")

        def _nd_hist(row):
            divcp = abs(_f(row.get("divida_cp")) or 0)
            divlp = abs(_f(row.get("divida_lp")) or 0)
            return divcp + divlp

        anos_h = hist["ano"].tolist()
        nd_vals  = [_nd_hist(r) / 1e6 for _, r in hist.iterrows()]
        ebd_vals = [(_f(r.get("ebitda")) or 0) / 1e6 for _, r in hist.iterrows()]

        fig_lev = _lines(anos_h, [
            ("Dívida Bruta Aprox.", nd_vals,  C["red"]),
            ("EBITDA",             ebd_vals, C["green"]),
        ], title="Evolução: Dívida vs EBITDA (R$ Bilhões)")
        st.plotly_chart(fig_lev, use_container_width=True)


def _tab_valuation(m, snap_ext, cd, hist, brapi_data=None):
    """Aba de Valuation: WACC + Múltiplos + EPV + DCF."""

    ebit   = _f(m.get("ebit"))
    da     = _f(snap_ext.get("depreciacao"))
    ebitda = (ebit + abs(da)) if ebit is not None and da is not None else None
    nd     = _f(snap_ext.get("divida_liquida"))
    pl     = _f(m.get("patrimonio_liquido"))
    receita= _f(m.get("receita_liquida"))
    lucro  = _f(m.get("lucro_liquido"))
    fcl    = _f(m.get("fcl_aprox"))

    # Placeholder para o painel de resumo no topo (preenchido após cálculos)
    _top_summary = st.empty()
    st.markdown("---")

    # ── SEÇÃO 1: WACC Calculator ────────────────────────────────────────────
    with st.expander("🧮  WACC — Custo Médio Ponderado de Capital (CAPM)", expanded=True):
        box("O WACC é a taxa de desconto usada no DCF. Ajuste os parâmetros abaixo para o contexto brasileiro.", "info")
        w1, w2 = st.columns(2)

        with w1:
            st.markdown("**Custo do Capital Próprio (Ke) — CAPM**")
            rf     = st.slider("Rf — Risk-free (SELIC/CDI) %", 5.0, 18.0, 10.5, 0.25,
                               key="w_rf", help="Taxa Selic atual ou NTN-B longa")
            beta   = st.slider("Beta (β)",  0.3, 2.5, 1.0, 0.05, key="w_beta",
                               help="Beta da empresa versus Ibovespa")
            erp    = st.slider("ERP — Prêmio de Risco de Mercado %", 3.0, 9.0, 5.5, 0.25,
                               key="w_erp", help="Damodaran: ~5.5% para Brasil")
            crp    = st.slider("CRP — Risco País %", 0.0, 6.0, 2.5, 0.25,
                               key="w_crp", help="Brazil CDS spread / 100")
            ke_pct = rf + beta * (erp + crp)
            st.markdown(f"**Ke = {rf:.2f}% + {beta:.2f}×({erp:.2f}%+{crp:.2f}%) = `{ke_pct:.2f}%`**")

        with w2:
            st.markdown("**Custo da Dívida (Kd) e Estrutura de Capital**")
            kd_pct = st.slider("Kd — Custo da dívida bruta %", 5.0, 22.0, 14.0, 0.25, key="w_kd")
            t_rate = st.slider("Alíquota efetiva (IR + CSLL) %", 15.0, 40.0, 34.0, 1.0, key="w_t")
            e_pct  = st.slider("% Equity (E/(E+D))", 10.0, 95.0, 60.0, 5.0, key="w_e",
                               help="Participação do capital próprio no capital total")
            d_pct  = 100.0 - e_pct
            kd_at  = kd_pct * (1 - t_rate / 100)
            wacc_pct = ke_pct * (e_pct / 100) + kd_at * (d_pct / 100)

            st.markdown(f"**Kd após IR = {kd_pct:.2f}%×(1−{t_rate:.0f}%) = `{kd_at:.2f}%`**")
            st.markdown(f"**WACC = {ke_pct:.2f}%×{e_pct:.0f}% + {kd_at:.2f}%×{d_pct:.0f}% = `{wacc_pct:.2f}%`**")

        wacc = wacc_pct / 100.0

        w_cols = st.columns(4)
        w_cols[0].markdown(mc("Ke (Custo Equity)",   f"{ke_pct:.2f}%",   "blu"), unsafe_allow_html=True)
        w_cols[1].markdown(mc("Kd (após IR)",         f"{kd_at:.2f}%",   "yel"), unsafe_allow_html=True)
        w_cols[2].markdown(mc("WACC Calculado",       f"{wacc_pct:.2f}%","pos"), unsafe_allow_html=True)
        w_cols[3].markdown(mc("WACC Manual (override)", "ver abaixo",    "nd"),  unsafe_allow_html=True)

        wacc_manual = st.number_input("Ou informe WACC diretamente (%)  — sobrescreve o calculado",
                                      0.0, 30.0, round(wacc_pct, 2), 0.25, key="w_manual") / 100.0
        wacc_final = wacc_manual if wacc_manual > 0 else wacc

    st.markdown("---")

    # ── SEÇÃO 2: Múltiplos de Mercado ───────────────────────────────────────
    sec("Múltiplos de Mercado — Entrada de Preço e Ações")
    box("Informe o preço atual da ação e o total de ações para calcular os múltiplos. "
        "Fonte: B3, brapi.dev ou Yahoo Finance.", "info")

    # Ações: prioridade CSV capital_social > BRAPI > 0
    cvm_shares  = _shares_for_cvm(cd)
    brapi_preco = _f(brapi_data.get("regularMarketPrice")) if brapi_data else 0.0
    brapi_acoes = (_f(brapi_data.get("sharesOutstanding")) or 0) / 1e6 if brapi_data else 0.0
    acoes_default = cvm_shares or brapi_acoes or 0.0

    fonte_acoes = ""
    if cvm_shares:
        fonte_acoes = f"FRE CVM 2026: {cvm_shares:,.0f}M ações"
    elif brapi_acoes:
        fonte_acoes = f"BRAPI: {brapi_acoes:,.0f}M ações"

    if brapi_preco or cvm_shares:
        msg = f"✅ Dados preenchidos automaticamente —"
        if brapi_preco:
            msg += f" Preço R$ {brapi_preco:.2f} (BRAPI)"
        if fonte_acoes:
            msg += f"  |  {fonte_acoes}"
        box(msg, "ok")

    mv1, mv2 = st.columns(2)
    with mv1:
        preco  = st.number_input("Preço da ação (R$)", 0.0, 99999.0, brapi_preco, 0.01,
                                  key="mult_preco", format="%.2f")
        acoes  = st.number_input("Total de ações (milhões)", 0.0, 9999999.0, acoes_default, 10.0,
                                  key="mult_acoes")

    mktcap = preco * acoes * 1e6 if preco > 0 and acoes > 0 else None
    ev_mkt = (mktcap + (nd or 0)) if mktcap is not None else None

    mult_rows = [
        ("Market Cap",   fbrl(mktcap), "–"),
        ("Enterprise Value (EV)", fbrl(ev_mkt), "EV = Mkt Cap + Dívida Líquida"),
        ("P / Lucro (P/L)",      fmult(_f(mktcap)/_f(lucro) if mktcap and lucro and lucro>0 else None),
                                 "< 15× barato | 15-25× justo | > 25× caro"),
        ("P / Valor Patrimonial (P/VP)", fmult(_f(mktcap)/_f(pl) if mktcap and pl and pl>0 else None),
                                         "< 1× abaixo do book"),
        ("P / Receita (P/S)",    fmult(_f(mktcap)/_f(receita) if mktcap and receita and receita>0 else None),
                                 "Benchmarks por setor"),
        ("P / FCL",              fmult(_f(mktcap)/_f(fcl) if mktcap and fcl and fcl>0 else None),
                                 "< 15× interessante"),
        ("EV / EBITDA",          fmult(_f(ev_mkt)/_f(ebitda) if ev_mkt and ebitda and ebitda>0 else None),
                                 "< 8× value | 8-15× neutro | > 15× caro"),
        ("EV / EBIT",            fmult(_f(ev_mkt)/_f(ebit) if ev_mkt and ebit and ebit>0 else None),
                                 "–"),
        ("EV / FCL",             fmult(_f(ev_mkt)/_f(fcl) if ev_mkt and fcl and fcl>0 else None),
                                 "–"),
    ]

    with mv2:
        if mktcap:
            st.markdown(mc("Market Cap", fbrl(mktcap), "blu"), unsafe_allow_html=True)
            st.markdown(mc("EV",         fbrl(ev_mkt), "cyan"), unsafe_allow_html=True)

    sec("Tabela de Múltiplos")
    df_mult = pd.DataFrame(mult_rows, columns=["Múltiplo", "Valor", "Referência"])
    st.dataframe(df_mult, use_container_width=True, hide_index=True)

    # Histórico de múltiplos (P/L, EV/EBITDA) se tiver preço
    if mktcap and not hist.empty and "ebitda" in hist.columns:
        sec("Histórico EV/EBITDA Implícito (EBITDA real × EV atual)")
        anos_h = hist["ano"].tolist()
        ev_eb_hist = [
            _f(ev_mkt) / _f(r.get("ebitda")) if _f(r.get("ebitda")) and _f(r.get("ebitda")) > 0 else None
            for _, r in hist.iterrows()
        ]
        fig_mult = _lines(anos_h, [("EV/EBITDA implícito", ev_eb_hist, C["cyan"])],
                          title="EV/EBITDA usando EBITDA histórico e EV atual")
        st.plotly_chart(fig_mult, use_container_width=True)

    st.markdown("---")

    # ── SEÇÃO 3: EPV ─────────────────────────────────────────────────────────
    sec("EPV — Earnings Power Value  (Greenwald)")
    box("EPV = NOPAT / WACC  |  NOPAT = EBIT normalizado × (1 − alíquota)  |  "
        "EPV Equity = EPV − Dívida Líquida", "info")

    e1, e2 = st.columns(2)
    with e1:
        epv_ebit  = st.number_input("EBIT normalizado (R$ M)",
                                    value=round(_f(ebit)/1e6, 1) if ebit else 0.0,
                                    step=100.0, key="epv_ebit")
        epv_tax   = st.slider("Alíquota efetiva", 0.15, 0.45, t_rate/100, 0.01, key="epv_tax")
        epv_wacc  = st.number_input("WACC (%)", 0.0, 30.0, round(wacc_final*100, 2), 0.25, key="epv_wacc2") / 100
        epv_nd    = st.number_input("Dívida Líquida (R$ M)",
                                    value=round(_f(nd)/1e6, 1) if nd else 0.0,
                                    step=100.0, key="epv_nd")
        epv_shr   = st.number_input("Ações em circulação (M) — para EPV/ação",
                                    value=acoes, step=10.0, key="epv_shr",
                                    help="Deixe 0 para não calcular por ação")

    with e2:
        epv_res = calculate_epv(epv_ebit * 1e6, tax_rate=epv_tax,
                                wacc=epv_wacc or 0.01, net_debt=epv_nd * 1e6)
        if epv_shr > 0 and epv_res.get("epv_equity"):
            epv_res["epv_per_share"] = epv_res["epv_equity"] / (epv_shr * 1e6)

        st.markdown(mc("NOPAT",          fbrl(epv_res.get("nopat")),          _cls(epv_res.get("nopat"))), unsafe_allow_html=True)
        st.markdown(mc("EPV Enterprise", fbrl(epv_res.get("epv_enterprise")), _cls(epv_res.get("epv_enterprise"))), unsafe_allow_html=True)
        st.markdown(mc("EPV Equity",     fbrl(epv_res.get("epv_equity")),     _cls(epv_res.get("epv_equity"))), unsafe_allow_html=True)
        if epv_res.get("epv_per_share"):
            st.markdown(mc("EPV por Ação", f"R$ {epv_res['epv_per_share']:,.2f}",
                           _cls(epv_res.get("epv_per_share"))), unsafe_allow_html=True)
        fl = "  ·  ".join(epv_res.get("flags", []))
        st.caption(f"Status: `{fl}`")

        epv_ev = _f(epv_res.get("epv_enterprise"))
        epv_nopat = _f(epv_res.get("nopat"))
        if epv_nopat and epv_ev:
            box(f"NOPAT = R$ {epv_nopat/1e6:,.0f}M  ÷  WACC {epv_wacc*100:.2f}%  =  "
                f"EPV Enterprise R$ {epv_ev/1e6:,.0f}M", "ok")

    st.markdown("---")

    # ── SEÇÃO 4: DCF Completo ─────────────────────────────────────────────
    sec("DCF — Discounted Cash Flow Completo")
    box("EV = Σ FCL/(1+WACC)ᵗ + TV/(1+WACC)ⁿ  |  TV = FCL_n×(1+g)/(WACC−g)  |  "
        "Equity = EV − Dívida Líquida  |  "
        "FCL = Caixa Operacional − CAPEX (dados CVM)", "info")

    eq_shr  = None  # preenchido pelo bloco DCF abaixo
    dcf_res = None  # idem

    # FCL base: usa dados CVM (FCOP − |CAPEX|)
    fcop_cvm  = _f(snap_ext.get("fluxo_caixa_operacional"))
    capex_cvm = _f(snap_ext.get("capex"))
    fcl_cvm   = None
    if fcop_cvm is not None:
        fcl_cvm = fcop_cvm - abs(capex_cvm or 0)
    fcl_default = round(fcl_cvm / 1e6, 1) if fcl_cvm else (round(_f(fcl)/1e6, 1) if fcl else 0.0)

    d1, d2 = st.columns([1, 1])
    with d1:
        st.markdown("**Premissas — FCL e Capital (dados CVM como base)**")
        if fcl_cvm is not None:
            st.caption(
                f"CVM: FCOP = {fbrl(fcop_cvm)}  |  CAPEX = {fbrl(capex_cvm)}  "
                f"→  **FCL = {fbrl(fcl_cvm)}**"
            )
        dcf_fcl = st.number_input("FCL Base (R$ M) — auditável",
                                  value=fcl_default, step=100.0, key="dcf_fcl",
                                  help="Pre-preenchido com FCOP−CAPEX da CVM. Edite se necessário.")
        dcf_nd  = st.number_input("Dívida Líquida (R$ M) — auditável",
                                  value=round(_f(nd)/1e6, 1) if nd else 0.0,
                                  step=100.0, key="dcf_nd2",
                                  help="Dívida Bruta − Caixa (dados CVM)")
        dcf_shr = st.number_input("Ações (M) — para Equity/ação",
                                  value=acoes, step=10.0, key="dcf_shr")

        st.markdown("**Premissas de Crescimento — auditáveis**")
        cg1, cg2 = st.columns(2)
        with cg1:
            g12 = st.slider("Anos 1–2 (%)",  0.0, 35.0, 10.0, 0.5, key="dg12") / 100
            g34 = st.slider("Anos 3–4 (%)",  0.0, 25.0,  7.0, 0.5, key="dg34") / 100
        with cg2:
            g5  = st.slider("Ano 5 (%)",      0.0, 20.0,  6.0, 0.5, key="dg5")  / 100
            g_t = st.slider("g terminal (%)", 0.0,  7.0,  4.5, 0.25, key="dgt") / 100

        dcf_wacc = st.number_input("WACC (%) — preenche com o calculado acima",
                                   0.0, 30.0, round(wacc_final*100, 2), 0.25, key="dcf_wacc2") / 100

        st.caption(
            f"Premissas: FCL R$ {dcf_fcl:,.0f}M | g12={g12:.1%} | g34={g34:.1%} | "
            f"g5={g5:.1%} | g_terminal={g_t:.2%} | WACC={dcf_wacc:.2%} | "
            f"Dívida Líq R$ {dcf_nd:,.0f}M | Ações {dcf_shr:,.0f}M"
        )

        growth_rates = [g12, g12, g34, g34, g5]

    with d2:
        st.markdown("**Resultado DCF**")

        if dcf_wacc <= g_t:
            box(f"WACC ({dcf_wacc:.3f}) deve ser maior que g terminal ({g_t:.3f})!", "err")
        elif dcf_fcl == 0:
            box("FCL = 0. Verifique se os dados CVM estão carregados ou edite o FCL Base acima.", "warn")
        else:
            dcf_res = calculate_dcf(
                base_fcf=dcf_fcl * 1e6,
                growth_rates=growth_rates,
                terminal_growth=g_t,
                wacc=dcf_wacc,
                net_debt=dcf_nd * 1e6,
            )
            ev_dcf  = _f(dcf_res.get("enterprise_value"))
            eq_dcf  = _f(dcf_res.get("equity_value"))
            vp_tv   = _f(dcf_res.get("vp_valor_terminal"))
            pct_tv  = dcf_res.get("premissas", {}).get("pct_ev_de_valor_terminal")
            fl_dcf  = "  ·  ".join(dcf_res.get("flags", []))

            eq_shr = eq_dcf / (dcf_shr * 1e6) if dcf_shr > 0 and eq_dcf else None

            st.markdown(mc("Enterprise Value (EV)",  fbrl(ev_dcf),  _cls(ev_dcf)),  unsafe_allow_html=True)
            st.markdown(mc("Equity Value",           fbrl(eq_dcf),  _cls(eq_dcf)),  unsafe_allow_html=True)
            st.markdown(mc("VP do Valor Terminal",   fbrl(vp_tv),   "blu"),          unsafe_allow_html=True)
            if pct_tv:
                cls_tv = "pos" if pct_tv < 75 else "neg"
                st.markdown(mc("% EV do Valor Terminal", f"{pct_tv:.1f}%", cls_tv), unsafe_allow_html=True)
            if eq_shr:
                st.markdown(mc("Equity por Ação", f"R$ {eq_shr:,.2f}", _cls(eq_shr)), unsafe_allow_html=True)

            st.caption(f"Status: `{fl_dcf}`")

            # Projeção detalhada
            fcfs = dcf_res.get("fcfs_projetados", [])
            vps  = dcf_res.get("vp_fcfs", [])
            if fcfs:
                df_proj = pd.DataFrame({
                    "Ano":          list(range(1, len(fcfs)+1)),
                    "g Aplicada":   [f"{r:.1%}" for r in growth_rates],
                    "FCL Projetado":  [f"R$ {v/1e6:,.1f}M" for v in fcfs],
                    "VP do FCL":      [f"R$ {v/1e6:,.1f}M" for v in vps],
                })
                st.dataframe(df_proj, use_container_width=True, hide_index=True)

    # Sensibilidade
    if dcf_fcl != 0 and dcf_wacc > g_t:
        sec("Análise de Sensibilidade — EV (R$ Bilhões)")
        waccs = [max(0.07, dcf_wacc + dw) for dw in [-0.02, -0.01, 0, +0.01, +0.02]]
        gs    = sorted({max(0.01, g_t - 0.01), g_t, min(0.07, g_t + 0.01)})
        gs    = [g for g in gs if g < dcf_wacc - 0.005]

        if gs:
            sens = []
            for w in waccs:
                row = {"WACC \\ g": f"{w:.2%}"}
                for g in gs:
                    if w > g + 0.005:
                        d = calculate_dcf(dcf_fcl*1e6, growth_rates, g, w, dcf_nd*1e6)
                        ev_s = _f(d.get("enterprise_value"))
                        row[f"g={g:.1%}"] = f"R$ {ev_s/1e6:,.0f}M" if ev_s else "N/D"
                    else:
                        row[f"g={g:.1%}"] = "—"
                sens.append(row)
            st.dataframe(pd.DataFrame(sens), use_container_width=True, hide_index=True)

    # ── Gráfico comparativo de valores ─────────────────────────────────────
    sec("Comparativo de Valuation")
    val_labels = []
    val_values = []

    if mktcap:
        val_labels.append("Market Cap (mercado)"); val_values.append(_f(mktcap) / 1e6)
    if pl:
        val_labels.append("Valor Patrimonial (PL)"); val_values.append(_f(pl) / 1e6)
    epv_ev2 = _f(epv_res.get("epv_enterprise"))
    if epv_ev2:
        val_labels.append("EPV Enterprise"); val_values.append(epv_ev2 / 1e6)
    if dcf_res and _f(dcf_res.get("enterprise_value")):
        val_labels.append("DCF Enterprise"); val_values.append(_f(dcf_res.get("enterprise_value")) / 1e6)

    if len(val_labels) >= 2:
        bar_colors = [C["blue"], C["purple"], C["teal"], C["green"]][:len(val_labels)]
        fig_comp = go.Figure(go.Bar(
            x=val_values, y=val_labels, orientation="h",
            marker_color=bar_colors,
            text=[f"R$ {v:.1f}B" for v in val_values],
            textposition="outside", textfont=dict(color=C["t2"], size=11),
        ))
        fig_comp.update_layout(**_PL, title="Comparativo de Enterprise Values (R$ Bilhões)",
                               showlegend=False)
        st.plotly_chart(fig_comp, use_container_width=True)

    # ── Painel de resumo no topo (preenchido após todos os cálculos) ─────────
    _preco    = preco   if preco  > 0  else None
    _acoes_m  = acoes   if acoes  > 0  else None
    _epv_shr  = epv_res.get("epv_per_share") if epv_shr > 0 else None
    _epv_ev   = _f(epv_res.get("epv_enterprise"))
    _epv_eq   = _f(epv_res.get("epv_equity"))
    _dcf_ev   = _f(dcf_res.get("enterprise_value")) if dcf_res else None
    _dcf_eq   = _f(dcf_res.get("equity_value"))     if dcf_res else None
    _dcf_shr  = eq_shr

    with _top_summary.container():
        sec("Resumo — Valuation")
        _sc = st.columns(4)

        # Card 1 — EPV
        if _epv_shr:
            _sc[0].markdown(mc("EPV / Ação", f"R$ {_epv_shr:,.2f}", _cls(_epv_shr)), unsafe_allow_html=True)
        elif _epv_eq:
            _sc[0].markdown(mc("EPV Equity", fbrl(_epv_eq), _cls(_epv_eq)), unsafe_allow_html=True)
        elif _epv_ev:
            _sc[0].markdown(mc("EPV Enterprise", fbrl(_epv_ev), _cls(_epv_ev)), unsafe_allow_html=True)
        else:
            _sc[0].markdown(mc("EPV", "Preencha EBIT abaixo", "nd"), unsafe_allow_html=True)

        # Card 2 — DCF
        if _dcf_shr:
            _sc[1].markdown(mc("DCF / Ação", f"R$ {_dcf_shr:,.2f}", _cls(_dcf_shr)), unsafe_allow_html=True)
        elif _dcf_eq:
            _sc[1].markdown(mc("DCF Equity", fbrl(_dcf_eq), _cls(_dcf_eq)), unsafe_allow_html=True)
        elif _dcf_ev:
            _sc[1].markdown(mc("DCF Enterprise", fbrl(_dcf_ev), _cls(_dcf_ev)), unsafe_allow_html=True)
        else:
            _sc[1].markdown(mc("DCF", "Preencha FCL abaixo", "nd"), unsafe_allow_html=True)

        # Card 3 — Preço de mercado
        _sc[2].markdown(mc("Preço de Mercado",
                           f"R$ {_preco:,.2f}" if _preco else "Informe em Múltiplos ↓",
                           "blu" if _preco else "nd"), unsafe_allow_html=True)

        # Card 4 — Upside
        _ref_shr = _epv_shr or _dcf_shr
        if _ref_shr and _preco:
            _lbl_up = "Upside EPV" if _epv_shr else "Upside DCF"
            _up = (_ref_shr / _preco - 1) * 100
            _sc[3].markdown(mc(_lbl_up, f"{_up:+.1f}%", "pos" if _up > 0 else "neg"), unsafe_allow_html=True)
        elif _epv_ev and _dcf_ev:
            _up_ev = (_epv_ev / _dcf_ev - 1) * 100
            _sc[3].markdown(mc("EPV vs DCF Enterprise", f"{_up_ev:+.1f}%",
                               "pos" if _up_ev > 0 else "neg"), unsafe_allow_html=True)
        else:
            _sc[3].markdown(mc("Upside", "Informe preço + ações ↓", "nd"), unsafe_allow_html=True)


def _tab_macro():
    """Aba de dados macroeconômicos brasileiros via BCB."""
    sec("Indicadores Macroeconômicos — Banco Central do Brasil")

    # Definição das séries
    SERIES = {
        "SELIC Meta (% a.a.)":       (432,  C["blue"],  "Comitê de Política Monetária"),
        "IPCA (% mensal)":           (433,  C["red"],   "Inflação oficial"),
        "CDI Diário (% a.a.)":       (4392, C["cyan"],  "Taxa interbancária"),
        "IGP-M (% mensal)":          (189,  C["yellow"],"FGV — aluguéis"),
        "INPC (% mensal)":           (188,  C["purple"],"Famílias de baixa renda"),
        "USD/BRL (ptax venda)":      (1,    C["teal"],  "Dólar comercial"),
    }

    # Cards com último valor
    col_cards = st.columns(len(SERIES))
    series_data = {}

    for i, (nome, (codigo, cor, desc)) in enumerate(SERIES.items()):
        df_s = _bcb_serie(codigo, 36)
        series_data[nome] = (df_s, cor)

        with col_cards[i]:
            if not df_s.empty:
                last_val  = df_s["valor"].iloc[-1]
                last_date = df_s["data"].iloc[-1].strftime("%d/%m/%y")
                prev_val  = df_s["valor"].iloc[-2] if len(df_s) > 1 else None
                delta     = last_val - prev_val if prev_val is not None else None
                cls_d     = "pos" if (delta or 0) < 0 and nome.startswith("USD") \
                           else "neg" if (delta or 0) > 0 and nome.startswith("USD") \
                           else "pos" if (delta or 0) > 0 else "neg"
                sub_txt = f"Δ {delta:+.2f}  |  {last_date}" if delta is not None else last_date
                st.markdown(mc(nome.split("(")[0].strip(),
                               f"{last_val:.2f}", cls_d, sub_txt), unsafe_allow_html=True)
            else:
                st.markdown(mc(nome.split("(")[0].strip(), "Offline", "nd",
                               "BCB API indisponível"), unsafe_allow_html=True)

    # Gráficos
    sec("Gráficos Históricos — Últimos 36 Meses")

    # SELIC + CDI
    df_sel = series_data.get("SELIC Meta (% a.a.)", (pd.DataFrame(), ""))[0]
    df_cdi = series_data.get("CDI Diário (% a.a.)", (pd.DataFrame(), ""))[0]

    if not df_sel.empty or not df_cdi.empty:
        fig_sel = go.Figure()
        if not df_sel.empty:
            fig_sel.add_trace(go.Scatter(x=df_sel["data"], y=df_sel["valor"],
                                         name="SELIC Meta", mode="lines",
                                         line=dict(color=C["blue"], width=2.5)))
        if not df_cdi.empty:
            fig_sel.add_trace(go.Scatter(x=df_cdi["data"], y=df_cdi["valor"],
                                         name="CDI", mode="lines",
                                         line=dict(color=C["cyan"], width=1.5, dash="dot")))
        fig_sel.update_layout(**_PL, title="SELIC Meta e CDI (% a.a.)")
        st.plotly_chart(fig_sel, use_container_width=True)

    # IPCA + IGPM + INPC
    df_ipca = series_data.get("IPCA (% mensal)", (pd.DataFrame(), ""))[0]
    df_igpm = series_data.get("IGP-M (% mensal)", (pd.DataFrame(), ""))[0]
    df_inpc = series_data.get("INPC (% mensal)", (pd.DataFrame(), ""))[0]

    if not df_ipca.empty:
        fig_inf = go.Figure()
        if not df_ipca.empty:
            fig_inf.add_trace(go.Scatter(x=df_ipca["data"], y=df_ipca["valor"],
                                          name="IPCA", mode="lines+markers",
                                          line=dict(color=C["red"], width=2)))
        if not df_igpm.empty:
            fig_inf.add_trace(go.Scatter(x=df_igpm["data"], y=df_igpm["valor"],
                                          name="IGP-M", mode="lines",
                                          line=dict(color=C["yellow"], width=1.5, dash="dot")))
        if not df_inpc.empty:
            fig_inf.add_trace(go.Scatter(x=df_inpc["data"], y=df_inpc["valor"],
                                          name="INPC", mode="lines",
                                          line=dict(color=C["purple"], width=1.5, dash="dot")))
        fig_inf.update_layout(**_PL, title="Inflação Mensal (%)")
        st.plotly_chart(fig_inf, use_container_width=True)

    # USD/BRL
    df_usd = series_data.get("USD/BRL (ptax venda)", (pd.DataFrame(), ""))[0]
    if not df_usd.empty:
        fig_usd = go.Figure()
        fig_usd.add_trace(go.Scatter(x=df_usd["data"], y=df_usd["valor"],
                                      name="USD/BRL", mode="lines",
                                      line=dict(color=C["teal"], width=2),
                                      fill="tozeroy",
                                      fillcolor=rgba(C["teal"], 0.07)))
        fig_usd.update_layout(**_PL, title="Dólar Comercial (PTAX Venda)")
        st.plotly_chart(fig_usd, use_container_width=True)

    # Tabela consolidada
    sec("Tabela de Referência Macroeconômica")
    macro_rows = []
    for nome, (df_s, cor) in series_data.items():
        if not df_s.empty:
            last = df_s.iloc[-1]
            acum = df_s["valor"].tail(12).sum() if "mensal" in nome.lower() else None
            macro_rows.append({
                "Indicador":    nome,
                "Último Valor": f"{last['valor']:.2f}",
                "Data":         last["data"].strftime("%d/%m/%Y"),
                "Acum. 12m":   f"{acum:.2f}%" if acum is not None else "–",
                "Fonte":        "BCB / SGS",
            })
        else:
            macro_rows.append({
                "Indicador": nome, "Último Valor": "Offline",
                "Data": "–", "Acum. 12m": "–", "Fonte": "BCB / SGS",
            })

    if macro_rows:
        st.dataframe(pd.DataFrame(macro_rows), use_container_width=True, hide_index=True)

    box("Dados em tempo real via <b>api.bcb.gov.br/dados/serie</b> (Banco Central do Brasil — SGS). "
        "Atualização a cada 30 minutos. Se offline, verifique sua conexão com a internet.", "info")


# ─────────────────────────────────────────────────────────────────────────────
# Welcome & Demo screens
# ─────────────────────────────────────────────────────────────────────────────

def _welcome(avail):
    box("""<b>EPS Value Terminal</b> — Análise fundamentalista de empresas brasileiras.<br>
🔍 Busque uma empresa na barra lateral por <b>nome</b>, <b>CD_CVM</b> ou <b>CNPJ</b>.<br>
📊 Veja DRE, Balanço, DFC, métricas e histórico gráfico.<br>
📋 Analise saúde financeira: alavancagem, liquidez, estrutura da dívida.<br>
💹 Calcule EPV e DCF com WACC breakdown completo.<br>
🌐 Monitore macro: SELIC, IPCA, CDI, USD/BRL em tempo real.""", "info")

    sec("Dados em Cache Local")
    for tipo in TIPOS_DOC:
        row = st.columns(len(DEMONSTRATIVOS))
        for i, stmt in enumerate(DEMONSTRATIVOS):
            ok = avail.get(f"{tipo}_{stmt}", False)
            with row[i]:
                if ok:
                    try:
                        df_t = pd.read_parquet(
                            get_processed_path(stmt.lower(), tipo.lower(), "parquet"),
                            columns=["CD_CVM"],
                        )
                        n_co = df_t["CD_CVM"].nunique()
                        n_rc = len(df_t)
                        st.markdown(mc(f"{tipo}/{stmt}",
                                       f"{n_rc:,} reg",
                                       "pos",
                                       f"{n_co:,} empresas"), unsafe_allow_html=True)
                    except Exception:
                        st.markdown(mc(f"{tipo}/{stmt}", "✓ OK", "pos"), unsafe_allow_html=True)
                else:
                    st.markdown(mc(f"{tipo}/{stmt}", "Não baixado", "nd"), unsafe_allow_html=True)


def _render_brapi_panel(q: Dict, ticker: str):
    """Painel completo de dados de mercado BRAPI."""
    sec(f"📈 Dados de Mercado — {ticker}  (BRAPI.dev · atualizado a cada 5 min)")

    preco  = q.get("regularMarketPrice", 0)
    var_d  = q.get("regularMarketChangePercent", 0)
    var_r  = q.get("regularMarketChange", 0)
    mktcap = q.get("marketCap")
    acoes  = q.get("sharesOutstanding")
    vol    = q.get("regularMarketVolume")
    vol10d = q.get("averageDailyVolume10Day")
    pl     = q.get("priceEarningsRatio")
    pvp    = q.get("priceToBook")
    ev_ebd = q.get("enterpriseValueEbitda")
    ev     = q.get("enterpriseValue")
    dy     = q.get("dividendYield")
    hi52   = q.get("fiftyTwoWeekHigh")
    lo52   = q.get("fiftyTwoWeekLow")
    nome_c = q.get("shortName", ticker)

    cor_v  = _cls(var_d)
    sinal  = "▲" if var_d >= 0 else "▼"

    # Row 1: preço e variação
    c = st.columns(5)
    c[0].markdown(mc("Preço Atual", f"R$ {preco:.2f}", cor_v,
                     f"{sinal} R$ {abs(var_r):.2f} ({var_d:+.2f}%)"), unsafe_allow_html=True)
    c[1].markdown(mc("Market Cap",  fbrl(mktcap), "blu"), unsafe_allow_html=True)
    c[2].markdown(mc("Ações (M)",   f"{acoes/1e6:,.0f}M" if acoes else "–", "neu"), unsafe_allow_html=True)
    c[3].markdown(mc("Volume Hoje", f"{vol/1e6:.1f}M" if vol else "–", "neu",
                     f"Média 10d: {vol10d/1e6:.1f}M" if vol10d else ""), unsafe_allow_html=True)
    c[4].markdown(mc("Dividend Yield", f"{dy:.2f}%" if dy else "–",
                     "pos" if dy and dy > 0 else "nd"), unsafe_allow_html=True)

    # Row 2: múltiplos de mercado (BRAPI)
    c2 = st.columns(5)
    c2[0].markdown(mc("P/L (mercado)",      fmult(pl, 1)   if pl   else "–", "neu"), unsafe_allow_html=True)
    c2[1].markdown(mc("P/VP (mercado)",     fmult(pvp, 2)  if pvp  else "–", "neu"), unsafe_allow_html=True)
    c2[2].markdown(mc("EV/EBITDA (mercado)",fmult(ev_ebd,1)if ev_ebd else "–", "neu"), unsafe_allow_html=True)
    c2[3].markdown(mc("Enterprise Value",   fbrl(ev)  if ev   else "–", "cyan"), unsafe_allow_html=True)
    if hi52 and lo52:
        pos_pct = (preco - lo52) / (hi52 - lo52) * 100 if hi52 != lo52 else 50
        c2[4].markdown(mc("52 Semanas",
                          f"R$ {lo52:.2f} – R$ {hi52:.2f}",
                          "pos" if pos_pct > 50 else "neg",
                          f"Posição atual: {pos_pct:.0f}%"), unsafe_allow_html=True)


def _no_data():
    box("""<b>⚠ Nenhum dado processado encontrado</b><br><br>
Execute o pipeline CVM no seu computador para baixar os dados:<br><br>
<code>cd valuation_cvm</code><br>
<code>python -m src.main --start-year 2019 --end-year 2025</code><br><br>
O download pode levar 20–60 min dependendo da sua conexão. Após concluir, recarregue esta página.
""", "warn")

    sec("Prévia do Layout — Dados Hipotéticos")
    box("Os valores abaixo são <b>demonstrativos</b> apenas para ilustrar o painel. "
        "Dados reais aparecem após rodar o pipeline.", "info")

    demo = {
        "receita_liquida": 58e9, "lucro_bruto": 24e9, "ebit": 14e9,
        "lucro_liquido": 9e9, "caixa_total": 18e9, "divida_bruta": 35e9,
        "divida_liquida": 17e9, "patrimonio_liquido": 48e9, "ativo_total": 140e9,
        "margem_bruta": 0.414, "margem_ebit": 0.241, "margem_liquida": 0.155,
        "roe": 0.188, "roa": 0.064, "roic_aprox": 0.172,
        "fluxo_caixa_operacional": 12e9, "fcl_aprox": 8.5e9,
    }
    co_strip("EMPRESA DEMONSTRAÇÃO S.A.", "00000", "DFP")
    _tab_overview(demo, {})

    anos_d = [2019, 2020, 2021, 2022, 2023, 2024]
    fig_d = _lines(anos_d, [
        ("Receita",      [38, 35, 44, 53, 58, 58], C["blue"]),
        ("EBIT",         [9,  7,  11, 14, 15, 14], C["green"]),
        ("Lucro Líquido",[6,  4,  8,  10, 10, 9],  C["purple"]),
    ], title="Evolução Financeira (R$ Bilhões) — DEMONSTRAÇÃO")
    st.plotly_chart(fig_d, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    header()

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown('<div class="sec">🔍 Buscar Empresa</div>', unsafe_allow_html=True)
        query    = st.text_input("", placeholder="Nome, CD_CVM ou CNPJ…",
                                 key="q", label_visibility="collapsed")
        tipo_raw = st.selectbox("Tipo de relatório",
                                ["DFP — Demonstração Anual", "ITR — Informação Trimestral"],
                                key="tipo")
        tipo_doc = tipo_raw.split(" ")[0]

        st.markdown("---")
        avail    = _avail()
        has_data = any(avail.values())

        st.markdown('<div class="sec">Status dos Dados</div>', unsafe_allow_html=True)
        for tipo in TIPOS_DOC:
            ok_cnt = sum(v for k, v in avail.items() if k.startswith(tipo))
            total  = sum(1 for k in avail if k.startswith(tipo))
            icon   = "●" if ok_cnt == total else "◑" if ok_cnt > 0 else "○"
            color  = C["green"] if ok_cnt == total else C["yellow"] if ok_cnt > 0 else C["red"]
            st.markdown(
                f'<span style="color:{color}">{icon} {tipo}: {ok_cnt}/{total}</span>',
                unsafe_allow_html=True,
            )

        st.markdown("---")
        st.markdown(f"""
<div style="font-size:11px;color:{C['t3']};line-height:1.9">
Para baixar dados:<br>
<code style="color:{C['t2']}">python -m src.main</code><br>
<code style="color:{C['t2']}">  --start-year 2019</code><br>
<code style="color:{C['t2']}">  --end-year 2025</code>
</div>""", unsafe_allow_html=True)

    # ── Rota principal ────────────────────────────────────────────────────────
    if not has_data:
        _no_data()
        return

    # Busca
    selected_cd  = None
    selected_name = None
    selected_setor = ""

    if query:
        reg = _registry()
        if reg.empty:
            box("Cadastro de empresas não encontrado.", "warn")
        else:
            matches = filter_company_by_name_or_cvm(query, df=reg)
            if matches.empty:
                box(f'Nenhuma empresa encontrada para <b>"{query}"</b>.', "warn")
            else:
                if len(matches) > 1:
                    sec("Resultados da Busca")
                    opts = [
                        f"{r.get('DENOM_CIA','N/D')}  (CD_CVM: {r.get('CD_CVM','?')})"
                        for _, r in matches.iterrows()
                    ]
                    idx  = st.selectbox("Selecione:", range(len(opts)),
                                        format_func=lambda i: opts[i], key="sel")
                    row  = matches.iloc[idx]
                else:
                    row  = matches.iloc[0]

                selected_cd    = str(row.get("CD_CVM", "")).strip()
                selected_name  = str(row.get("DENOM_CIA", "N/D")).strip()
                selected_setor = str(row.get("SETOR_ATIV", "")).strip()

    if not selected_cd:
        _welcome(avail)
        return

    # Dashboard da empresa
    with st.spinner(f"Carregando {selected_name}…"):
        snap_ext = _ext_snap(selected_cd, tipo_doc)
        m        = calculate_basic_metrics(snap_ext)
        m["caixa_total"]    = (snap_ext.get("caixa_equivalentes") or 0) + (snap_ext.get("aplicacoes_financeiras") or 0) or None
        m["divida_liquida"] = snap_ext.get("divida_liquida")
        hist = _history(selected_cd, tipo_doc)

    # ── Auto-detect ticker quando empresa muda ───────────────────────────────
    if selected_cd and st.session_state.get("_last_cd_ticker") != selected_cd:
        st.session_state["_last_cd_ticker"] = selected_cd
        detected = _auto_ticker_from_name(selected_name or "")
        if detected:
            st.session_state["ticker"] = detected
        st.rerun()

    # ── Busca cotação BRAPI antes de renderizar o cabeçalho ──────────────────
    ticker_input = st.session_state.get("ticker", "").strip().upper()
    brapi_data = _brapi_quote(ticker_input) if ticker_input else None

    # ── Cabeçalho com nome + cotação ao lado ─────────────────────────────────
    co_strip(selected_name, selected_cd, tipo_doc, selected_setor,
             brapi_data=brapi_data, ticker=ticker_input)

    # ── Sidebar: ticker editável + detalhes ──────────────────────────────────
    with st.sidebar:
        st.markdown("---")
        st.markdown('<div class="sec">📈 Cotação B3 (BRAPI)</div>', unsafe_allow_html=True)
        ticker_input = st.text_input(
            "", placeholder="Ex: PETR4, VALE3, WEGE3",
            key="ticker", label_visibility="collapsed",
        )
        if brapi_data:
            preco = brapi_data.get("regularMarketPrice", 0)
            var_d = brapi_data.get("regularMarketChangePercent", 0)
            cor_v = C["green"] if var_d >= 0 else C["red"]
            sinal = "▲" if var_d >= 0 else "▼"
            st.markdown(
                f'<div style="background:{C["surf"]};border:1px solid {C["brd"]};'
                f'border-left:3px solid {C["blue"]};border-radius:6px;padding:10px 14px;margin-top:4px">'
                f'<div style="color:{C["t3"]};font-size:10px;letter-spacing:1px">{ticker_input.upper()}</div>'
                f'<div style="color:{C["t1"]};font-size:22px;font-weight:700">R$ {preco:.2f}</div>'
                f'<div style="color:{cor_v};font-size:12px">{sinal} {abs(var_d):.2f}% hoje</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            hi52 = brapi_data.get("fiftyTwoWeekHigh")
            lo52 = brapi_data.get("fiftyTwoWeekLow")
            if hi52 and lo52 and hi52 != lo52:
                pos_pct = (preco - lo52) / (hi52 - lo52) * 100
                st.markdown(
                    f'<div style="font-size:10px;color:{C["t3"]};margin-top:6px">'
                    f'52 sem: R$ {lo52:.2f} — R$ {hi52:.2f}<br>'
                    f'<div style="background:{C["brd2"]};border-radius:3px;height:5px;margin-top:4px">'
                    f'<div style="background:{C["blue"]};width:{pos_pct:.0f}%;height:100%;border-radius:3px"></div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            dy = brapi_data.get("dividendYield")
            if dy:
                st.markdown(f'<span style="color:{C["t3"]};font-size:10px">DY: <b style="color:{C["green"]}">{dy:.2f}%</b></span>',
                            unsafe_allow_html=True)
        elif ticker_input:
            st.markdown(f'<span style="color:{C["red"]};font-size:11px">Ticker não encontrado ou API offline.</span>',
                        unsafe_allow_html=True)

    tabs = st.tabs(["VISÃO GERAL", "HISTÓRICO", "DEMONSTRATIVOS",
                    "SAÚDE FINANCEIRA", "VALUATION", "MACRO BRASIL"])

    with tabs[0]: _tab_overview(m, snap_ext)
    with tabs[1]: _tab_history(selected_cd, tipo_doc, selected_name)
    with tabs[2]: _tab_statements(selected_cd, tipo_doc)
    with tabs[3]: _tab_health(snap_ext, m, hist)
    with tabs[4]: _tab_valuation(m, snap_ext, selected_cd, hist, brapi_data=brapi_data)
    with tabs[5]: _tab_macro()


if __name__ == "__main__":
    main()
