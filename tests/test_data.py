"""Tests for LoanPilot's storage contract and schema."""

import hashlib
import json
from pathlib import Path
import re

import pandas as pd

from loanpilot.config import PROJECT_ROOT
from loanpilot.data.documents import validate_persona_documents
from loanpilot.data.policy import load_policy
from loanpilot.data.schema import create_schema
from loanpilot.data.seed import PERSONAS, calculate_emi, seed_demo_data
from loanpilot.data.store import DataStore, SQLiteStore


def test_sqlite_store_implements_interface_and_creates_schema(tmp_path) -> None:
    """The local implementation should create and query an empty schema."""
    store = SQLiteStore(tmp_path / "loanpilot.db")
    assert isinstance(store, DataStore)

    create_schema(store)
    counts = store.table_counts()

    assert "raw_documents" in counts
    assert "cur_customers" in counts
    assert counts["cur_customers"] == 0
    assert store.query("SELECT * FROM srv_application_features").empty


def test_sqlite_store_query_execute_and_counts(tmp_path) -> None:
    """The store supports parameterized writes, reads, and row counts."""
    store = SQLiteStore(tmp_path / "store.db")
    store.execute("CREATE TABLE sample (value INTEGER NOT NULL)")

    assert store.execute("INSERT INTO sample (value) VALUES (?)", (42,)) == 1
    assert store.query("SELECT value FROM sample WHERE value = ?", (42,)).iloc[0, 0] == 42
    assert store.table_counts() == {"sample": 1}


def test_relative_store_paths_are_project_rooted() -> None:
    """Relative database paths must not depend on the caller's working directory."""
    from loanpilot.config import PROJECT_ROOT

    assert SQLiteStore("data/test.db").path == PROJECT_ROOT / "data" / "test.db"


def _table_hashes(store: SQLiteStore) -> dict[str, str]:
    """Hash stable, ordered rows in every base table."""
    hashes = {}
    for table in sorted(store.table_counts()):
        columns = store.query(f'PRAGMA table_info("{table}")')["name"].tolist()
        ordering = ", ".join(f'"{column}"' for column in columns)
        rows = store.query(f'SELECT * FROM "{table}" ORDER BY {ordering}')
        encoded = json.dumps(rows.to_dict("records"), sort_keys=True, default=str)
        hashes[table] = hashlib.sha256(encoded.encode()).hexdigest()
    return hashes


def test_seed_counts_personas_and_determinism(tmp_path) -> None:
    """The fixed seed produces the same 500 customers and 66 applications."""
    first_store = SQLiteStore(tmp_path / "first.db")
    second_store = SQLiteStore(tmp_path / "second.db")
    first_counts = seed_demo_data(first_store, reset=True)
    second_counts = seed_demo_data(second_store, reset=True)

    assert first_counts["cur_customers"] == 500
    assert first_counts["cur_applications"] == 66
    assert first_counts["raw_policy_docs"] == 18
    assert first_counts["raw_documents"] == 18
    assert first_counts == second_counts
    assert _table_hashes(first_store) == _table_hashes(second_store)

    features = first_store.query(
        "SELECT a.persona_key, a.stage, f.income, f.foir, f.bureau_score "
        "FROM cur_applications a JOIN srv_application_features f USING (application_id) "
        "WHERE a.persona_key IS NOT NULL ORDER BY a.persona_key"
    )
    assert len(features) == len(PERSONAS)
    assert set(features["stage"]) == {"Submitted"}
    for row in features.to_dict("records"):
        persona = PERSONAS[row["persona_key"]]
        assert row["income"] == persona["income"]
        if persona["score"] is None:
            assert pd.isna(row["bureau_score"])
        else:
            assert row["bureau_score"] == persona["score"]
        if persona.get("foir") is not None:
            assert abs(row["foir"] - persona["foir"]) <= 0.015
    assert first_store.query("PRAGMA foreign_key_check").empty
    validate_persona_documents(first_store)
    pdfs = first_store.query("SELECT file_path FROM raw_documents")
    for relative_path in pdfs["file_path"]:
        pdf_path = PROJECT_ROOT / Path(relative_path)
        assert pdf_path.is_file()
        assert pdf_path.stat().st_size > 0
        assert pdf_path.read_bytes().startswith(b"%PDF")


def test_policy_is_structured_and_matches_raw_documents(tmp_path) -> None:
    """Every illustrative clause and regulatory note is persisted verbatim."""
    store = SQLiteStore(tmp_path / "policy.db")
    seed_demo_data(store, reset=True)
    policy = load_policy()
    expected = {
        clause["clause_id"]: clause["text"] for clause in policy["clauses"]
    }
    expected.update(
        {
            note["clause_id"]: note["text"]
            for note in policy["regulatory_topic_notes"]
        }
    )
    stored = store.query("SELECT clause_id, text FROM raw_policy_docs")
    assert len(stored) == 18
    assert dict(zip(stored["clause_id"], stored["text"], strict=True)) == expected
    assert all(
        "Summary for demo; verify against the official RBI document" in note["text"]
        for note in policy["regulatory_topic_notes"]
    )


def test_generated_dataset_meets_data_and_persona_rules(tmp_path) -> None:
    """Validate generated row volumes, loan math, identity, and persona targets."""
    store = SQLiteStore(tmp_path / "rules.db")
    counts = seed_demo_data(store, reset=True)
    assert counts["cur_customers"] == 500
    assert counts["cur_accounts"] == 500
    assert counts["cur_transactions"] == 3000
    assert counts["cur_applications"] == 66
    assert counts["cur_decisions"] == 60
    assert counts["cur_audit_log"] == 66
    assert counts["raw_bureau_responses"] == 66
    assert counts["raw_kyc_responses"] == 66
    assert counts["raw_policy_docs"] == 18
    assert counts["raw_documents"] == 18
    assert store.query("PRAGMA foreign_key_check").empty

    loan_counts = store.query(
        "SELECT customer_id, COUNT(*) AS loan_count FROM cur_existing_loans "
        "GROUP BY customer_id"
    )
    assert loan_counts["loan_count"].between(1, 3).all()
    repayment_counts = store.query(
        "SELECT loan_id, COUNT(*) AS repayment_count FROM cur_repayments GROUP BY loan_id"
    )
    assert repayment_counts["repayment_count"].between(12, 24).all()
    assert store.query(
        "SELECT customer_id FROM cur_customers "
        "WHERE net_monthly_income < 25000 OR net_monthly_income > 200000"
    ).empty
    assert store.query(
        "SELECT customer_id FROM cur_customers "
        "WHERE total_experience_months < current_tenure_months "
        "OR total_experience_months > (age - 18) * 12"
    ).empty
    assert store.query(
        "SELECT pan_demo_id FROM cur_customers WHERE pan_demo_id GLOB "
        "'[A-Z][A-Z][A-Z][A-Z][A-Z][0-9][0-9][0-9][0-9][A-Z]'"
    ).empty
    assert all(
        re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan) is None
        for pan in store.query("SELECT pan_demo_id FROM cur_customers")["pan_demo_id"]
    )

    historical_stages = store.query(
        "SELECT stage, COUNT(*) AS row_count FROM cur_applications "
        "WHERE persona_key IS NULL GROUP BY stage"
    )
    assert dict(zip(historical_stages["stage"], historical_stages["row_count"], strict=True)) == {
        "Approved": 30,
        "Declined": 18,
        "Referred": 12,
    }
    processing = store.query(
        "SELECT julianday(d.decided_at) - julianday(a.submitted_at) AS processing_days "
        "FROM cur_applications a JOIN cur_decisions d USING (application_id)"
    )
    assert processing["processing_days"].between(1, 9).all()

    features = store.query(
        "SELECT a.persona_key, a.requested_amount, a.tenure_months, f.* "
        "FROM cur_applications a JOIN srv_application_features f USING (application_id) "
        "WHERE a.persona_key IS NOT NULL ORDER BY a.persona_key"
    )
    expected_foir = {
        "PERSONA-1": 0.27,
        "PERSONA-2": 0.47,
        "PERSONA-3": 0.59,
        "PERSONA-6": 0.38,
    }
    for row in features.to_dict("records"):
        rate = (
            0.115
            if row["bureau_score"] >= 750
            else 0.135
            if row["bureau_score"] >= 700
            else 0.16
        )
        assert abs(
            row["proposed_emi"]
            - calculate_emi(row["requested_amount"], rate, row["tenure_months"])
        ) < 0.01
        existing_emi = store.query(
            "SELECT COALESCE(SUM(emi), 0) AS total FROM cur_existing_loans "
            "WHERE customer_id = ? AND status = 'Active'",
            (f"CUST-{row['persona_key']}",),
        ).iloc[0, 0]
        assert abs(
            row["foir"] - (existing_emi + row["proposed_emi"]) / row["income"]
        ) < 1e-10
        if row["persona_key"] in expected_foir:
            assert abs(row["foir"] - expected_foir[row["persona_key"]]) <= 0.02

    scores = {
        row["persona_key"]: row["bureau_score"]
        for row in features.to_dict("records")
    }
    assert scores["PERSONA-1"] == 782
    assert scores["PERSONA-2"] == 712
    assert scores["PERSONA-3"] == 668
    assert scores["PERSONA-4"] == 745
    assert pd.isna(scores["PERSONA-5"])
    assert scores["PERSONA-6"] == 706
    late_row = store.query(
        "SELECT due_month, days_past_due FROM cur_repayments "
        "WHERE loan_id LIKE 'LOAN-CUST-PERSONA-2-%' AND days_past_due > 0"
    )
    assert late_row.to_dict("records") == [
        {"due_month": "2025-08", "days_past_due": 30}
    ]
