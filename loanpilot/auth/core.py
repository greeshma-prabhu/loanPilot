"""Credential loading and password hash verification."""

import hashlib
import hmac
import json
import os
import secrets
from typing import Any


def _secret_auth() -> dict[str, Any]:
    """Return Streamlit auth configuration when secrets are available."""
    try:
        import streamlit as st

        value = st.secrets.get("auth", {})
    except (FileNotFoundError, RuntimeError):
        value = {}
    return dict(value) if hasattr(value, "items") else {}


def configured_users() -> list[dict[str, str]]:
    """Read users only from Streamlit secrets or an environment JSON setting."""
    auth = _secret_auth()
    users = auth.get("users", {})
    result = []
    if hasattr(users, "items"):
        for username, user in users.items():
            if hasattr(user, "items"):
                result.append({"username": str(username), **{
                    key: str(user.get(key, ""))
                    for key in ("display_name", "email", "role", "password_hash")
                }})
    if result:
        return result
    raw_users = os.getenv("LOANPILOT_AUTH_USERS", "")
    if not raw_users:
        return []
    try:
        parsed = json.loads(raw_users)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []
    return [
        {"username": str(username), **{
            key: str(user.get(key, ""))
            for key in ("display_name", "email", "role", "password_hash")
        }}
        for username, user in parsed.items()
        if isinstance(user, dict)
    ]


def demo_access_enabled() -> bool:
    """Return whether demo access is explicitly enabled in config."""
    value = _secret_auth().get("demo_enabled")
    if value is None:
        value = os.getenv("LOANPILOT_AUTH_DEMO_ENABLED")
    if value is None:
        return True
    return str(value).strip().casefold() in {"true", "1", "yes", "on"}


def make_password_hash(password: str, *, salt: bytes | None = None) -> str:
    """Create a salted scrypt hash in a pasteable, versioned text format."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password hash without timing-sensitive digest comparison."""
    try:
        algorithm, salt_hex, digest_hex = encoded_hash.split("$", 2)
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=2**14,
            r=8,
            p=1,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
