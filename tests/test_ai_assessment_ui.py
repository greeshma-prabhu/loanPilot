"""AI Assessment page coverage for user-created applications."""

import json

import pytest
from streamlit.testing.v1 import AppTest

from loanpilot.agent.orchestrator import run_assessment
from loanpilot.agent.reason_text import build_why
from loanpilot.data.queries import get_application, get_agent_trace, list_applications
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore

_APPLICATION_ID = "APP-NEW-ASSESSMENT-UI"


@pytest.fixture
def assessed_store(tmp_path, monkeypatch, create_user_case) -> SQLiteStore:
    """Create one assessed intake alongside stored examples hidden from the page."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    store = SQLiteStore(tmp_path / "assessment.db")
    seed_demo_data(store, reset=True)
    create_user_case(store, _APPLICATION_ID, "Assessment Applicant")
    run_assessment(_APPLICATION_ID, store)
    return store


def _app(store: SQLiteStore, application_id: str = _APPLICATION_ID) -> AppTest:
    """Render assessment for a chosen isolated user-created application."""
    script = (
        "import streamlit as st\n"
        "from loanpilot.pages.ai_assessment import render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"st.session_state['selected_application'] = {application_id!r}\n"
        f"render(SQLiteStore({str(store.path)!r}))\n"
    )
    return AppTest.from_string(script)


def test_assessment_displays_the_user_created_case_and_decision(assessed_store) -> None:
    """Assessment results remain accessible for actual intake records."""
    app = _app(assessed_store).run()
    assert not app.exception
    content = "\n".join(element.value for element in app.markdown)
    assert app.selectbox(key="assessment_application_selector").value == _APPLICATION_ID
    assert (
        get_application(_APPLICATION_ID, assessed_store).iloc[0]["name"]
        == "Assessment Applicant"
    )
    assert any(item.value == "Key numbers" for item in app.subheader)
    assert "Priya Menon" not in content
    assert "Karthik Nair" not in content
    assert any(item.label == "Run assessment" for item in app.button)
    assert any(item.label == "Details" for item in app.expander)
    assert len(list_applications({"user_created_only": True}, assessed_store)) == 1


def test_assessment_shows_foir_for_actual_case(assessed_store) -> None:
    """The actual application assessment includes its computed FOIR."""
    app = _app(assessed_store).run()
    foir = next(metric for metric in app.metric if metric.label == "FOIR · 45% limit")
    assert "→" in foir.value


def test_assessment_why_uses_saved_policy_trace(assessed_store) -> None:
    """The bounded explanation is based on the saved assessment policy result."""
    trace = get_agent_trace(_APPLICATION_ID, store=assessed_store)
    policy_step = json.loads(trace.loc[trace.step_no == 3].iloc[0]["tool_calls_json"])
    clauses = policy_step["result"]["policy"]["clauses"]
    recommendation = get_application(_APPLICATION_ID, assessed_store).iloc[0][
        "ai_recommendation"
    ]
    lines = build_why(recommendation, clauses)
    assert len(lines) <= 5
    assert all(line["text"] != clause["rule_text"] for line in lines for clause in clauses)
    app = _app(assessed_store).run()
    assert any(line["clause_id"] in "\n".join(x.value for x in app.markdown) for line in lines)


def test_unassessed_user_case_shows_run_assessment_state(
    tmp_path, create_user_case
) -> None:
    """A newly submitted case has a clear empty assessment state."""
    store = SQLiteStore(tmp_path / "unassessed.db")
    application_id = create_user_case(store, _APPLICATION_ID, "New Applicant")
    app = _app(store, application_id).run()
    assert not app.exception
    assert any(item.value == "Assessment not run yet" for item in app.subheader)
    assert sum(button.label == "Run assessment" for button in app.button) == 1
    assert get_application(application_id, store).iloc[0]["ai_recommendation"] is None
