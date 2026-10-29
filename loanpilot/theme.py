"""Shared visual elements for LoanPilot pages."""

import streamlit as st

from loanpilot.badges import implementation_badge
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore

_CSS = """
<style>
    html, body {
        width: 100% !important;
        max-width: 100% !important;
        overflow-x: hidden !important;
    }
    [data-testid="stAppViewContainer"] {
        width: 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
        overflow-x: hidden !important;
    }
    [data-testid="stMainBlockContainer"] {
        width: 100% !important;
        max-width: 1280px !important;
        min-width: 0 !important;
    }
    [data-testid="stMain"] {
        flex: 1 1 auto !important;
        width: 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
    }
    [data-testid="stHorizontalBlock"],
    [data-testid="stColumn"] {
        min-width: 0 !important;
    }
    [class*="st-key-hr-decided-"] {
        border-radius: 10px;
        background: rgba(243, 247, 248, .78);
        padding: .15rem .3rem;
    }
    [class*="st-key-hr-reason-"] {
        border: 2px solid #d59a36;
        background: #fffaf0;
        padding: .75rem;
        border-radius: 12px;
    }
    [class*="st-key-review-count-total"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: #ffffff;
        border-color: #dfe5e8;
    }
    [class*="st-key-review-count-pending"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: #fffaf3;
        border-color: #f6d7b5;
    }
    [class*="st-key-review-count-approved"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: #f6fff9;
        border-color: #cfead8;
    }
    [class*="st-key-review-count-rejected"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: #fff7f6;
        border-color: #efcfcb;
    }
    :root {
        --lp-ink: #24333a;
        --lp-muted: #68777d;
        --lp-teal: #138b83;
        --lp-line: #e1e7e9;
        --lp-canvas: #ffffff;
    }
    .stApp {
        background: var(--lp-canvas);
        color: var(--lp-ink);
    }
    [data-testid="stHeader"] {
        background: rgba(255, 255, 255, .92);
        backdrop-filter: blur(12px);
    }
    [data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid #e1e7e9;
    }
    [data-testid="stSidebar"] * { color: #24333a; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #68777d; }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a {
        border-radius: 10px;
        margin: 3px 0;
        border: 1px solid transparent;
        transition: background .18s ease, transform .18s ease;
    }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {
        background: #f4f7f8;
        border-color: #e1e7e9;
        transform: translateX(2px);
    }
    [data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] {
        background: #edf5f4;
        border-color: #c9e2df;
        box-shadow: inset 3px 0 #138b83;
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {
        background: transparent;
        border-color: #d7e0e3;
        color: #34454c;
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
        color: #11776f;
        background: #eef7f6;
    }
    [data-testid="stTabs"] [data-testid="stVerticalBlock"] { gap: .7rem; }
    [data-testid="stProgress"] > div > div > div { background: #138b83; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        font-size: 14px;
    }
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
        font-size: 14px;
        color: #68777d;
    }
    .lp-sidebar-brand {
        display: flex;
        flex-direction: column;
        color: #2a2a2a;
        font-size: 1.12rem;
        font-weight: 720;
        letter-spacing: -.01em;
        margin: .2rem 0 1.2rem;
        padding: .8rem .75rem;
        border: 1px solid #e1e7e9;
        border-radius: 14px;
        background: #ffffff;
        box-shadow: 0 4px 14px rgba(20, 59, 60, .04);
    }
    .lp-sidebar-brand span {
        color: #68777d;
        font-size: .88rem;
        font-weight: 550;
        letter-spacing: 0;
    }
    .lp-sidebar-section {
        margin: .9rem .25rem .25rem;
        color: #45646a;
        font-size: .74rem;
        font-weight: 750;
        letter-spacing: .1em;
        text-transform: uppercase;
    }
    [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover {
        background: #eef7f6;
        border-color: #c9e2df;
        color: #255a56;
    }
    input, textarea, [data-baseweb="select"] > div {
        border-color: #cbd6da !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stExpander"],
    [data-testid="stDataFrame"],
    [data-testid="stTable"] {
        border-color: #dbe3e6;
    }
    [data-testid="stSegmentedControl"] button[aria-pressed="true"] {
        background: #138b83 !important;
        color: #fff !important;
        border-color: #0e756f !important;
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
        color: #24333a;
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
    button[data-testid="stBaseButton-primary"] {
        background: linear-gradient(120deg, #168f87, #11766f) !important;
        border: 1px solid #0e756f !important;
        color: #fff !important;
        box-shadow: 0 4px 10px rgba(17, 118, 111, .14) !important;
    }
    button[data-testid="stBaseButton-primary"] *,
    button[data-testid="stBaseButton-primary"]:hover {
        color: #fff !important;
    }
    button[data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(120deg, #11766f, #0d625d) !important;
    }
    [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
        background: transparent !important;
        border: 1px solid transparent !important;
        color: #34454c !important;
    }
    [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] * {
        color: #34454c !important;
    }
    .lp-eyebrow { color: #138b83 !important; }
    .lp-subtitle { color: #68777d !important; }
    [data-baseweb="input"] > div,
    [data-baseweb="textarea"] > div,
    [data-baseweb="select"] > div {
        border-color: #cbd6da !important;
    }
    [data-baseweb="input"] > div:focus-within,
    [data-baseweb="textarea"] > div:focus-within,
    [data-baseweb="select"] > div:focus-within {
        border-color: #138b83 !important;
        box-shadow: 0 0 0 3px rgba(19, 139, 131, .16) !important;
    }
</style>
"""


def render_disclaimer() -> None:
    """Apply shared presentation styles without rendering a global banner."""
    st.markdown(_CSS, unsafe_allow_html=True)


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
