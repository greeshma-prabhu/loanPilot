"""Authentication, login-gate, and credential utility tests."""

import subprocess
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from loanpilot.auth import core as auth_core
from loanpilot.auth.core import (
    is_valid_password_hash,
    make_password_hash,
    verify_password,
)
from loanpilot.auth import session
from loanpilot.config import PROJECT_ROOT
from loanpilot.pages import login

_TEST_PASSWORD = "loanpilot-" + "test-secret"


def _login_app(users: list[dict[str, str]]) -> AppTest:
    """Render login with one test-local credential and safe navigation stub."""
    digest = make_password_hash(_TEST_PASSWORD)
    test_users = users or [
        {
            "username": "greeshma",
            "display_name": "Greeshma Prabhu",
            "email": "Arambhbank@gmail.com",
            "role": "Credit Analyst",
            "password_hash": digest,
        }
    ]
    script = (
        "import streamlit as st\n"
        "from loanpilot.pages import login\n"
        f"login.configured_users = lambda: {test_users!r}\n"
        "login.credential_configuration_error = lambda: None\n"
        "login.demo_access_enabled = lambda: True\n"
        "login.render()\n"
    )
    return AppTest.from_string(script)


@pytest.mark.parametrize("username", ["Greeshma Prabhu", "arambhBANK@gmail.com"])
def test_credentials_accept_display_name_and_email(username: str) -> None:
    """Credentials match either accepted identifier without case sensitivity."""
    app = _login_app([]).run()
    app.text_input(key="login_username").set_value(username)
    app.text_input(key="login_password").set_value(_TEST_PASSWORD)
    next(button for button in app.button if button.label == "Sign in").click().run()
    assert app.session_state["auth"] == {
        "name": "Greeshma Prabhu",
        "email": "Arambhbank@gmail.com",
        "role": "Credit Analyst",
        "method": "credentials",
    }


def test_credentials_accept_configured_username() -> None:
    """The username key in [auth.users.<username>] is a valid sign-in identifier."""
    app = _login_app([]).run()
    app.text_input(key="login_username").set_value(" GREESHMA ")
    app.text_input(key="login_password").set_value(_TEST_PASSWORD)
    next(button for button in app.button if button.label == "Sign in").click().run()
    assert app.session_state["auth"]["method"] == "credentials"


def test_credential_sign_in_opens_authenticated_dashboard() -> None:
    """Valid username/password submission reaches the product dashboard."""
    user = {
        "username": "greeshma",
        "display_name": "Greeshma Prabhu",
        "email": "analyst@example.test",
        "role": "Credit Analyst",
        "password_hash": make_password_hash(_TEST_PASSWORD),
    }
    script = (
        "import streamlit as st\n"
        "from loanpilot.pages import login\n"
        f"login.configured_users = lambda: {[user]!r}\n"
        "login.credential_configuration_error = lambda: None\n"
        "login.demo_access_enabled = lambda: True\n"
        "from app import main\n"
        "main()\n"
    )
    app = AppTest.from_string(script).run()
    app.text_input(key="login_username").set_value("greeshma")
    app.text_input(key="login_password").set_value(_TEST_PASSWORD)
    next(button for button in app.button if button.label == "Sign in").click().run()

    assert not app.exception
    assert app.session_state["auth"]["method"] == "credentials"
    assert any(element.value == "Overview" for element in app.title)
    assert any(link.label == "Applications" for link in app.get("page_link"))


def test_wrong_password_uses_generic_error() -> None:
    """The login error never identifies whether the name or password was wrong."""
    app = _login_app([]).run()
    app.text_input(key="login_username").set_value("Greeshma Prabhu")
    app.text_input(key="login_password").set_value("incorrect")
    next(button for button in app.button if button.label == "Sign in").click().run()
    assert [item.value for item in app.error] == [
        "Incorrect email, username or password"
    ]
    assert "auth" not in app.session_state


def test_unknown_username_uses_generic_error() -> None:
    """Unknown identifiers receive the same generic response as wrong passwords."""
    app = _login_app([]).run()
    app.text_input(key="login_username").set_value("unknown-user")
    app.text_input(key="login_password").set_value(_TEST_PASSWORD)
    next(button for button in app.button if button.label == "Sign in").click().run()

    assert [item.value for item in app.error] == [
        "Incorrect email, username or password"
    ]
    assert "auth" not in app.session_state


def test_five_failed_attempts_lock_the_credential_form(monkeypatch) -> None:
    """Five bad submissions set a future lockout and hide the credential form."""
    monkeypatch.setattr(login.time, "time", lambda: 1000.0)
    app = _login_app([]).run()
    app.text_input(key="login_username").set_value("Greeshma Prabhu")
    for attempt in range(5):
        app.text_input(key="login_password").set_value(f"bad-{attempt}")
        next(button for button in app.button if button.label == "Sign in").click().run()
    assert app.session_state["auth_failed_attempts"] == 5
    assert app.session_state["auth_locked_until"] == 1060.0
    assert not any(button.label == "Sign in" for button in app.button)
    assert any("60 seconds" in item.value for item in app.warning)


def test_demo_access_sets_guest_identity() -> None:
    """The demo-access callback creates only the documented guest identity."""
    app = _login_app([]).run()
    app.button(key="login_demo_access").click().run()
    assert app.session_state["auth"] == {
        "name": "Demo Analyst",
        "role": "Guest (demo)",
        "method": "demo",
    }


def test_no_configured_user_disables_credentials_with_safe_setup_notice(
    monkeypatch,
) -> None:
    """Missing credentials show a safe setup hint and retain demo access."""
    monkeypatch.setattr(login, "configured_users", lambda: [])
    monkeypatch.setattr(
        login,
        "credential_configuration_error",
        lambda: "No username/password users are configured.",
    )
    monkeypatch.setattr(login, "demo_access_enabled", lambda: True)
    app = AppTest.from_string(
        "from loanpilot.pages.login import render\nrender()\n"
    ).run()
    assert any("Streamlit secrets" in item.value for item in app.warning)
    assert app.text_input(key="login_username").disabled
    assert app.text_input(key="login_password").disabled
    assert next(button for button in app.button if button.label == "Sign in").disabled
    assert any(button.label == "Continue with demo access" for button in app.button)
    assert not any(button.label == "Contact" for button in app.button)
    assert not app.exception


def test_missing_credentials_have_a_distinct_configuration_error(monkeypatch) -> None:
    """Missing auth setup is distinct from an incorrect password."""
    monkeypatch.setattr(auth_core, "_read_auth_secrets", lambda: ({}, None))
    monkeypatch.delenv("LOANPILOT_AUTH_USERS", raising=False)

    assert auth_core.configured_users() == []
    assert auth_core.credential_configuration_error() == (
        "No username/password users are configured."
    )


def test_malformed_password_hash_is_reported_as_configuration_error(
    monkeypatch,
) -> None:
    """Malformed scrypt values are never presented as ordinary bad credentials."""
    monkeypatch.setattr(
        auth_core,
        "_read_auth_secrets",
        lambda: (
            {
                "users": {
                    "analyst": {
                        "display_name": "Test Analyst",
                        "email": "analyst@example.test",
                        "role": "Credit Analyst",
                        "password_hash": "scrypt$not-a-salt$not-a-digest",
                    }
                }
            },
            None,
        ),
    )
    monkeypatch.delenv("LOANPILOT_AUTH_USERS", raising=False)

    assert auth_core.configured_users() == []
    assert auth_core.credential_configuration_error() == (
        "A configured auth password hash is malformed."
    )
    assert not is_valid_password_hash("scrypt$not-a-salt$not-a-digest")
    assert not verify_password(_TEST_PASSWORD, "scrypt$not-a-salt$not-a-digest")


def test_sign_out_returns_to_login_page() -> None:
    """The sign-out callback clears identity and routes to the login page."""
    script = (
        "import streamlit as st\n"
        "from app import LOGIN_PAGE, _sign_out\n"
        "from loanpilot.pages import login\n"
        "login.configured_users = lambda: []\n"
        "login.demo_access_enabled = lambda: True\n"
        "overview = st.Page(lambda: st.write('Overview'), title='Overview', default=True)\n"
        "nav = st.navigation({'Operate': [overview], 'Access': [LOGIN_PAGE]}, position='hidden')\n"
        "if st.session_state.get('auth'):\n"
        "    st.button('Sign out', on_click=_sign_out, args=(LOGIN_PAGE,))\n"
        "else:\n"
        "    login.render()\n"
        "nav.run()\n"
    )
    app = AppTest.from_string(script)
    app.session_state["auth"] = {
        "name": "Test Analyst",
        "role": "Credit Analyst",
        "method": "credentials",
    }
    app.run()
    app.button[0].click().run()
    assert "auth" not in app.session_state
    assert app.session_state["_auth_cookie_action"] == "delete"
    assert any(button.label == "Continue with demo access" for button in app.button)


def test_password_hash_cli_output_is_verifiable(monkeypatch, capsys) -> None:
    """The interactive hash utility outputs a usable hash without the password."""
    from loanpilot.auth import make_hash

    responses = iter([_TEST_PASSWORD, _TEST_PASSWORD])
    monkeypatch.setattr(make_hash, "getpass", lambda _prompt: next(responses))
    make_hash.main()
    output = capsys.readouterr().out.strip()
    encoded = output.split('"', 2)[1]
    assert output.startswith('password_hash = "scrypt$')
    assert verify_password(_TEST_PASSWORD, encoded)
    assert _TEST_PASSWORD not in output


def test_signed_session_token_survives_refresh_and_expires(monkeypatch) -> None:
    """Signed sessions restore the configured identity until their seven-day expiry."""
    user = {
        "username": "greeshma",
        "display_name": "Greeshma Prabhu",
        "email": "Arambhbank@gmail.com",
        "role": "Credit Analyst",
        "password_hash": make_password_hash(_TEST_PASSWORD),
    }
    monkeypatch.setattr(session, "_signing_key", lambda: b"test session signing key")
    monkeypatch.setattr(session, "configured_users", lambda: [user])
    auth = {
        "name": user["display_name"],
        "email": user["email"],
        "role": user["role"],
        "method": "credentials",
    }

    token = session.create_session_token(auth, now=1_000)

    assert session.restore_session_token(token, now=1_001) == auth
    assert session.restore_session_token(
        token, now=1_000 + session.SESSION_SECONDS
    ) is None


def test_signed_session_token_rejects_tampering_and_revoked_users(monkeypatch) -> None:
    """Cookie edits and removed account credentials cannot restore a session."""
    user = {
        "username": "greeshma",
        "display_name": "Greeshma Prabhu",
        "email": "Arambhbank@gmail.com",
        "role": "Credit Analyst",
        "password_hash": make_password_hash(_TEST_PASSWORD),
    }
    monkeypatch.setattr(session, "_signing_key", lambda: b"test session signing key")
    monkeypatch.setattr(session, "configured_users", lambda: [user])
    auth = {
        "name": user["display_name"],
        "email": user["email"],
        "role": user["role"],
        "method": "credentials",
    }
    token = session.create_session_token(auth, now=1_000)

    assert session.restore_session_token(token + "x", now=1_001) is None
    monkeypatch.setattr(session, "configured_users", lambda: [])
    assert session.restore_session_token(token, now=1_001) is None


def test_cookie_gate_restores_identity_after_refresh_and_navigation() -> None:
    """The app cookie gate restores identity after session state is recreated."""
    script = (
        "import streamlit as st\n"
        "from app import _sync_auth_cookie\n"
        "from loanpilot.auth import session\n"
        "session.demo_access_enabled = lambda: True\n"
        "class FakeCookieManager:\n"
        "    def __init__(self):\n"
        "        self.cookies = st.session_state.setdefault('browser_cookies', {})\n"
        "    def get(self, name):\n"
        "        return self.cookies.get(name)\n"
        "    def set(self, name, value, **kwargs):\n"
        "        self.cookies[name] = value\n"
        "    def delete(self, name, **kwargs):\n"
        "        self.cookies.pop(name, None)\n"
        "manager = FakeCookieManager()\n"
        "_sync_auth_cookie(manager, request_cookies=dict(manager.cookies), request_url='https://loanpilot.test')\n"
        "def sign_in():\n"
        "    st.session_state['auth'] = {'name': 'Demo Analyst', 'role': 'Guest (demo)', 'method': 'demo'}\n"
        "    st.session_state['_auth_cookie_action'] = 'set'\n"
        "if st.session_state.get('auth'):\n"
        "    st.selectbox('Page', ['Overview', 'Applications'], key='test_page')\n"
        "    st.write(st.session_state['auth']['name'])\n"
        "else:\n"
        "    st.button('Sign in', on_click=sign_in)\n"
    )
    app = AppTest.from_string(script).run()
    app.button[0].click().run()
    assert app.session_state["auth"]["name"] == "Demo Analyst"
    assert app.session_state["browser_cookies"]

    app.selectbox(key="test_page").select("Applications").run()
    assert app.session_state["auth"]["name"] == "Demo Analyst"

    # A browser refresh creates fresh Streamlit session state but sends its cookie.
    del app.session_state["auth"]
    app.run()
    assert app.session_state["auth"]["name"] == "Demo Analyst"


def test_repository_has_no_embedded_password_or_default_scrypt_hash() -> None:
    """Tracked runtime files contain no committed usable credential material."""
    tracked = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    forbidden_hash = 'password_hash = "scrypt$'
    for relative in tracked:
        if relative.replace("\\", "/") == "tests/test_auth.py":
            continue
        path = PROJECT_ROOT / Path(relative)
        if path.suffix not in {".py", ".toml", ".json", ".md"} or not path.is_file():
            continue
        assert forbidden_hash not in path.read_text(
            encoding="utf-8", errors="ignore"
        ), f"Embedded password hash in {relative}"
