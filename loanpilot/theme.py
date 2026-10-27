"""Shared visual elements for LoanPilot pages."""

import streamlit as st

from loanpilot.badges import implementation_badge
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore

_CSS = """
<style>
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
        border: 1px solid #dce7e5;
        border-radius: 0.65rem;
        background: #ffffff;
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
        '<div class="loanpilot-banner">Demonstration with synthetic data. '
        "Not a real bank system or credit decision.</div>",
        unsafe_allow_html=True,
    )


def render_header(title: str, purpose: str) -> None:
    """Render a page title and its one-line purpose."""
    st.title(title)
    st.write(purpose)


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
