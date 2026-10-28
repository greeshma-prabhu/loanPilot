"""Shared implementation-status ledger for dashboard and About page."""

import json
from typing import Any

import pandas as pd

from loanpilot.config import LEDGER_PATH
from loanpilot.data.queries import has_live_gemini_trace
from loanpilot.data.store import SQLiteStore


def ledger_entries(store: SQLiteStore | None = None) -> list[dict[str, str]]:
    """Load the project ledger and resolve conditional Gemini status."""
    with LEDGER_PATH.open(encoding="utf-8") as ledger_file:
        entries: list[dict[str, Any]] = json.load(ledger_file)
    live_gemini = has_live_gemini_trace(store)
    resolved = []
    for entry in entries:
        status = entry["status"]
        note = entry["note"]
        if status == "Conditional":
            status = "Real" if live_gemini else "Simulated"
            if not live_gemini:
                note += (
                    " No persisted live Gemini trace; recorded LLM text is used "
                    "while deterministic tools still run."
                )
        resolved.append(
            {
                "component": str(entry["component"]),
                "status": str(status),
                "note": str(note),
            }
        )
    return resolved


def ledger_frame(store: SQLiteStore | None = None) -> pd.DataFrame:
    """Return all ledger components in a display-ready DataFrame."""
    return pd.DataFrame(ledger_entries(store))


def ledger_counts(store: SQLiteStore | None = None) -> dict[str, int]:
    """Count components by the three implementation badge categories."""
    entries = ledger_entries(store)
    return {
        status: sum(entry["status"] == status for entry in entries)
        for status in ("Real", "Simulated", "Planned")
    }
