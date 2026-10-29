"""Signed browser-cookie sessions for refresh-safe demo sign-in."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from loanpilot.auth.core import _secret_auth, configured_users, demo_access_enabled

AUTH_COOKIE_NAME = "loanpilot_auth"
SESSION_SECONDS = 7 * 24 * 60 * 60
_PROCESS_SECRET = secrets.token_bytes(32)


def _signing_key() -> bytes:
    """Derive a stable signing key from configured secrets or credential hashes."""
    auth = _secret_auth()
    secret = str(
        auth.get("session_secret")
        or os.getenv("LOANPILOT_AUTH_SESSION_SECRET")
        or ""
    ).strip()
    if secret and not secret.startswith("REPLACE_WITH_"):
        material = secret.encode("utf-8")
    else:
        users = configured_users()
        hashes = sorted(
            user.get("password_hash", "")
            for user in users
            if user.get("password_hash", "")
        )
        material = (
            "\n".join(hashes).encode("utf-8")
            if hashes
            else _PROCESS_SECRET
        )
    return hashlib.sha256(b"LoanPilot session v1\0" + material).digest()


def create_session_token(auth: dict[str, Any], *, now: int | None = None) -> str:
    """Create a tamper-evident token containing only a minimal identity and expiry."""
    payload = {
        "auth": {
            key: str(auth[key])
            for key in ("name", "email", "role", "method")
            if key in auth
        },
        "exp": (int(time.time()) if now is None else now) + SESSION_SECONDS,
        "v": 1,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(_signing_key(), encoded.encode("ascii"), hashlib.sha256)
    signed = base64.urlsafe_b64encode(signature.digest()).decode("ascii").rstrip("=")
    return f"{encoded}.{signed}"


def restore_session_token(token: str, *, now: int | None = None) -> dict[str, str] | None:
    """Validate a cookie token and confirm its identity is still configured."""
    if not token or len(token) > 4096:
        return None
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(
            _signing_key(), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        signature = base64.urlsafe_b64decode(
            supplied_signature + "=" * (-len(supplied_signature) % 4)
        )
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        )
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    current_time = int(time.time()) if now is None else now
    if not isinstance(payload, dict) or payload.get("v") != 1:
        return None
    if not isinstance(payload.get("exp"), int) or payload["exp"] <= current_time:
        return None
    auth = payload.get("auth")
    if not isinstance(auth, dict):
        return None
    if not all(isinstance(auth.get(field), str) and auth[field] for field in ("name", "role")):
        return None

    method = auth.get("method")
    if method == "demo":
        if not demo_access_enabled():
            return None
        return {key: auth[key] for key in ("name", "role", "method")}
    if method != "credentials" or not auth.get("email"):
        return None

    user = next(
        (
            candidate
            for candidate in configured_users()
            if candidate.get("email", "").casefold()
            == auth["email"].casefold()
            and candidate.get("display_name") == auth["name"]
            and candidate.get("role") == auth["role"]
        ),
        None,
    )
    if user is None:
        return None
    return {
        "name": user["display_name"],
        "email": user["email"],
        "role": user["role"],
        "method": "credentials",
    }
