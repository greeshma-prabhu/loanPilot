"""Export live Gemini cache entries as deterministic persona replays."""

import json
import logging
from pathlib import Path

from loanpilot.config import AGENT_RECORDED_DIR
from loanpilot.data.queries import get_llm_cache
from loanpilot.data.store import SQLiteStore

LOGGER = logging.getLogger(__name__)
PERSONA_APPLICATIONS = {
    f"PERSONA-{number}": f"APP-PERSONA-{number}" for number in range(1, 7)
}
REPLAY_STEPS = ("document_verification", "recommendation")


def export_recorded_traces(store: SQLiteStore | None = None) -> dict[str, Path]:
    """Write persona replay files for cases with live output for both LLM steps."""
    store = store or SQLiteStore()
    exported: dict[str, Path] = {}
    for persona_key, application_id in PERSONA_APPLICATIONS.items():
        replay: dict[str, dict] = {}
        for step in REPLAY_STEPS:
            cached = get_llm_cache(application_id, step, store)
            if cached.empty or cached.iloc[0]["mode"] != "Live Gemini":
                break
            payload = json.loads(cached.iloc[0]["response_json"])
            if not isinstance(payload, dict) or payload.get("_fallback"):
                break
            replay[step] = payload
        if len(replay) != len(REPLAY_STEPS):
            continue
        destination = Path(AGENT_RECORDED_DIR) / f"{persona_key.lower()}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(replay, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        exported[persona_key] = destination
    if not exported:
        LOGGER.warning(
            "No persona replay files exported; live Gemini cache entries for both "
            "document_verification and recommendation are required."
        )
    return exported


def main() -> None:
    """Export all complete live persona traces from the configured database."""
    paths = export_recorded_traces()
    if not paths:
        print(
            "No complete live Gemini traces found. Run a live assessment first; "
            "nothing was overwritten."
        )
        return
    for persona_key, path in paths.items():
        print(f"{persona_key}: {path}")


if __name__ == "__main__":
    main()
