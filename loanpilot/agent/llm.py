"""Gemini text generation with validated JSON, DB cache, and recorded replay."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from loanpilot.config import AGENT_RECORDED_DIR, GEMINI_MODEL
from loanpilot.data.queries import get_llm_cache, save_llm_cache
from loanpilot.data.store import SQLiteStore

LOGGER = logging.getLogger(__name__)
LIVE_MODE = "Live Gemini"
RECORDED_MODE = "Recorded (pre-written sample)"


def recorded_mode_label(generated_by: str | None) -> str:
    """Describe whether a replay was authored as a sample or captured live."""
    if generated_by and generated_by.casefold().startswith("live run "):
        return f"Recorded ({generated_by})"
    return RECORDED_MODE


class InvalidLLMJSON(ValueError):
    """Raised when the model response is not a JSON object."""


class GeminiUnavailableError(RuntimeError):
    """Raised when an on-demand Gemini operation cannot be completed."""


def _api_key() -> str | None:
    """Read the Gemini key from the environment, then Streamlit secrets."""
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY")
        return str(secret_key) if secret_key else None
    except Exception:
        LOGGER.info("Gemini secrets are unavailable; using recorded mode.")
        return None


def _recorded_payload(persona_key: str | None) -> dict[str, Any]:
    """Read one synthetic persona's replayable language-model output."""
    if not persona_key:
        return {}
    path = Path(AGENT_RECORDED_DIR) / f"{persona_key.lower()}.json"
    if not path.is_file():
        return {}
    try:
        with path.open(encoding="utf-8") as recorded_file:
            result = json.load(recorded_file)
        if not isinstance(result, dict):
            raise InvalidLLMJSON("Recorded replay must contain a JSON object")
        return result
    except (OSError, json.JSONDecodeError, InvalidLLMJSON) as error:
        LOGGER.warning("Could not read recorded output %s: %s", path, error)
        return {}


def _generate_json(
    prompt: str,
    api_key: str,
    *,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Call Gemini and require a JSON object response."""
    from google import genai
    from google.genai import types

    options = (
        {"http_options": types.HttpOptions(timeout=timeout_ms)}
        if timeout_ms is not None
        else {}
    )
    client = genai.Client(api_key=api_key, **options)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    text = response.text
    if not text:
        raise InvalidLLMJSON("Gemini returned an empty response")
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise InvalidLLMJSON("Gemini response was not valid JSON") from error
    if not isinstance(result, dict):
        raise InvalidLLMJSON("Gemini response must be a JSON object")
    return result


def generate_json_with_gemini(
    prompt: str,
    *,
    timeout_ms: int = 20_000,
) -> dict[str, Any]:
    """Generate grounded JSON using the configured Gemini model and key."""
    api_key = _api_key()
    if not api_key:
        raise GeminiUnavailableError("Gemini is not configured.")
    return _generate_json(prompt, api_key, timeout_ms=timeout_ms)


def extract_identity_holder_name(content: bytes, mime_type: str) -> dict[str, str] | None:
    """Extract a holder name and optional PAN identifier from synthetic identity evidence."""
    api_key = _api_key()
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                "Read the holder's full name only from this synthetic identity document. "
                "Return JSON with holder_name (string or null) and pan_number (string or null). "
                "Do not infer missing text.",
                types.Part.from_bytes(data=content, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        if not response.text:
            return None
        payload = json.loads(response.text)
        if not isinstance(payload, dict):
            return None
        name = payload.get("holder_name")
        pan_number = payload.get("pan_number")
        if not isinstance(name, str) or not name.strip():
            return None
        return {
            "holder_name": name.strip(),
            "pan_number": pan_number.strip() if isinstance(pan_number, str) else "",
        }
    except Exception as error:
        LOGGER.warning(
            "Identity document extraction failed (%s).",
            type(error).__name__,
        )
        return None


def run_json_step(
    application_id: str,
    step: str,
    prompt: str,
    persona_key: str | None,
    store: SQLiteStore,
) -> tuple[dict[str, Any] | None, str]:
    """Return cached, live, or recorded structured output for one agent step."""
    cached = get_llm_cache(application_id, step, store)
    if not cached.empty:
        row = cached.iloc[0]
        try:
            response = json.loads(row["response_json"])
            if isinstance(response, dict) and not response.get("_fallback"):
                mode = row["mode"]
                if mode == "Recorded trace":
                    mode = recorded_mode_label(
                        _recorded_payload(persona_key).get("generated_by")
                    )
                return response, mode
            return None, RECORDED_MODE
        except (json.JSONDecodeError, TypeError) as error:
            LOGGER.warning("Discarding invalid cached response for %s/%s: %s", application_id, step, error)

    api_key = _api_key()
    if api_key:
        try:
            response = _generate_json(prompt, api_key)
            _save(application_id, step, LIVE_MODE, response, store)
            return response, LIVE_MODE
        except Exception as error:
            LOGGER.warning(
                "Gemini step %s failed (%s); using recorded output.",
                step,
                type(error).__name__,
            )
            if isinstance(error, InvalidLLMJSON):
                _save(
                    application_id,
                    step,
                    RECORDED_MODE,
                    {"_fallback": True},
                    store,
                )
                return None, RECORDED_MODE

    recorded = _recorded_payload(persona_key).get(step)
    if isinstance(recorded, dict):
        mode = recorded_mode_label(
            _recorded_payload(persona_key).get("generated_by")
        )
        _save(application_id, step, mode, recorded, store)
        return recorded, mode
    _save(application_id, step, RECORDED_MODE, {"_fallback": True}, store)
    return None, RECORDED_MODE


def _save(
    application_id: str,
    step: str,
    mode: str,
    response: dict[str, Any],
    store: SQLiteStore,
) -> None:
    """Persist validated model or recorded output in the per-step cache."""
    save_llm_cache(
        application_id,
        step,
        mode,
        json.dumps(response, sort_keys=True),
        datetime.now().isoformat(timespec="seconds"),
        store,
    )
