"""Decision-first AI assessment page coverage."""

import json

import pytest
from streamlit.testing.v1 import AppTest

from loanpilot.agent.orchestrator import run_assessment
from loanpilot.agent.reason_text import build_why
from loanpilot.data.queries import get_application, get_agent_trace
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore

PERSONAS = (
    ("APP-PERSONA-1", "APPROVE"),
    ("APP-PERSONA-2", "REFER"),
    ("APP-PERSONA-3", "DECLINE"),
    ("APP-PERSONA-4", "REFER: document review"),
    ("APP-PERSONA-5", "REFER"),
    ("APP-PERSONA-6", "DECLINE"),
)


@pytest.fixture
def assessed_store(tmp_path_factory, monkeypatch) -> SQLiteStore:
    """Create all six synthetic assessment outcomes without a live Gemini call."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    store = SQLiteStore(tmp_path_factory.mktemp("assessment-ui") / "assessment.db")
    seed_demo_data(store, reset=True)
    for application_id, _ in PERSONAS:
        run_assessment(application_id, store)
    return store


def _app(store: SQLiteStore, application_id: str) -> AppTest:
    """Render assessment for a chosen isolated application."""
    script = (
        "import streamlit as st\n"
        "from loanpilot.pages.ai_assessment import render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"st.session_state['selected_application'] = {application_id!r}\n"
        f"render(SQLiteStore({str(store.path)!r}))\n"
    )
    return AppTest.from_string(script)


@pytest.mark.parametrize(("application_id", "decision_text"), PERSONAS)
def test_persona_decision_is_prominent_and_precedes_details(
    assessed_store, application_id, decision_text
) -> None:
    """Each persona's decision appears before collapsed details."""
    app = _app(assessed_store, application_id).run()
    assert not app.exception
    content = "\n".join(element.value for element in app.markdown)
    assert decision_text in content
    assert any(item.label == "Details" for item in app.expander)
    assert any(item.label == "Run assessment" for item in app.button)
    decision_index = content.index(decision_text)
    assert decision_index < content.index("Key numbers")


def test_anita_foir_is_shown_for_stated_and_verified_income(assessed_store) -> None:
    """Anita's key numbers expose both FOIR measurements alongside document referral."""
    app = _app(assessed_store, "APP-PERSONA-4").run()
    text = "\n".join(element.value for element in app.markdown)
    assert "REFER: document review" in text
    foir = next(metric for metric in app.metric if metric.label == "FOIR · 45% limit")
    assert "→" in foir.value


def test_meera_reason_names_cp_2_3_and_why_is_bounded(assessed_store) -> None:
    """Meera's decline uses deterministic employment wording with at most five lines."""
    trace = get_agent_trace("APP-PERSONA-6", store=assessed_store)
    policy_step = json.loads(trace.loc[trace.step_no == 3].iloc[0]["tool_calls_json"])
    clauses = policy_step["result"]["policy"]["clauses"]
    lines = build_why("Decline", clauses)
    assert len(lines) <= 5
    assert any(line["clause_id"] == "CP-2.3" for line in lines)
    reason = next(line["text"] for line in lines if line["clause_id"] == "CP-2.3")
    assert "months" in reason and "total experience" in reason
    assert all(line["text"] != clause["rule_text"] for line in lines for clause in clauses)
    app = _app(assessed_store, "APP-PERSONA-6").run()
    text = "\n".join(element.value for element in app.markdown)
    assert "CP-2.3" in text


def test_karthik_reason_shows_demo_amount_cap(assessed_store) -> None:
    """A thin-file referral states the illustrative Rs 75,000 cap."""
    app = _app(assessed_store, "APP-PERSONA-5").run()
    text = "\n".join(element.value for element in app.markdown)
    assert "REFER" in text
    assert "Rs 75,000" in text


def test_unassessed_persona_shows_run_assessment_state(tmp_path) -> None:
    """An unassessed loaded case has a clear decision empty state and run action."""
    store = SQLiteStore(tmp_path / "unassessed.db")
    seed_demo_data(store, reset=True)
    app = _app(store, "APP-PERSONA-1").run()
    assert not app.exception
    assert any(item.value == "Assessment not run yet" for item in app.subheader)
    assert any(button.label == "Run assessment" for button in app.button)
    assert get_application("APP-PERSONA-1", store).iloc[0]["ai_recommendation"] is None
