"""Credential loading and password hash verification."""

from collections.abc import Mapping
import hashlib
import hmac
import json
import os
import secrets
from typing import Any


def _read_auth_secrets() -> tuple[dict[str, Any], str | None]:
    """Return the auth section and a safe configuration error, if malformed."""
    try:
        import streamlit as st

        secrets_config = st.secrets
    except (FileNotFoundError, RuntimeError):
        return {}, None
    value = secrets_config.get("auth", {})
    if not isinstance(value, Mapping):
        return {}, "The auth section in Streamlit secrets must be a table."
    return dict(value), None


def _secret_auth() -> dict[str, Any]:
    """Return Streamlit auth configuration when secrets are available."""
    return _read_auth_secrets()[0]


def _normalize_users(
    users: Mapping[str, Any],
) -> tuple[list[dict[str, str]], str | None]:
    """Normalize credential records and validate their shape without exposing values."""
    result = []
    for username, user in users.items():
        if not isinstance(user, Mapping):
            return [], "A configured auth user must be a table."
        candidate = {
            "username": str(username).strip(),
            **{
                key: str(user.get(key, "")).strip()
                for key in ("display_name", "email", "role", "password_hash")
            },
        }
        if not all(candidate.values()):
            return [], "A configured auth user is missing required fields."
        if not is_valid_password_hash(candidate["password_hash"]):
            return [], "A configured auth password hash is malformed."
        result.append(candidate)
    if not result:
        return [], "No username/password users are configured."
    return result, None


def _load_users() -> tuple[list[dict[str, str]], str | None]:
    """Load users from Streamlit secrets or the supported environment fallback."""
    auth, secrets_error = _read_auth_secrets()
    if secrets_error:
        return [], secrets_error
    users = auth.get("users", {})
    if users:
        if not isinstance(users, Mapping):
            return [], "The auth.users setting must contain username tables."
        return _normalize_users(users)

    raw_users = os.getenv("LOANPILOT_AUTH_USERS", "")
    if not raw_users:
        return [], "No username/password users are configured."
    try:
        parsed = json.loads(raw_users)
    except json.JSONDecodeError:
        return [], "LOANPILOT_AUTH_USERS is not valid JSON."
    if not isinstance(parsed, Mapping):
        return [], "LOANPILOT_AUTH_USERS must be a username-to-user mapping."
    return _normalize_users(parsed)


def configured_users() -> list[dict[str, str]]:
    """Read valid users only from Streamlit secrets or environment JSON."""
    return _load_users()[0]


def credential_configuration_error() -> str | None:
    """Describe missing or invalid credential setup without exposing secret values."""
    return _load_users()[1]


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


def is_valid_password_hash(encoded_hash: str) -> bool:
    """Check the supported scrypt encoding without attempting password verification."""
    try:
        algorithm, salt_hex, digest_hex = encoded_hash.split("$", 2)
        salt = bytes.fromhex(salt_hex)
        digest = bytes.fromhex(digest_hex)
    except (AttributeError, ValueError):
        return False
    return algorithm == "scrypt" and len(salt) == 16 and len(digest) == 64


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password hash without timing-sensitive digest comparison."""
    if not is_valid_password_hash(encoded_hash):
        return False
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
