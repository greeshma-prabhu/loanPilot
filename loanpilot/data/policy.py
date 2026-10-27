"""Load and persist the illustrative demo policy text."""

import json
from typing import Any

from loanpilot.config import POLICY_PATH
from loanpilot.data.store import SQLiteStore

_POLICY_VERSION = "demo-v1"


def load_policy() -> dict[str, Any]:
    """Read the machine-readable fictional bank policy."""
    with POLICY_PATH.open(encoding="utf-8") as policy_file:
        return json.load(policy_file)


def seed_policy_docs(store: SQLiteStore) -> int:
    """Insert policy clauses and short regulatory topic notes into RAW."""
    policy = load_policy()
    rows = []
    for clause in policy["clauses"]:
        rows.append(
            (
                f"POLICY-{clause['clause_id']}",
                clause["title"],
                clause["clause_id"],
                clause["text"],
                _POLICY_VERSION,
            )
        )
    for note in policy["regulatory_topic_notes"]:
        rows.append(
            (
                f"POLICY-{note['clause_id']}",
                note["title"],
                note["clause_id"],
                note["text"],
                _POLICY_VERSION,
            )
        )
    store.execute_many(
        "INSERT INTO raw_policy_docs "
        "(policy_id, title, clause_id, text, version) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)
