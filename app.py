"""LoanPilot Streamlit application entry point."""

import streamlit as st

from loanpilot import config
from loanpilot.badges import render_badge_legend
from loanpilot.data.bootstrap import bootstrap_demo_data
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore
from loanpilot.navigation import NAVIGATION


def main() -> None:
    """Configure navigation and render the selected page."""
    st.set_page_config(page_title=config.APP_NAME, page_icon="🏦", layout="wide")
    store = SQLiteStore()
    if not st.session_state.get("_loanpilot_bootstrapped"):
        with st.spinner("Checking the synthetic demo setup..."):
            bootstrap_status = bootstrap_demo_data(store)
        st.session_state["_loanpilot_bootstrapped"] = True
        if bootstrap_status:
            st.session_state["_loanpilot_bootstrap_notice"] = bootstrap_status

    navigation = st.navigation(NAVIGATION)

    with st.sidebar:
        st.markdown('<div class="lp-sidebar-brand">LoanPilot</div>', unsafe_allow_html=True)
        st.caption(config.BANK_NAME)
        bootstrap_notice = st.session_state.pop(
            "_loanpilot_bootstrap_notice", None
        )
        if bootstrap_notice == "initialized":
            st.success("First-run setup complete. Synthetic cases and sample PDFs are ready.")
        elif bootstrap_notice == "documents_restored":
            st.success("Missing sample documents were restored from synthetic data.")
        with st.expander("Implementation status", expanded=False):
            render_badge_legend()
        if st.button("Reset demo data", width="stretch", help="Restore the synthetic sample cases."):
            counts = seed_demo_data(store, reset=True)
            count_text = ", ".join(
                f"{table}: {count}" for table, count in counts.items()
            )
            st.toast(f"Demo data reset. {count_text}")

    navigation.run()


if __name__ == "__main__":
    main()
