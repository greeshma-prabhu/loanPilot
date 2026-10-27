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
RECORDED_MODE = "Recorded trace"


class InvalidLLMJSON(ValueError):
    """Raised when the model response is not a JSON object."""


def _api_key() -> str | None:
    """Read the Gemini key from the environment, then Streamlit secrets."""
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY")
        return str(secret_key) if secret_key else None
    except Exception as error:
        LOGGER.info("Gemini secrets are unavailable; using recorded mode: %s", error)
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


def _generate_json(prompt: str, api_key: str) -> dict[str, Any]:
    """Call Gemini and require a JSON object response."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
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
                return response, row["mode"]
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
            LOGGER.warning("Gemini step %s failed; using recorded output: %s", step, error)
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
        _save(application_id, step, RECORDED_MODE, recorded, store)
        return recorded, RECORDED_MODE
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
