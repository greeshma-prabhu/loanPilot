"""Shared visual elements for LoanPilot pages."""

import streamlit as st

from loanpilot.badges import implementation_badge
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore

_CSS = """
<style>
    :root {
        --lp-ink: #143b3c;
        --lp-muted: #617779;
        --lp-teal: #0e7775;
        --lp-line: #dce8e7;
        --lp-canvas: #f3f7f7;
    }
    .stApp {
        background:
            radial-gradient(ellipse at 86% 0%, rgba(201, 231, 227, .48), transparent 34rem),
            var(--lp-canvas);
        color: var(--lp-ink);
    }
    [data-testid="stHeader"] {
        background: rgba(243, 247, 247, .86);
        backdrop-filter: blur(12px);
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #102f35 0%, #163f43 58%, #18504e 100%);
        border-right: 1px solid rgba(255,255,255,.1);
    }
    [data-testid="stSidebar"] * { color: #edf7f6; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #bdd2d1; }
    [data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {
        border-radius: 10px;
        margin: 3px 8px;
        transition: background .18s ease, transform .18s ease;
    }
    [data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {
        background: rgba(255,255,255,.1);
        transform: translateX(2px);
    }
    [data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {
        background: rgba(128, 207, 195, .2);
        box-shadow: inset 3px 0 #83d2c3;
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {
        background: rgba(255,255,255,.1);
        border-color: rgba(255,255,255,.2);
        color: #fff;
    }
    .block-container {
        max-width: 1440px;
        padding-top: 2rem;
        padding-bottom: 4rem;
    }
    h1, h2, h3, h4 {
        color: var(--lp-ink);
        letter-spacing: -.025em;
    }
    h1 {
        font-size: clamp(2rem, 3.2vw, 2.8rem) !important;
        line-height: 1.1 !important;
        font-weight: 760 !important;
        margin: .25rem 0 .45rem !important;
    }
    h2 { font-weight: 720 !important; }
    h3 { font-weight: 690 !important; }
    p, [data-testid="stCaptionContainer"] { color: var(--lp-muted); }
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, #fff, #f8fbfb);
        border: 1px solid var(--lp-line);
        border-radius: 16px;
        padding: 1rem 1.1rem;
        box-shadow: 0 5px 16px rgba(20, 59, 60, .045);
    }
    [data-testid="stMetricLabel"] p {
        color: var(--lp-muted);
        font-size: .82rem;
        font-weight: 650;
        letter-spacing: .035em;
        text-transform: uppercase;
    }
    [data-testid="stMetricValue"] { color: var(--lp-ink); font-weight: 760; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--lp-line);
        border-radius: 16px;
        background: rgba(255,255,255,.88);
        box-shadow: 0 7px 22px rgba(20, 59, 60, .045);
    }
    [data-testid="stExpander"] {
        background: rgba(255,255,255,.78);
        border: 1px solid var(--lp-line);
        border-radius: 14px;
        overflow: hidden;
    }
    [data-testid="stExpander"] summary { font-weight: 650; color: var(--lp-ink); }
    [data-testid="stTabs"] [role="tablist"] {
        gap: .35rem;
        border-bottom: 1px solid var(--lp-line);
    }
    [data-testid="stTabs"] button[role="tab"] {
        border-radius: 10px 10px 0 0;
        padding: .65rem 1rem;
        color: var(--lp-muted);
        font-weight: 630;
    }
    [data-testid="stTabs"] button[aria-selected="true"] {
        color: #075957;
        background: rgba(14,119,117,.08);
    }
    [data-testid="stDataFrame"], [data-testid="stTable"] {
        border: 1px solid var(--lp-line);
        border-radius: 12px;
        overflow: hidden;
        background: white;
    }
    [data-testid="stBaseButton-primary"] {
        background: linear-gradient(135deg, #0d7774, #176b69);
        border: 0;
        border-radius: 11px;
        box-shadow: 0 5px 13px rgba(14,119,117,.18);
        font-weight: 680;
        transition: transform .18s ease, box-shadow .18s ease;
    }
    [data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(135deg, #096865, #135c5a);
        transform: translateY(-1px);
        box-shadow: 0 8px 18px rgba(14,119,117,.24);
    }
    [data-testid="stBaseButton-secondary"] {
        border-radius: 11px;
        border-color: #c9d9d8;
        color: var(--lp-ink);
        font-weight: 620;
    }
    [data-baseweb="select"] > div, [data-baseweb="input"] > div,
    [data-baseweb="textarea"] > div {
        border-radius: 10px;
        border-color: #cfdfde;
        background: #fff;
    }
    .lp-disclaimer {
        display: flex;
        align-items: center;
        gap: .6rem;
        padding: .58rem .9rem;
        margin: 0 0 1.5rem;
        border: 1px solid #d5e8e4;
        border-left: 4px solid #1b8279;
        border-radius: 11px;
        background: linear-gradient(90deg, #eaf5f2, #f8fbfa);
        color: #315d5a;
        font-size: .86rem;
        font-weight: 560;
    }
    .lp-disclaimer-icon {
        display: inline-grid;
        width: 1.35rem;
        height: 1.35rem;
        place-items: center;
        border-radius: 50%;
        background: #d2eae4;
        color: #126a63;
        font-size: .76rem;
        font-weight: 800;
    }
    .lp-eyebrow {
        color: #167c76;
        font-size: .72rem;
        font-weight: 760;
        letter-spacing: .14em;
        text-transform: uppercase;
        margin-bottom: .35rem;
    }
    .lp-subtitle {
        color: #627779;
        font-size: 1.02rem;
        max-width: 58rem;
        margin: .1rem 0 1.3rem;
    }
    .lp-pipeline-card {
        min-height: 6.35rem;
        padding: .85rem .75rem;
        border: 1px solid #dce8e7;
        border-radius: 15px;
        background: linear-gradient(145deg, #fff, #f8fbfb);
        box-shadow: 0 5px 15px rgba(20,59,60,.045);
        text-align: center;
    }
    .lp-pipeline-card.is-done {
        border-color: #a9d8cb;
        background: linear-gradient(145deg, #f0faf6, #e7f5ef);
    }
    .lp-pipeline-card.is-ready {
        border: 1.5px solid #67b9ad;
        box-shadow: 0 0 0 3px rgba(48,157,143,.1);
    }
    .lp-pipeline-state {
        color: #637b7b;
        font-size: .76rem;
        font-weight: 740;
        letter-spacing: .045em;
        text-transform: uppercase;
    }
    .lp-pipeline-card.is-done .lp-pipeline-state { color: #167b64; }
    .lp-pipeline-card.is-ready .lp-pipeline-state { color: #08736d; }
    .lp-pipeline-label {
        margin-top: .55rem;
        color: #183e3f;
        font-size: .84rem;
        font-weight: 660;
        line-height: 1.25;
    }
    .loanpilot-banner {
        padding: 0.55rem 0.9rem;
        margin: 0 0 1.1rem 0;
        border-left: 4px solid #0f766e;
        border-radius: 0.35rem;
        background: #e8f4f2;
        color: #173b39;
        font-size: 0.92rem;
    }
    .loanpilot-kpi {
        padding: 1rem 1.1rem;
        border: 1px solid #dce8e7;
        border-radius: 1rem;
        background: linear-gradient(145deg, #ffffff, #f8fbfb);
        box-shadow: 0 5px 16px rgba(20, 59, 60, .045);
    }
    .loanpilot-kpi-label {
        color: #526563;
        font-size: 0.9rem;
    }
    .loanpilot-kpi-value {
        margin-top: 0.25rem;
        color: #173b39;
        font-size: 1.55rem;
        font-weight: 650;
    }
</style>
"""


def render_disclaimer() -> None:
    """Render the synthetic-data disclaimer banner."""
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="lp-disclaimer"><span class="lp-disclaimer-icon">i</span>'
        "Demonstration with synthetic data. Not a real bank system or credit decision.</div>",
        unsafe_allow_html=True,
    )


def render_header(
    title: str,
    purpose: str,
    eyebrow: str = "AARAMBH BANK  /  LOANPILOT",
) -> None:
    """Render a branded section label, page title, and one-line purpose."""
    st.markdown(f'<div class="lp-eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="lp-subtitle">{purpose}</div>', unsafe_allow_html=True)


def render_kpi_card(label: str, value: str) -> None:
    """Render a compact KPI card; available for later phases."""
    st.markdown(
        '<div class="loanpilot-kpi">'
        f'<div class="loanpilot-kpi-label">{label}</div>'
        f'<div class="loanpilot-kpi-value">{value}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_placeholder(title: str, purpose: str, phase: int) -> None:
    """Render the shared shell for a not-yet-implemented page."""
    render_disclaimer()
    render_header(title, purpose)
    st.markdown(
        f"{implementation_badge('simulated')} "
        f"{implementation_badge('planned')}",
        unsafe_allow_html=True,
    )
    st.caption(f"Built in phase {phase}")
    store = SQLiteStore()
    if store.table_counts().get("cur_customers", 0) == 0:
        st.info("No demo data is loaded yet. Load the synthetic sample dataset to begin.")
        if st.button("Load demo data", key="load_demo_data"):
            _reset_demo_data(store)


def _reset_demo_data(store: SQLiteStore) -> None:
    """Regenerate the synthetic dataset and report each table's row count."""
    counts = seed_demo_data(store, reset=True)
    count_text = ", ".join(f"{table}: {count}" for table, count in counts.items())
    st.toast(f"Demo data ready. {count_text}")
