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
        max-width: 1280px;
        padding-top: 4.3rem;
        padding-bottom: 3rem;
    }
    [data-testid="stVerticalBlock"] { gap: .8rem; }
    [data-testid="stMarkdownContainer"],
    [data-testid="stWidgetLabel"],
    [data-testid="stText"],
    [data-testid="stAlert"] {
        font-size: 15px;
        line-height: 1.5;
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
    p { color: var(--lp-muted); }
    [data-testid="stCaptionContainer"] {
        color: #536c6d;
        font-size: 14px;
        line-height: 1.45;
    }
    [data-testid="stCaptionContainer"] p { font-size: 14px; }
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, #fff, #f8fbfb);
        border: 1px solid var(--lp-line);
        border-radius: 14px;
        padding: .9rem 1rem;
        box-shadow: 0 5px 16px rgba(20, 59, 60, .045);
    }
    [data-testid="stMetricLabel"] p {
        color: var(--lp-muted);
        font-size: .9rem;
        font-weight: 650;
        letter-spacing: .035em;
        text-transform: uppercase;
    }
    [data-testid="stMetricValue"] { color: var(--lp-ink); font-weight: 760; }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--lp-line);
        border-radius: 14px;
        background: rgba(255,255,255,.88);
        box-shadow: 0 4px 14px rgba(20, 59, 60, .04);
        padding: .9rem 1rem;
    }
    [data-testid="stExpander"] {
        background: rgba(255,255,255,.78);
        border: 1px solid var(--lp-line);
        border-radius: 12px;
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
    [data-testid="stTabs"] [data-testid="stVerticalBlock"] { gap: .7rem; }
    [data-testid="stProgress"] > div > div > div { background: #0e7775; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        font-size: 14px;
    }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        font-size: 14px;
        color: #c6d9d8;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background: rgba(255,255,255,.07);
        border-color: rgba(255,255,255,.2);
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        color: #f0f8f7 !important;
    }
    .lp-sidebar-brand {
        color: #f0f8f7;
        font-size: 1rem;
        font-weight: 720;
        letter-spacing: -.01em;
        margin: .2rem 0 0;
    }
    [data-testid="stDataFrame"], [data-testid="stTable"] {
        border: 1px solid var(--lp-line);
        border-radius: 12px;
        overflow: hidden;
        background: white;
    }
    .lp-table-wrap {
        width: 100%;
        border: 1px solid var(--lp-line);
        border-radius: 12px;
        overflow: hidden;
        background: #fff;
    }
    .lp-data-table {
        width: 100%;
        border-collapse: collapse;
        table-layout: fixed;
        font-size: .88rem;
    }
    .lp-data-table th,
    .lp-data-table td {
        padding: .5rem .55rem;
        border-bottom: 1px solid #e8eeee;
        text-align: left;
        vertical-align: middle;
        overflow-wrap: anywhere;
    }
    .lp-data-table th {
        background: #f4f8f7;
        color: #355a59;
        font-size: .78rem;
        font-weight: 700;
    }
    .lp-data-table tr:last-child td { border-bottom: 0; }
    .lp-demo-story {
        min-height: 1.35rem;
        overflow: hidden;
        color: #536c6d;
        font-size: .82rem;
        line-height: 1.35;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .lp-assessment-progress {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: .35rem;
        width: 100%;
        margin: .25rem 0 1rem;
    }
    .lp-assessment-step {
        min-width: 0;
        padding: .38rem .45rem;
        border: 1px solid #dce8e7;
        border-radius: 8px;
        background: #fff;
        color: #536c6d;
        font-size: .82rem;
        font-weight: 650;
        line-height: 1.2;
        text-align: center;
        white-space: nowrap;
    }
    .lp-assessment-step.done { color: #155e49; background: #e8f4e9; }
    .lp-assessment-step.running { color: #075957; background: #e4f1ef; border-color: #0e7775; }
    .lp-assessment-step.waiting { color: #586867; background: #f3f5f5; }
    .lp-decision-title {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: .65rem;
        color: #173b39;
        font-size: clamp(1.7rem, 3vw, 2.45rem);
        font-weight: 780;
        line-height: 1.15;
    }
    .lp-decision-title.success { color: #176b3f; }
    .lp-decision-title.warning { color: #805400; }
    .lp-decision-title.danger { color: #9d2f2a; }
    .lp-decision-summary {
        display: -webkit-box;
        max-width: 70rem;
        margin: .55rem 0 .85rem;
        overflow: hidden;
        color: #465e5d;
        font-size: 1rem;
        line-height: 1.45;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 2;
    }
    .lp-decision-fact {
        min-height: 3.8rem;
        padding: .65rem .7rem;
        border: 1px solid #dce8e7;
        border-radius: 10px;
        background: #f8fbfb;
    }
    .lp-decision-fact span {
        display: block;
        color: #536c6d;
        font-size: .78rem;
        font-weight: 650;
        line-height: 1.2;
    }
    .lp-decision-fact strong {
        display: block;
        margin-top: .35rem;
        color: #173b39;
        font-size: .96rem;
        overflow-wrap: anywhere;
    }
    .lp-decision-facts {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: .55rem;
    }
    .lp-decision-facts.compact {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    @media (max-width: 760px) {
        .lp-decision-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .lp-assessment-step { font-size: .73rem; padding-inline: .2rem; }
        .lp-why-line { grid-template-columns: 1.1rem minmax(0, 1fr); }
        .lp-why-line .lp-status-chip { grid-column: 2; justify-self: start; }
    }
    .lp-why-line {
        display: grid;
        grid-template-columns: 1.2rem minmax(0, 1fr) auto;
        align-items: center;
        gap: .55rem;
        margin: .35rem 0;
        color: #294947;
        font-size: .94rem;
        line-height: 1.35;
    }
    .lp-why-line > span:first-child { font-weight: 800; }
    .lp-policy-table {
        width: 100%;
        table-layout: fixed;
        border-collapse: collapse;
        color: #173b39;
        font-size: .9rem;
    }
    .lp-policy-table th, .lp-policy-table td {
        padding: .55rem;
        border: 1px solid #dce8e7;
        text-align: left;
        vertical-align: top;
        overflow-wrap: anywhere;
        white-space: normal;
    }
    .lp-policy-table th { background: #f3f7f7; }
    [data-testid="stBaseButton-primary"] {
        background: linear-gradient(135deg, #0d7774, #176b69);
        color: #fff !important;
        border: 0;
        border-radius: 11px;
        box-shadow: 0 5px 13px rgba(14,119,117,.18);
        font-weight: 680;
        transition: transform .18s ease, box-shadow .18s ease;
    }
    [data-testid="stBaseButton-primary"] *,
    button[kind="primary"] * {
        color: #fff !important;
    }
    [data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(135deg, #096865, #135c5a);
        transform: translateY(-1px);
        box-shadow: 0 8px 18px rgba(14,119,117,.24);
    }
    [data-testid="stBaseButton-secondary"] {
        border-radius: 11px;
        border-color: #c9d9d8;
        color: var(--lp-ink) !important;
        font-weight: 620;
    }
    [data-testid="stBaseButton-secondary"] * {
        color: var(--lp-ink) !important;
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"],
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] * {
        color: #fff !important;
    }
    [data-baseweb="input"] > div,
    [data-baseweb="textarea"] > div,
    [data-baseweb="select"] > div {
        border: 1px solid #9fb3ad !important;
        border-radius: 8px !important;
        background: #fff !important;
        color: #173b39 !important;
        box-shadow: none !important;
    }
    [data-baseweb="input"] input,
    [data-baseweb="textarea"] textarea,
    [data-baseweb="select"] input {
        color: #173b39 !important;
        background: #fff !important;
        caret-color: #0e7775;
    }
    [data-baseweb="input"] input::placeholder,
    [data-baseweb="textarea"] textarea::placeholder,
    [data-baseweb="select"] input::placeholder {
        color: #637777 !important;
        opacity: 1;
    }
    [data-baseweb="input"] > div:focus-within,
    [data-baseweb="textarea"] > div:focus-within,
    [data-baseweb="select"] > div:focus-within {
        border-color: #0e7775 !important;
        box-shadow: 0 0 0 3px rgba(14,119,117,.2) !important;
    }
    [data-testid="stDateInput"] input,
    [data-testid="stNumberInput"] input {
        color: #173b39 !important;
        background: #fff !important;
    }
    [data-testid="stDateInput"] input,
    [data-testid="stNumberInput"] > div > div,
    [data-testid="stTextInput"] > div > div {
        border: 1px solid #9fb3ad !important;
        border-radius: 8px !important;
    }
    [data-testid="stDateInput"] input:focus,
    [data-testid="stNumberInput"] input:focus,
    [data-testid="stTextInput"] input:focus {
        border-color: #0e7775 !important;
        box-shadow: 0 0 0 3px rgba(14,119,117,.2) !important;
    }
    .lp-badge-legend {
        display: grid;
        gap: .3rem;
        justify-items: start;
        max-width: 100%;
    }
    .lp-badge-legend span {
        max-width: 100%;
        white-space: normal;
        line-height: 1.25;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong {
        color: #fff;
    }
    .lp-disclaimer {
        display: flex;
        align-items: center;
        gap: .6rem;
        padding: .58rem .9rem;
        margin: 0 0 1.15rem;
        border: 1px solid #d5e8e4;
        border-left: 4px solid #1b8279;
        border-radius: 11px;
        background: linear-gradient(90deg, #eaf5f2, #f8fbfa);
        color: #315d5a;
        font-size: .9rem;
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
        font-size: .78rem;
        font-weight: 760;
        letter-spacing: .14em;
        text-transform: uppercase;
        margin-bottom: .35rem;
    }
    .lp-subtitle {
        color: #627779;
        font-size: 1rem;
        max-width: 58rem;
        margin: .1rem 0 1rem;
    }
    .lp-pipeline-card {
        min-height: 5.25rem;
        padding: .65rem .6rem;
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
        font-size: .85rem;
        font-weight: 740;
        letter-spacing: .045em;
        text-transform: uppercase;
    }
    .lp-pipeline-card.is-done .lp-pipeline-state { color: #167b64; }
    .lp-pipeline-card.is-ready .lp-pipeline-state { color: #08736d; }
    .lp-pipeline-label {
        margin-top: .4rem;
        color: #183e3f;
        font-size: .9rem;
        font-weight: 660;
        line-height: 1.25;
    }
    .lp-stage-state {
        font-size: .82rem;
        font-weight: 650;
        color: #355a59;
        line-height: 1.2;
    }
    .lp-stage-label {
        margin-top: .25rem;
        font-size: .82rem;
        color: #536c6d;
        line-height: 1.25;
        overflow-wrap: anywhere;
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


def format_datetime(value: object) -> str:
    """Format ISO timestamps as a short local-style date and 12-hour time."""
    from datetime import datetime

    if value is None or str(value).strip().casefold() in {
        "",
        "nan",
        "nat",
        "none",
        "<na>",
    }:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return parsed.strftime("%d %b %Y, %I:%M %p").replace(" 0", " ")


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
