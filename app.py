"""LoanPilot Streamlit application entry point."""

import streamlit as st

from loanpilot import config
from loanpilot.data.bootstrap import bootstrap_demo_data
from loanpilot.data.store import SQLiteStore
from loanpilot.navigation import KNOW_MORE_PAGES, NAVIGATION, OPERATE_PAGES


@st.dialog("Know more")
def _show_know_more() -> None:
    """Offer explanatory pages in a lightweight navigation dialog."""
    st.caption("Explore how this demonstration is designed and what it contains.")
    for key, label in (
        ("approach_story", "Approach Story"),
        ("technical_architecture", "Technical Architecture"),
        ("data_explorer", "Data Explorer"),
        ("about_faq", "About & FAQ"),
    ):
        st.page_link(KNOW_MORE_PAGES[key], label=label, icon="↗")


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

    navigation = st.navigation(NAVIGATION, position="hidden")

    with st.sidebar:
        st.markdown(
            '<div class="lp-sidebar-brand">LoanPilot'
            f'<span>{config.BANK_NAME}</span></div>',
            unsafe_allow_html=True,
        )
        for key in ("overview", "applications", "new_application", "ai_assessment", "human_review"):
            st.page_link(OPERATE_PAGES[key])
        if st.button("Know more", key="open_know_more", type="secondary", width="stretch"):
            _show_know_more()
        bootstrap_notice = st.session_state.pop(
            "_loanpilot_bootstrap_notice", None
        )
        if bootstrap_notice == "initialized":
            st.success("First-run setup complete. Synthetic cases and sample PDFs are ready.")
        elif bootstrap_notice == "documents_restored":
            st.success("Missing sample documents were restored from synthetic data.")
    navigation.run()


if __name__ == "__main__":
    main()
