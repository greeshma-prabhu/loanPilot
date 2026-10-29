"""LoanPilot Streamlit application entry point."""

from datetime import datetime, timedelta, timezone

import extra_streamlit_components as stx
import streamlit as st

from loanpilot import config
from loanpilot.auth.session import (
    AUTH_COOKIE_NAME,
    SESSION_SECONDS,
    create_session_token,
    restore_session_token,
)
from loanpilot.pages import login
from loanpilot.navigation import KNOW_MORE_PAGES, NAVIGATION, OPERATE_PAGES

LOGIN_PAGE = st.Page(login.render, title="Sign in", url_path="login")


def _sync_auth_cookie(cookie_manager) -> None:
    """Persist explicit sign-in and restore authenticated identity after refresh."""
    action = st.session_state.pop("_auth_cookie_action", None)
    secure_cookie = str(getattr(st.context, "url", "")).startswith("https://")
    if action == "set" and st.session_state.get("auth"):
        cookie_manager.set(
            AUTH_COOKIE_NAME,
            create_session_token(st.session_state["auth"]),
            key="set_loanpilot_auth",
            path="/",
            max_age=SESSION_SECONDS,
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=SESSION_SECONDS),
            secure=secure_cookie,
            same_site="lax",
        )
        return
    if action == "delete":
        _delete_auth_cookie(cookie_manager)
        return
    if st.session_state.get("auth"):
        return

    token = st.context.cookies.get(AUTH_COOKIE_NAME)
    if token:
        restored = restore_session_token(str(token))
        if restored:
            st.session_state["auth"] = restored
        else:
            _delete_auth_cookie(cookie_manager)


def _delete_auth_cookie(cookie_manager) -> None:
    """Remove the persistent session token from the browser."""
    cookie_manager.cookies.setdefault(AUTH_COOKIE_NAME, "")
    cookie_manager.delete(AUTH_COOKIE_NAME, key="delete_loanpilot_auth")


def _sign_out(login_page) -> None:
    """Clear identity, expire the browser token, and switch to login."""
    st.session_state.pop("auth", None)
    st.session_state["_auth_cookie_action"] = "delete"
    st.switch_page(login_page)


def main() -> None:
    """Gate all product navigation behind a session-level sign-in."""
    st.set_page_config(
        page_title=config.APP_NAME,
        page_icon="🏦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    cookie_manager = stx.CookieManager(key="loanpilot_auth_cookie_manager")
    _sync_auth_cookie(cookie_manager)
    if not st.session_state.get("auth"):
        login.render()
        return

    from loanpilot.data.schema import create_schema
    from loanpilot.data.store import SQLiteStore
    navigation_pages = {
        **NAVIGATION,
        "Access": [LOGIN_PAGE],
    }
    navigation = st.navigation(navigation_pages, position="hidden")

    store = SQLiteStore()
    create_schema(store)

    with st.sidebar:
        with st.container(key="sidebar-layout"):
            with st.container(key="sidebar-nav"):
                st.markdown(
                    '<div class="lp-sidebar-brand">LoanPilot'
                    f'<span>{config.BANK_NAME}</span></div>',
                    unsafe_allow_html=True,
                )
                for key in OPERATE_PAGES:
                    st.page_link(OPERATE_PAGES[key])
            with st.container(key="sidebar-sign-out-area"):
                with st.expander("Know More", expanded=False):
                    for key, label in (
                        ("approach_story", "Approach Story"),
                        ("technical_architecture", "Technical Architecture"),
                        ("data_explorer", "Data Explorer"),
                        ("about_faq", "About & FAQ"),
                    ):
                        st.page_link(KNOW_MORE_PAGES[key], label=label)
                st.button(
                    "Sign out",
                    key="sign_out",
                    on_click=_sign_out,
                    args=(LOGIN_PAGE,),
                    type="primary",
                    width="stretch",
                )
    navigation.run()


if __name__ == "__main__":
    main()
