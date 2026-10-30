"""Human Review interaction and action-mapping regression tests."""

from datetime import datetime
import pytest
import pandas as pd
from streamlit.testing.v1 import AppTest

from loanpilot.agent.orchestrator import run_assessment
from loanpilot.data.queries import (
    create_intake_application,
    get_application,
    get_audit_log,
    get_human_review_cases,
    get_review_queue,
    record_human_decision,
)
from loanpilot.data.demo_seed import seed_synthetic_applications
from loanpilot.data.schema import create_schema
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore
from loanpilot.decisions import (
    HUMAN_ACTIONS,
    action_code_for_label,
    evaluate_human_action,
)
from loanpilot.pages import human_review

_REASON = "Reviewed the evidence and documented the decision rationale."
_FIRST_CASE = "APP-NEW-REVIEW-3"
_SECOND_CASE = "APP-NEW-REVIEW-6"
_ACTION_EXPECTATIONS = (
    ("approve", _FIRST_CASE, "Approve", "Sanction"),
    ("approve_with_conditions", _SECOND_CASE, "Approve with conditions", "Sanction"),
    ("modify_terms", _FIRST_CASE, "Modify terms", "Sanction"),
    ("refer_up", _SECOND_CASE, "Refer up", "Escalated"),
    ("reject", _FIRST_CASE, "Reject", "Rejected"),
    ("request_documents", _SECOND_CASE, "Request documents", "Awaiting documents"),
)


@pytest.fixture
def assessed_pair(tmp_path, monkeypatch) -> SQLiteStore:
    """Create isolated assessed user-created cases for reviewer interactions."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    store = SQLiteStore(tmp_path / "review-ui.db")
    seed_demo_data(store, reset=True)
    for application_id, name in (
        (_FIRST_CASE, "Review Applicant One"),
        (_SECOND_CASE, "Review Applicant Two"),
    ):
        create_intake_application(
            {
                "name": name,
                "dob": "1990-01-01",
                "age": 36,
                "city": "Pune",
                "mobile": "9000000000",
                "employer": "Review Test Employer",
                "employment_type": "Salaried",
                "current_tenure_months": 60,
                "total_experience_months": 120,
                "net_monthly_income": 100000,
                "existing_emi": 0,
                "pan_demo_id": f"{application_id[-1]}EST1234A",
            },
            {
                "requested_amount": 200000,
                "tenure_months": 36,
                "purpose": "Education",
                "submitted_at": datetime.now().isoformat(timespec="seconds"),
            },
            {
                "provider": "Review test bureau",
                "score": 800,
                "thin_file": False,
                "active_accounts": 1,
                "enquiries_6m": 0,
                "max_dpd_24m": 0,
                "written_off": False,
                "utilization_pct": 5,
            },
            {"status": "verified", "checks": []},
            [
                {
                    "doc_type": doc_type,
                    "file_name": f"{doc_type}.pdf",
                    "file_path": str(tmp_path / f"{application_id}-{doc_type}.pdf"),
                    "text_content": f"Verified test {doc_type} document.",
                }
                for doc_type in ("identity", "address", "income", "bank_statement")
            ],
            store,
            application_id=application_id,
        )
        run_assessment(application_id, store)
    with store.connection() as connection:
        connection.execute(
            "UPDATE cur_decisions SET ai_recommendation = ? WHERE application_id = ?",
            ("Decline", _FIRST_CASE),
        )
        connection.execute(
            "UPDATE cur_decisions SET ai_recommendation = ? WHERE application_id = ?",
            ("Approve", _SECOND_CASE),
        )
    return store


def _app(store: SQLiteStore) -> AppTest:
    """Render the review page against a dedicated temporary SQLite database."""
    return AppTest.from_string(
        "import streamlit as st\n"
        "st.session_state['auth'] = {'name': 'Test Reviewer', 'role': 'Credit Analyst'}\n"
        "from loanpilot.pages.human_review import render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"render(SQLiteStore({str(store.path)!r}))\n"
    )


def test_review_filters_include_seeded_and_unassessed_operational_cases(
    tmp_path, monkeypatch, create_user_case
) -> None:
    """All includes unassessed and synthetic cases; Pending means human review."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    store = SQLiteStore(tmp_path / "review-seeded.db")
    create_schema(store)
    seed_synthetic_applications(store)
    new_id = create_user_case(store, "APP-NEW-UNASSESSED", "Unassessed Applicant")

    all_cases = get_human_review_cases("All", store=store, user_created_only=True)
    assert len(all_cases) == 11
    assert new_id in set(all_cases["application_id"])
    assert len(
        get_human_review_cases("Pending", store=store, user_created_only=True)
    ) == 4
    assert len(
        get_human_review_cases("Approved", store=store, user_created_only=True)
    ) == 1
    assert len(
        get_human_review_cases("Rejected", store=store, user_created_only=True)
    ) == 1

    run_assessment(new_id, store)
    pending = get_human_review_cases("Pending", store=store, user_created_only=True)
    assert len(pending) == 5
    assert new_id in set(pending["application_id"])


def test_decision_is_recorded_under_the_signed_in_user_without_reviewer_picker(
    assessed_pair,
) -> None:
    """Reviewer identity is kept in the signed-in session, not a selectable field."""
    app = _app(assessed_pair).run()
    application_id = _FIRST_CASE
    app.button(key=f"review_open_{application_id}").click().run()
    assert not any(
        element.key == f"reviewer_display_{application_id}"
        for element in app.text_input
    )
    assert any(
        "signed-in reviewer account" in element.value for element in app.caption
    )


def _fake_sanction(
    application_id,
    amount,
    tenure,
    rate,
    reason,
    reviewer,
    *,
    conditions=None,
    decision_action,
    store,
):
    """Persist approval-stage human decisions without writing a PDF in UI tests."""
    application = get_application(application_id, store).iloc[0]
    action_code = action_code_for_label(decision_action)
    record_human_decision(
        application_id,
        decision_action,
        reason,
        evaluate_human_action(application["ai_recommendation"], action_code).is_override,
        reviewer,
        datetime.now().isoformat(timespec="seconds"),
        "Sanction",
        store,
    )
    return {"sanction_ref": f"TEST-{application_id}"}


@pytest.mark.parametrize(
    ("action_code", "application_id", "decision", "stage"),
    _ACTION_EXPECTATIONS,
)
def test_each_action_persists_matching_decision_stage_and_audit(
    assessed_pair, monkeypatch, action_code, application_id, decision, stage
) -> None:
    """Every code maps to its own saved label, stage and audit event."""
    monkeypatch.setattr(human_review, "approve_and_sanction", _fake_sanction)
    app = _app(assessed_pair).run()
    app.button(key=f"review_open_{application_id}").click().run()
    action_key = f"review_action_{application_id}"
    assert app.selectbox(key=action_key).value == ""
    assert app.selectbox(key=action_key).options == [
        "Choose an action",
        *(action.label for action in HUMAN_ACTIONS.values()),
    ]
    app.selectbox(key=action_key).select(decision).run()
    assert app.session_state[action_key] == decision
    app.text_area(key=f"decision_reason_{application_id}").set_value(_REASON).run()
    assert app.session_state[action_key] == decision
    app.button(key=f"submit_review_{application_id}").click().run()

    saved = get_application(application_id, assessed_pair).iloc[0]
    assert saved["human_decision"] == decision
    assert saved["stage"] == stage
    audit = get_audit_log(application_id, assessed_pair)
    event = audit.loc[audit["action"].str.startswith("Human decision:")].iloc[0]
    assert event["action"] == f"Human decision: {decision}"
    assert event["actor"] == "Test Reviewer"
    assert stage in event["detail"]
    assert application_id not in set(get_review_queue(assessed_pair)["application_id"])
    assert app.session_state["review_open"] == application_id
    assert any(item.value == "Decision result" for item in app.subheader)
    result_text = "\n".join(element.value for element in app.markdown)
    assert f"Your decision:** {decision}" in result_text
    assert f"New stage:** {stage}" in result_text
    assert not any(
        "Imran Sheikh:" in message.value or "Meera Iyer:" in message.value
        for message in app.success
    )


def test_decline_reject_has_no_override_notice_but_decline_approval_does(
    assessed_pair, monkeypatch
) -> None:
    """The CP-8.2 notice follows the selected action and reason is optional."""
    monkeypatch.setattr(human_review, "approve_and_sanction", _fake_sanction)
    app = _app(assessed_pair).run()
    app.button(key=f"review_open_{_FIRST_CASE}").click().run()
    app.selectbox(key=f"review_action_{_FIRST_CASE}").select("Reject").run()
    assert not any("CP-8.2" in warning.value for warning in app.warning)

    app.selectbox(key=f"review_action_{_FIRST_CASE}").select("Approve").run()
    assert any("CP-8.2" in warning.value for warning in app.warning)
    app.text_area(key=f"decision_reason_{_FIRST_CASE}").set_value("OK").run()
    assert app.button(key=f"submit_review_{_FIRST_CASE}").disabled is False
    app.button(key=f"submit_review_{_FIRST_CASE}").click().run()
    saved = get_application(_FIRST_CASE, assessed_pair).iloc[0]
    assert saved["human_decision"] == "Approve"
    assert saved["is_override"] == 1
    assert saved["human_reason"] == "OK"


def test_human_review_submit_allows_empty_reason(assessed_pair, monkeypatch) -> None:
    """Selecting an action is enough to submit; a written reason is optional."""
    monkeypatch.setattr(human_review, "approve_and_sanction", _fake_sanction)
    app = _app(assessed_pair).run()
    app.button(key=f"review_open_{_FIRST_CASE}").click().run()
    app.selectbox(key=f"review_action_{_FIRST_CASE}").select("Reject").run()
    assert app.button(key=f"submit_review_{_FIRST_CASE}").disabled is False
    app.button(key=f"submit_review_{_FIRST_CASE}").click().run()
    saved = get_application(_FIRST_CASE, assessed_pair).iloc[0]
    assert saved["human_decision"] == "Reject"
    assert saved["human_reason"] == ""


def test_reviewer_can_reject_an_ai_approved_case(assessed_pair) -> None:
    """Reject remains selectable and persists as an override after AI approval."""
    application = get_application(_SECOND_CASE, assessed_pair).iloc[0]
    assert application["ai_recommendation"] == "Approve"

    app = _app(assessed_pair).run()
    app.button(key=f"review_open_{_SECOND_CASE}").click().run()
    action_select = app.selectbox(key=f"review_action_{_SECOND_CASE}")
    assert "Reject" in action_select.options
    action_select.select("Reject").run()
    assert app.session_state[f"review_action_{_SECOND_CASE}"] == "Reject"
    assert any("Override:" in warning.value for warning in app.warning)
    app.text_area(key=f"decision_reason_{_SECOND_CASE}").set_value("Do not approve").run()
    app.button(key=f"submit_review_{_SECOND_CASE}").click().run()

    saved = get_application(_SECOND_CASE, assessed_pair).iloc[0]
    assert saved["human_decision"] == "Reject"
    assert bool(saved["is_override"])
    assert saved["stage"] == "Rejected"
    assert saved["human_reason"] == "Do not approve"


def test_reviewer_can_approve_ai_decline_without_a_grid_rate(
    assessed_pair, monkeypatch
) -> None:
    """A human approval can use an explicit configured rate if CP-7.1 has no match."""
    captured = {}

    def fake_sanction(*args, **kwargs):
        captured["rate"] = args[3]
        return _fake_sanction(*args, **kwargs)

    monkeypatch.setattr(human_review, "pricing_rate", lambda score: None)
    monkeypatch.setattr(human_review, "approve_and_sanction", fake_sanction)
    app = _app(assessed_pair).run()
    app.button(key=f"review_open_{_FIRST_CASE}").click().run()
    app.selectbox(key=f"review_action_{_FIRST_CASE}").select("Approve").run()

    rate_key = f"manual_rate_{_FIRST_CASE}"
    assert app.selectbox(key=rate_key).value == ""
    assert app.button(key=f"submit_review_{_FIRST_CASE}").disabled
    app.selectbox(key=rate_key).select(0.16).run()
    assert app.button(key=f"submit_review_{_FIRST_CASE}").disabled is False
    app.button(key=f"submit_review_{_FIRST_CASE}").click().run()

    saved = get_application(_FIRST_CASE, assessed_pair).iloc[0]
    assert captured["rate"] == 0.16
    assert saved["ai_recommendation"] == "Decline"
    assert saved["human_decision"] == "Approve"
    assert bool(saved["is_override"])
    assert saved["stage"] == "Sanction"


@pytest.mark.parametrize("recommendation", ("Approve", "Refer", "Decline"))
def test_action_control_is_empty_and_offers_all_actions(
    assessed_pair, recommendation
) -> None:
    """Every AI recommendation presents the same complete, initially empty action list."""
    assessed_pair.execute(
        "UPDATE cur_decisions SET ai_recommendation = ? WHERE application_id = ?",
        (recommendation, _FIRST_CASE),
    )
    app = _app(assessed_pair).run()
    app.button(key=f"review_open_{_FIRST_CASE}").click().run()
    action_select = app.selectbox(key=f"review_action_{_FIRST_CASE}")
    assert action_select.value == ""
    assert action_select.options == [
        "Choose an action",
        *(action.label for action in HUMAN_ACTIONS.values()),
    ]
    assert app.button(key=f"submit_review_{_FIRST_CASE}").disabled
    app.text_area(key=f"decision_reason_{_FIRST_CASE}").set_value(_REASON).run()
    assert app.button(key=f"submit_review_{_FIRST_CASE}").disabled
    action_select.select("Reject").run()
    assert app.button(key=f"submit_review_{_FIRST_CASE}").disabled is False


def test_action_selection_survives_rerun_and_cases_do_not_share_form_state(assessed_pair) -> None:
    """Separate application keys prevent the action or reason from crossing cases."""
    app = _app(assessed_pair).run()
    app.button(key=f"review_open_{_FIRST_CASE}").click().run()
    app.selectbox(key=f"review_action_{_FIRST_CASE}").select("Reject").run()
    app.text_area(key=f"decision_reason_{_FIRST_CASE}").set_value(_REASON).run()
    app.selectbox(key=f"review_action_{_FIRST_CASE}").select("Refer up").run()
    assert app.session_state[f"review_action_{_FIRST_CASE}"] == "Refer up"

    app.button(key=f"close_review_details_{_FIRST_CASE}").click().run()
    app.button(key=f"review_open_{_SECOND_CASE}").click().run()
    assert app.selectbox(key=f"review_action_{_SECOND_CASE}").value == ""
    assert app.text_area(key=f"decision_reason_{_SECOND_CASE}").value == ""


def test_case_panel_is_inline_single_and_dismissible(assessed_pair) -> None:
    """Opening a case hides other applicants; X closes without saving."""
    app = _app(assessed_pair).run()
    assert app.title[0].value == "Review queue"
    assert app.button(key=f"review_open_{_FIRST_CASE}")
    assert app.button(key=f"review_open_{_SECOND_CASE}")
    assert not any(item.value == "Your decision" for item in app.subheader)

    app.button(key=f"review_open_{_FIRST_CASE}").click().run()
    assert any(item.value == "Your decision" for item in app.subheader)
    assert app.session_state["review_open"] == _FIRST_CASE
    visible_markdown = "\n".join(element.value for element in app.markdown)
    assert "Review Applicant One" in visible_markdown
    assert "Review Applicant Two" not in visible_markdown
    assert not any(button.key == f"review_open_{_SECOND_CASE}" for button in app.button)

    app.button(key=f"close_review_details_{_FIRST_CASE}").click().run()
    assert not any(item.value == "Your decision" for item in app.subheader)
    assert app.session_state["review_open"] is None
    assert pd.isna(get_application(_SECOND_CASE, assessed_pair).iloc[0]["human_decision"])


def test_status_pills_are_the_only_queue_summary_controls(assessed_pair, monkeypatch) -> None:
    """The queue uses the filter pills without duplicate count cards."""
    monkeypatch.setattr(human_review, "approve_and_sanction", _fake_sanction)
    app = _app(assessed_pair).run()
    for label in ("Pending", "Approved", "Rejected", "All"):
        assert app.button(key=f"review_filter_{label.casefold()}").label.startswith(label)
    labels = [app.button(key=f"review_filter_{label.casefold()}").label for label in
              ("Pending", "Approved", "Rejected", "All")]
    assert labels == ["Pending · 2", "Approved · 0", "Rejected · 0", "All · 2"]
    assert not app.metric
    assert not any(item.value == "Your decision" for item in app.subheader)
    app.button(key=f"review_open_{_FIRST_CASE}").click().run()
    app.selectbox(key=f"review_action_{_FIRST_CASE}").select("Reject").run()
    app.text_area(key=f"decision_reason_{_FIRST_CASE}").set_value(_REASON).run()
    app.button(key=f"submit_review_{_FIRST_CASE}").click().run()

    assert app.session_state["review_open"] == _FIRST_CASE
    assert app.session_state["review_filter"] == "All"
    assert any(item.value == "Decision result" for item in app.subheader)
    assert any("New stage:** Rejected" in item.value for item in app.markdown)


def test_review_queue_only_shows_requested_applicant_fields(assessed_pair) -> None:
    """The collapsed list omits case id, loan details, age and city."""
    app = _app(assessed_pair).run()
    content = "\n".join(element.value for element in app.markdown)
    assert "APPLICANT" in content
    assert "AI DECISION" in content
    assert "CASE" not in content
    assert "Personal loan" not in content
    assert "Hyderabad" not in content
    assert "months" not in content
    assert "Nothing is sanctioned until a person decides." not in content
