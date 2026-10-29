"""Login page for the fictional Aarambh Bank demo workspace."""

import time

import streamlit as st

from loanpilot.auth import (
    configured_users,
    credential_configuration_error,
    demo_access_enabled,
    verify_password,
)
from loanpilot.theme import bank_logo_data_uri, render_login_styles


def _show_forgot_password() -> None:
    """Explain the demo password recovery path."""
    st.toast("Contact your administrator (demo)")


def _sign_in_demo() -> None:
    """Start an explicitly configured demo-access session."""
    st.session_state.pop("_signed_out", None)
    st.session_state["auth"] = {
        "name": "Demo Analyst",
        "role": "Guest (demo)",
        "method": "demo",
    }
    st.session_state["_auth_cookie_action"] = "set"
    st.toast("Welcome back, Demo")


def _credential_sign_in() -> None:
    """Check submitted credentials and apply the session lockout policy."""
    now = time.time()
    if now < float(st.session_state.get("auth_locked_until", 0)):
        return
    username = str(st.session_state.get("login_username", "")).strip().casefold()
    password = str(st.session_state.get("login_password", ""))
    user = next(
        (
            candidate
            for candidate in configured_users()
            if username
            in {
                candidate.get(identifier, "").strip().casefold()
                for identifier in ("username", "display_name", "email")
            }
        ),
        None,
    )
    if user and verify_password(password, user.get("password_hash", "")):
        st.session_state.pop("_signed_out", None)
        st.session_state["auth"] = {
            "name": user["display_name"],
            "email": user["email"],
            "role": user["role"],
            "method": "credentials",
        }
        st.session_state["_auth_cookie_action"] = "set"
        st.session_state["auth_failed_attempts"] = 0
        st.session_state.pop("auth_locked_until", None)
        st.session_state["login_error"] = ""
        st.session_state["login_password"] = ""
        st.toast(f"Welcome back, {user['display_name'].split()[0]}")
        return

    attempts = int(st.session_state.get("auth_failed_attempts", 0)) + 1
    st.session_state["auth_failed_attempts"] = attempts
    st.session_state["login_error"] = "Incorrect email, username or password"
    if attempts >= 5:
        st.session_state["auth_locked_until"] = now + 60
    st.session_state["login_password"] = ""


def _render_lockout() -> None:
    """Render a one-second-updating lockout countdown."""
    @st.fragment(run_every=1)
    def countdown() -> None:
        remaining = max(
            0,
            int(float(st.session_state.get("auth_locked_until", 0)) - time.time() + 0.999),
        )
        if remaining:
            st.warning(f"Too many attempts. Try again in {remaining} seconds.")
        else:
            st.session_state["auth_failed_attempts"] = 0
            st.session_state.pop("auth_locked_until", None)
            st.info("Sign-in is available again.")

    countdown()


def render() -> None:
    """Render an isolated credential form with optional demo access."""
    render_login_styles()
    users = configured_users()
    configuration_error = credential_configuration_error()
    credentials_configured = bool(users) and configuration_error is None
    with st.container(key="login-card"):
        st.markdown(
            f"""
            <div class="lp-login-brand">
              <img src="{bank_logo_data_uri()}" alt="" aria-hidden="true">
              <div class="lp-login-brand-copy">
                <span class="lp-login-bank-name">Aarambh Bank</span>
                <span class="lp-login-product-name">LoanPilot</span>
                <span class="lp-login-tagline">AI-Powered Lending Assistant</span>
              </div>
            </div>
            <h1 class="lp-login-title">Welcome back</h1>
            <p class="lp-login-subtitle">Sign in to your intelligent lending workspace.</p>
            """,
            unsafe_allow_html=True,
        )
        if configuration_error:
            st.warning(
                "Username/password sign-in is unavailable. Check the "
                "[auth.users.<username>] configuration in Streamlit secrets."
            )
        if st.session_state.get("login_error"):
            st.error(st.session_state["login_error"])
        locked = time.time() < float(st.session_state.get("auth_locked_until", 0))
        if locked:
            _render_lockout()
        else:
            with st.form("login_form", clear_on_submit=False):
                st.text_input(
                    "Email or username",
                    key="login_username",
                    disabled=not credentials_configured,
                    placeholder="Email or username",
                )
                st.text_input(
                    "Password",
                    type="password",
                    key="login_password",
                    disabled=not credentials_configured,
                    placeholder="Password",
                )
                st.form_submit_button(
                    "Sign in",
                    on_click=_credential_sign_in,
                    disabled=not credentials_configured or locked,
                    type="primary",
                    width="stretch",
                )
            st.button(
                "Forgot password?",
                key="login_forgot_password",
                on_click=_show_forgot_password,
                type="tertiary",
            )
        st.markdown(
            '<div class="lp-login-divider"><span>or</span></div>',
            unsafe_allow_html=True,
        )
        st.button(
            "Continue with demo access",
            key="login_demo_access",
            on_click=_sign_in_demo,
            disabled=not demo_access_enabled(),
            type="secondary",
            width="stretch",
        )
