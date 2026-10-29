"""LoanPilot Streamlit application entry point."""

import streamlit as st

from loanpilot import config
from loanpilot.pages import login

LOGIN_PAGE = st.Page(login.render, title="Sign in", url_path="login")


def _sign_out(login_page) -> None:
    """Clear the authenticated identity and return to the sole logged-out route."""
    st.session_state.pop("auth", None)
    st.switch_page(login_page)


def main() -> None:
    """Gate all product navigation behind a session-level sign-in."""
    st.set_page_config(
        page_title=config.APP_NAME,
        page_icon="🏦",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    if not st.session_state.get("auth"):
        from loanpilot import navigation as _navigation

        st.navigation([LOGIN_PAGE], position="hidden").run()
        return

    from loanpilot.data.bootstrap import bootstrap_demo_data
    from loanpilot.data.store import SQLiteStore
    from loanpilot.navigation import KNOW_MORE_PAGES, NAVIGATION, OPERATE_PAGES

    store = SQLiteStore()
    if not st.session_state.get("_loanpilot_bootstrapped"):
        with st.spinner("Checking the synthetic demo setup..."):
            bootstrap_status = bootstrap_demo_data(store)
        st.session_state["_loanpilot_bootstrapped"] = True
        if bootstrap_status:
            st.session_state["_loanpilot_bootstrap_notice"] = bootstrap_status

    navigation_pages = {
        **NAVIGATION,
        "Access": [LOGIN_PAGE],
    }
    navigation = st.navigation(navigation_pages, position="hidden")
    with st.sidebar:
        st.markdown(
            '<div class="lp-sidebar-brand">LoanPilot'
            f'<span>{config.BANK_NAME}</span></div>',
            unsafe_allow_html=True,
        )
        for key in ("overview", "applications", "new_application", "ai_assessment", "human_review"):
            st.page_link(OPERATE_PAGES[key])
        with st.expander("Know more", expanded=False):
            for key, label in (
                ("approach_story", "Approach Story"),
                ("technical_architecture", "Technical Architecture"),
                ("data_explorer", "Data Explorer"),
                ("about_faq", "About & FAQ"),
            ):
                st.page_link(KNOW_MORE_PAGES[key], label=label)
        bootstrap_notice = st.session_state.pop(
            "_loanpilot_bootstrap_notice", None
        )
        if bootstrap_notice == "initialized":
            st.success("First-run setup complete. Synthetic cases and sample PDFs are ready.")
        elif bootstrap_notice == "documents_restored":
            st.success("Missing sample documents were restored from synthetic data.")
        st.button(
            "Sign out",
            key="sign_out",
            on_click=_sign_out,
            args=(LOGIN_PAGE,),
            width="stretch",
        )
    navigation.run()


if __name__ == "__main__":
    main()
