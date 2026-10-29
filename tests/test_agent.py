"""Tests for deterministic policy assessment and persisted agent traces."""

import math

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from loanpilot.agent.llm import RECORDED_MODE, InvalidLLMJSON
from loanpilot.agent.orchestrator import run_assessment
from loanpilot.agent.policy_engine import max_affordable_amount
from loanpilot.agent.tools import extract_document_fields, get_features
from loanpilot.data.queries import (
    count_agent_audit_events,
    get_agent_trace,
    get_application,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore

EXPECTED = {
    "APP-PERSONA-1": "Approve",
    "APP-PERSONA-2": "Refer",
    "APP-PERSONA-3": "Decline",
    "APP-PERSONA-4": "Refer",
    "APP-PERSONA-5": "Refer",
    "APP-PERSONA-6": "Decline",
}


@pytest.fixture(scope="module")
def seeded_store(tmp_path_factory) -> SQLiteStore:
    """Create one isolated synthetic database for agent and UI tests."""
    store = SQLiteStore(tmp_path_factory.mktemp("agent") / "demo.db")
    seed_demo_data(store, reset=True)
    return store


@pytest.mark.parametrize(("application_id", "recommendation"), EXPECTED.items())
def test_assessment_outcomes_and_persisted_handoff(
    seeded_store, application_id: str, recommendation: str, monkeypatch
) -> None:
    """The deterministic policy outcome persists five trace steps and a human handoff."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    result = run_assessment(application_id, seeded_store)
    assert result["recommendation"] == recommendation
    assert result["handed_to"] == "Human Review"
    assert len(result["steps"]) == 5
    expected_clauses = [
        "CP-2.1",
        "CP-2.2",
        "CP-2.3",
        "CP-3.1",
        "CP-3.2",
        "CP-4.1",
        "CP-5.1",
        "CP-5.2",
        "CP-5.3",
        "CP-5.4",
        "CP-6.1",
        "CP-6.2",
    ]
    assert [clause["clause_id"] for clause in result["policy"]["clauses"]] == expected_clauses
    assert all(
        clause["status"] in {"pass", "refer", "decline"}
        and clause["severity"] in {"low", "medium", "high"}
        for clause in result["policy"]["clauses"]
    )

    trace = get_agent_trace(application_id, result["run_id"], seeded_store)
    assert len(trace) == 5
    assert trace["step_no"].tolist() == [1, 2, 3, 4, 5]
    assert count_agent_audit_events(application_id, seeded_store) >= 5

    application = get_application(application_id, seeded_store).iloc[0]
    assert application["ai_recommendation"] == recommendation
    assert application["stage"] == "Human Review"
    assert application["stage"] != "Sanction"

    for reason in result["reasons_for"] + result["reasons_against"]:
        assert reason["clause_id"].startswith("CP-")


def test_persona_specific_document_and_thin_file_outcomes(seeded_store, monkeypatch) -> None:
    """Document review, verified-income FOIR, thin-file cap, and relationship context persist."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    anita = run_assessment("APP-PERSONA-4", seeded_store)
    assert anita["recommendation"] == "Refer"
    assert anita["risk_band"] == "High"
    assert anita["finances"]["foir_stated"] < 0.45
    assert anita["finances"]["foir_verified"] > 0.55

    karthik = run_assessment("APP-PERSONA-5", seeded_store)
    assert any("Rs 75,000" in condition for condition in karthik["conditions"])
    assert karthik["policy"]["recommendation"] == "Refer"

    meera = run_assessment("APP-PERSONA-6", seeded_store)
    employment = next(row for row in meera["policy"]["clauses"] if row["clause_id"] == "CP-2.3")
    assert employment["status"] == "decline"
    assert "relationship" in meera["explanation"].casefold()


def test_max_affordable_amount_worked_example() -> None:
    """The affordability helper returns the PV of monthly capacity at 12%."""
    amount = max_affordable_amount(100000, 10000, 0.12, 12, 0.45)
    monthly_capacity = 35000
    monthly_rate = 0.01
    expected = monthly_capacity * (1 - (1 + monthly_rate) ** -12) / monthly_rate
    assert math.isclose(amount, expected, rel_tol=1e-12)
    assert (10000 + amount * monthly_rate / (1 - (1 + monthly_rate) ** -12)) / 100000 == pytest.approx(0.45)


def test_invalid_gemini_json_uses_regex_extraction(seeded_store, monkeypatch) -> None:
    """Invalid live JSON falls back to directly parsed document text."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: "test-key")
    monkeypatch.setattr(
        "loanpilot.agent.llm.get_llm_cache",
        lambda application_id, step, store: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "loanpilot.agent.llm._generate_json",
        lambda prompt, api_key: (_ for _ in ()).throw(
            InvalidLLMJSON("invalid response")
        ),
    )
    features = get_features("APP-PERSONA-4", seeded_store)
    extracted = extract_document_fields("APP-PERSONA-4", features, seeded_store)
    assert extracted["extraction_method"] == "Regex fallback"
    assert extracted["fields"]["net"] == 82000
    assert extracted["fields"]["salary_credits_avg"] == 54120


def test_missing_key_replays_recorded_trace(seeded_store, monkeypatch) -> None:
    """When there is no key, the persona replay supplies document fields."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    monkeypatch.setattr(
        "loanpilot.agent.llm.get_llm_cache",
        lambda application_id, step, store: pd.DataFrame(),
    )
    features = get_features("APP-PERSONA-1", seeded_store)
    extracted = extract_document_fields("APP-PERSONA-1", features, seeded_store)
    assert extracted["mode"] == RECORDED_MODE
    assert extracted["extraction_method"] == "Recorded fields"
    assert extracted["fields"]["net"] == 95000


def test_assessment_page_renders_user_created_case(
    seeded_store, monkeypatch, create_user_case
) -> None:
    """The assessment page runs against a user-created application."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    application_id = create_user_case(
        seeded_store, "APP-NEW-AGENT-UI", "Assessment Applicant"
    )
    script = (
        "import streamlit as st\n"
        "from loanpilot.pages.ai_assessment import render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"st.session_state['selected_application'] = {application_id!r}\n"
        f"render(SQLiteStore({str(seeded_store.path)!r}))\n"
    )
    app = AppTest.from_string(script).run()
    app.button(key="run_assessment").click().run()
    assert not app.exception
    assert app.title[0].value == "AI Assessment"
    assert app.button(key=f"decision_review_{application_id}").label == "Go to Human Review"
