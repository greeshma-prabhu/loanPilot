"""Human Review interaction and action-mapping regression tests."""

from datetime import datetime
import pytest
import pandas as pd
from streamlit.testing.v1 import AppTest

from loanpilot.agent.orchestrator import run_assessment
from loanpilot.data.queries import (
    get_application,
    get_audit_log,
    get_review_queue,
    record_human_decision,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore
from loanpilot.pages import human_review

_REASON = "Reviewed the evidence and documented the decision rationale."
_ACTION_EXPECTATIONS = (
    ("approve", "APP-PERSONA-3", "Approve", "Sanction"),
    ("approve_with_conditions", "APP-PERSONA-6", "Approve with conditions", "Sanction"),
    ("modify_terms", "APP-PERSONA-3", "Modify terms", "Sanction"),
    ("refer_up", "APP-PERSONA-6", "Refer up", "Escalated"),
    ("reject", "APP-PERSONA-3", "Reject", "Rejected"),
    ("request_documents", "APP-PERSONA-6", "Request documents", "Awaiting documents"),
)


@pytest.fixture
def assessed_pair(tmp_path, monkeypatch) -> SQLiteStore:
    """Create isolated assessed Imran and Meera cases for reviewer interactions."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    store = SQLiteStore(tmp_path / "review-ui.db")
    seed_demo_data(store, reset=True)
    for application_id in ("APP-PERSONA-3", "APP-PERSONA-6"):
        run_assessment(application_id, store)
    return store


def _app(store: SQLiteStore) -> AppTest:
    """Render the review page against a dedicated temporary SQLite database."""
    return AppTest.from_string(
        "from loanpilot.pages.human_review import render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"render(SQLiteStore({str(store.path)!r}))\n"
    )


def test_greeshma_prabhu_is_available_as_a_reviewer(assessed_pair) -> None:
    """The reviewer selector includes Greeshma Prabhu and preserves the selection."""
    app = _app(assessed_pair).run()
    application_id = "APP-PERSONA-3"
    app.button(key=f"review_open_{application_id}").click().run()
    reviewer_key = f"reviewer_{application_id}"
    reviewer = app.selectbox(key=reviewer_key)
    assert "Greeshma Prabhu" in reviewer.options

    reviewer.select("Greeshma Prabhu").run()

    assert app.session_state[reviewer_key] == "Greeshma Prabhu"


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
    action_code = next(code for code, label in human_review.ACTIONS.items() if label == decision_action)
    record_human_decision(
        application_id,
        decision_action,
        reason,
        human_review.is_override_decision(application["ai_recommendation"], action_code),
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
    app.selectbox(key=action_key).select(action_code).run()
    assert app.session_state[action_key] == action_code
    app.text_area(key=f"decision_reason_{application_id}").set_value(_REASON).run()
    assert app.session_state[action_key] == action_code
    app.button(key=f"submit_review_{application_id}").click().run()

    saved = get_application(application_id, assessed_pair).iloc[0]
    assert saved["human_decision"] == decision
    assert saved["stage"] == stage
    audit = get_audit_log(application_id, assessed_pair)
    event = audit.loc[audit["action"].str.startswith("Human decision:")].iloc[0]
    assert event["action"] == f"Human decision: {decision}"
    assert stage in event["detail"]
    assert application_id not in set(get_review_queue(assessed_pair)["application_id"])
    assert app.session_state["review_open"] is None
    assert not any(
        "Imran Sheikh:" in message.value or "Meera Iyer:" in message.value
        for message in app.success
    )


def test_decline_reject_has_no_override_notice_but_decline_approval_does(
    assessed_pair, monkeypatch
) -> None:
    """The CP-8.2 notice follows the selected code and reason length gates approval."""
    monkeypatch.setattr(human_review, "approve_and_sanction", _fake_sanction)
    app = _app(assessed_pair).run()
    app.button(key="review_open_APP-PERSONA-3").click().run()
    app.selectbox(key="review_action_APP-PERSONA-3").select("reject").run()
    assert not any("CP-8.2" in warning.value for warning in app.warning)

    app.selectbox(key="review_action_APP-PERSONA-3").select("approve").run()
    assert any("CP-8.2" in warning.value for warning in app.warning)
    app.text_area(key="decision_reason_APP-PERSONA-3").set_value("Too short").run()
    assert app.button(key="submit_review_APP-PERSONA-3").disabled
    app.text_area(key="decision_reason_APP-PERSONA-3").set_value(_REASON).run()
    assert not app.button(key="submit_review_APP-PERSONA-3").disabled
    app.button(key="submit_review_APP-PERSONA-3").click().run()
    saved = get_application("APP-PERSONA-3", assessed_pair).iloc[0]
    assert saved["human_decision"] == "Approve"
    assert saved["is_override"] == 1


def test_action_selection_survives_rerun_and_cases_do_not_share_form_state(assessed_pair) -> None:
    """Separate application keys prevent the action or reason from crossing cases."""
    app = _app(assessed_pair).run()
    app.button(key="review_open_APP-PERSONA-3").click().run()
    app.selectbox(key="review_action_APP-PERSONA-3").select("reject").run()
    app.text_area(key="decision_reason_APP-PERSONA-3").set_value(_REASON).run()
    app.selectbox(key="review_action_APP-PERSONA-3").select("refer_up").run()
    assert app.session_state["review_action_APP-PERSONA-3"] == "refer_up"

    app.button(key="close_review_details_APP-PERSONA-3").click().run()
    app.button(key="review_open_APP-PERSONA-6").click().run()
    assert app.selectbox(key="review_action_APP-PERSONA-6").value == "reject"
    assert app.text_area(key="decision_reason_APP-PERSONA-6").value == ""


def test_case_panel_is_inline_single_and_dismissible(assessed_pair) -> None:
    """Opening a case hides other applicants; X closes without saving."""
    app = _app(assessed_pair).run()
    assert app.title[0].value == "Review queue"
    assert app.button(key="review_open_APP-PERSONA-3")
    assert app.button(key="review_open_APP-PERSONA-6")
    assert not any(item.value == "Your decision" for item in app.subheader)

    app.button(key="review_open_APP-PERSONA-3").click().run()
    assert any(item.value == "Your decision" for item in app.subheader)
    assert app.session_state["review_open"] == "APP-PERSONA-3"
    visible_markdown = "\n".join(element.value for element in app.markdown)
    assert "Imran Sheikh" in visible_markdown
    assert "Meera Iyer" not in visible_markdown
    assert not any(button.key == "review_open_APP-PERSONA-6" for button in app.button)

    app.button(key="close_review_details_APP-PERSONA-3").click().run()
    assert not any(item.value == "Your decision" for item in app.subheader)
    assert app.session_state["review_open"] is None
    assert pd.isna(get_application("APP-PERSONA-6", assessed_pair).iloc[0]["human_decision"])


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
    app.button(key="review_open_APP-PERSONA-3").click().run()
    app.selectbox(key="review_action_APP-PERSONA-3").select("reject").run()
    app.text_area(key="decision_reason_APP-PERSONA-3").set_value(_REASON).run()
    app.button(key="submit_review_APP-PERSONA-3").click().run()

    assert app.session_state["review_open"] is None
    assert not any(button.key == "review_open_APP-PERSONA-3" for button in app.button)
    app.button(key="review_filter_rejected").click().run()
    assert app.button(key="review_open_APP-PERSONA-3").label == "View"
    assert any("Rejected" in element.value for element in app.markdown)


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
