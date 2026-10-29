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
from loanpilot import navigation as page_navigation
from loanpilot.theme import render_active_navigation_style, render_sidebar_brand

LOGIN_PAGE = st.Page(login.render, title="Sign in", url_path="login")


def _sync_auth_cookie(
    cookie_manager,
    *,
    request_cookies=None,
    request_url: str | None = None,
) -> None:
    """Persist explicit sign-in and restore authenticated identity after refresh."""
    action = st.session_state.pop("_auth_cookie_action", None)
    context = st.context
    if request_cookies is None:
        request_cookies = getattr(context, "cookies", {})
    if action == "set" and st.session_state.get("auth"):
        current_url = request_url or str(getattr(context, "url", ""))
        secure_cookie = current_url.startswith("https://")
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

    # st.context.cookies is populated from the HTTP request and is authoritative
    # after refresh. CookieManager's component value is a compatibility fallback
    # for Streamlit releases where request cookies are not exposed consistently.
    token = request_cookies.get(AUTH_COOKIE_NAME)
    if not token:
        token = cookie_manager.get(AUTH_COOKIE_NAME)
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
    global LOGIN_PAGE
    st.set_page_config(
        page_title=config.APP_NAME,
        page_icon=str(config.BANK_LOGO_PATH),
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
    operate_pages, know_more_pages, page_groups = page_navigation.build_navigation()
    LOGIN_PAGE = st.Page(login.render, title="Sign in", url_path="login")
    navigation_pages = {
        **page_groups,
        "Access": [LOGIN_PAGE],
    }
    navigation = st.navigation(navigation_pages, position="hidden")

    store = SQLiteStore()
    create_schema(store)

    with st.sidebar:
        render_active_navigation_style(navigation.url_path)
        with st.container(key="sidebar-layout"):
            with st.container(key="sidebar-nav"):
                render_sidebar_brand(config.BANK_NAME)
                page_icons = {
                    "overview": ":material/space_dashboard:",
                    "applications": ":material/folder_open:",
                    "new_application": ":material/add_circle:",
                    "ai_assessment": ":material/psychology:",
                    "human_review": ":material/rate_review:",
                    "document_library": ":material/description:",
                    "guided_demo": ":material/play_circle:",
                }
                for key, page in operate_pages.items():
                    st.page_link(page, icon=page_icons[key])
            with st.container(key="sidebar-sign-out-area"):
                with st.expander("Know More", expanded=False):
                    know_more = (
                        ("approach_story", "Approach Story", ":material/lightbulb:"),
                        (
                            "technical_architecture",
                            "Technical Architecture",
                            ":material/account_tree:",
                        ),
                        ("data_explorer", "Data Explorer", ":material/query_stats:"),
                        ("about_faq", "About & FAQ", ":material/info:"),
                    )
                    for key, label, icon in know_more:
                        st.page_link(know_more_pages[key], label=label, icon=icon)
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
