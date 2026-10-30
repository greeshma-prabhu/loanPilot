"""Human review, sanction, and simulated disbursement workflow tests."""

import math
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from loanpilot.agent.llm import recorded_mode_label
from loanpilot.agent.orchestrator import run_assessment
from loanpilot.agent.policy_engine import pricing_rate
from loanpilot.agent.sanction import (
    DEFAULT_CONDITIONS,
    approve_and_sanction,
    modified_terms_preview,
    run_simulated_disbursement,
    update_conditions,
)
from loanpilot.data.queries import (
    get_application,
    get_disbursement,
    get_review_queue,
    get_sanction,
    get_audit_log,
    record_human_decision,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore
from loanpilot.decisions import HUMAN_ACTIONS, evaluate_human_action

VALID_REASON = "Reviewed the synthetic evidence and documented this decision."
PERSONA_IDS = [f"APP-PERSONA-{number}" for number in range(1, 7)]


@pytest.fixture
def review_store(tmp_path, monkeypatch) -> SQLiteStore:
    """Create six assessed persona cases in an isolated temporary database."""
    monkeypatch.setattr("loanpilot.agent.llm._api_key", lambda: None)
    store = SQLiteStore(tmp_path / "review.db")
    seed_demo_data(store, reset=True)
    with patch("loanpilot.agent.llm._api_key", return_value=None):
        for application_id in PERSONA_IDS:
            run_assessment(application_id, store)
    return store


def test_priya_approval_sanction_and_simulated_disbursement(review_store) -> None:
    """Priya's human approval creates the PDF, sanction, and simulated payout."""
    sanction = approve_and_sanction(
        "APP-PERSONA-1",
        400000,
        36,
        0.115,
        VALID_REASON,
        "Aarav Kulkarni (Credit Analyst)",
        store=review_store,
    )
    saved = get_sanction("APP-PERSONA-1", review_store).iloc[0]
    assert get_application("APP-PERSONA-1", review_store).iloc[0]["stage"] == "Sanction"
    assert saved["sanction_ref"] == sanction["sanction_ref"]
    assert sanction["letter_path"].is_file()
    assert sanction["letter_path"].stat().st_size > 0
    assert sanction["kfs"]["loan_amount"] == 400000
    assert sanction["kfs"]["processing_fee"] == 8000
    assert sanction["kfs"]["net_disbursed"] == 392000
    assert "Illustrative" in sanction["kfs"]["label"]

    payout = run_simulated_disbursement("APP-PERSONA-1", review_store)
    saved_payout = get_disbursement("APP-PERSONA-1", review_store).iloc[0]
    assert payout["mode"] == "simulated"
    assert saved_payout["mode"] == "simulated"
    assert payout["gross_amount"] == 400000
    assert payout["fees"] == 8000
    assert payout["net_amount"] == 392000
    assert get_application("APP-PERSONA-1", review_store).iloc[0]["stage"] == "Disbursed (simulated)"
    actions = get_audit_log("APP-PERSONA-1", review_store)["action"].tolist()
    assert any("Human decision" in action for action in actions)
    assert "Sanction generated" in actions
    assert "Simulated disbursement completed" in actions


def test_imran_rejection_is_not_override(review_store) -> None:
    """Rejecting an AI-declined case does not count as an override."""
    record_human_decision(
        "APP-PERSONA-3",
        "Reject",
        VALID_REASON,
        False,
        "Nisha Desai (Credit Manager)",
        "2026-10-27T10:00:00",
        "Rejected",
        review_store,
    )
    application = get_application("APP-PERSONA-3", review_store).iloc[0]
    assert application["ai_recommendation"] == "Decline"
    assert application["human_decision"] == "Reject"
    assert application["is_override"] == 0
    assert application["stage"] == "Rejected"


def test_approving_imran_is_override_and_reason_is_saved(review_store) -> None:
    """Approving an AI-declined case requires and stores a written override reason."""
    sanction = approve_and_sanction(
        "APP-PERSONA-3",
        100000,
        24,
        0.16,
        "Manager reviewed supporting evidence and accepts this documented exception.",
        "Nisha Desai (Credit Manager)",
        store=review_store,
    )
    application = get_application("APP-PERSONA-3", review_store).iloc[0]
    assert application["human_decision"] == "Approve"
    assert application["is_override"] == 1
    assert "documented exception" in application["human_reason"]
    assert sanction["override"] is True


def test_meera_override_record(review_store) -> None:
    """Meera's human approval records an override, reason, and sanction stage."""
    approve_and_sanction(
        "APP-PERSONA-6",
        450000,
        48,
        0.135,
        "Credit Manager accepts the short tenure based on prior experience and relationship history.",
        "Nisha Desai (Credit Manager)",
        store=review_store,
    )
    application = get_application("APP-PERSONA-6", review_store).iloc[0]
    assert application["ai_recommendation"] == "Decline"
    assert application["human_decision"] == "Approve"
    assert application["is_override"] == 1
    assert len(application["human_reason"]) >= 20
    assert application["stage"] == "Sanction"


@pytest.mark.parametrize("reason", ("", "Looks good"))
def test_human_decision_accepts_empty_or_short_reason(review_store, reason) -> None:
    """Reviewers can save an action with any reason length, including no reason."""
    record_human_decision(
        "APP-PERSONA-1",
        "Approve",
        reason,
        False,
        "Aarav Kulkarni (Credit Analyst)",
        "2026-10-27T10:00:00",
        "Sanction",
        review_store,
    )
    saved = get_application("APP-PERSONA-1", review_store).iloc[0]
    assert saved["human_decision"] == "Approve"
    assert saved["human_reason"] == reason
    assert saved["stage"] == "Sanction"


def test_all_actions_persist_for_each_ai_recommendation(review_store) -> None:
    """All six actions persist with their mapped stage and exact CP-8.2 override flag."""
    application_id = "APP-PERSONA-1"
    for recommendation in ("Approve", "Refer", "Decline"):
        for action_code, action in HUMAN_ACTIONS.items():
            assessment = evaluate_human_action(recommendation, action_code)
            review_store.execute(
                """
                UPDATE cur_applications SET stage = 'Human Review'
                WHERE application_id = ?
                """,
                (application_id,),
            )
            review_store.execute(
                """
                UPDATE cur_decisions
                SET ai_recommendation = ?, human_decision = NULL,
                    human_reason = NULL, is_override = 0, decided_by = NULL,
                    decided_at = NULL
                WHERE application_id = ?
                """,
                (recommendation, application_id),
            )
            record_human_decision(
                application_id,
                action.label,
                VALID_REASON,
                assessment.is_override,
                "Test Reviewer",
                "2026-10-29T12:00:00",
                action.stage,
                review_store,
            )
            saved = get_application(application_id, review_store).iloc[0]
            assert saved["human_decision"] == action.label
            assert saved["stage"] == action.stage
            assert bool(saved["is_override"]) is assessment.is_override


def test_override_rule_is_specific_and_separate_from_difference() -> None:
    """Only approve after decline or reject after approve is a CP-8.2 override."""
    assert evaluate_human_action("Approve", "reject").differs
    assert evaluate_human_action("Approve", "reject").is_override
    assert evaluate_human_action("Decline", "approve").is_override
    assert not evaluate_human_action("Approve", "approve").is_override
    assert evaluate_human_action("Decline", "modify_terms").is_override
    assert not evaluate_human_action("Approve", "refer_up").is_override
    assert evaluate_human_action("Decline", "refer_up").differs


def test_short_imran_approval_reason_can_override(review_store) -> None:
    """An AI-declined case may be approved with a short recorded reason."""
    approve_and_sanction(
        "APP-PERSONA-3",
        100000,
        24,
        0.16,
        "Override",
        "Nisha Desai (Credit Manager)",
        store=review_store,
    )
    application = get_application("APP-PERSONA-3", review_store).iloc[0]
    assert application["stage"] == "Sanction"
    assert application["human_decision"] == "Approve"
    assert application["human_reason"] == "Override"
    assert application["is_override"] == 1
    assert not get_sanction("APP-PERSONA-3", review_store).empty


def test_modify_terms_recalculates_emi_and_warns_above_foir(review_store) -> None:
    """Modified terms return a reducing-balance EMI and over-45% verified FOIR flag."""
    preview = modified_terms_preview(
        amount=900000,
        tenure_months=48,
        annual_rate=0.135,
        existing_emi=12000,
        verified_income=72000,
    )
    monthly_rate = 0.135 / 12
    factor = (1 + monthly_rate) ** 48
    expected_emi = 900000 * monthly_rate * factor / (factor - 1)
    assert math.isclose(preview["emi"], expected_emi, rel_tol=1e-12)
    assert preview["foir_verified"] == pytest.approx((12000 + expected_emi) / 72000)
    assert preview["foir_over_limit"] is True


def test_conditions_block_disbursement_until_complete(review_store) -> None:
    """All selected sanction conditions must be checked before payout."""
    approve_and_sanction(
        "APP-PERSONA-1",
        400000,
        36,
        0.115,
        VALID_REASON,
        "Aarav Kulkarni (Credit Analyst)",
        conditions=list(DEFAULT_CONDITIONS),
        store=review_store,
    )
    with pytest.raises(ValueError, match="conditions"):
        run_simulated_disbursement("APP-PERSONA-1", review_store)

    conditions = [
        {"name": name, "required": True, "complete": True}
        for name in DEFAULT_CONDITIONS
    ]
    update_conditions(
        "APP-PERSONA-1",
        conditions,
        "Aarav Kulkarni (Credit Analyst)",
        review_store,
    )
    payout = run_simulated_disbursement("APP-PERSONA-1", review_store)
    assert payout["mode"] == "simulated"


def test_agent_assessment_never_sanctions(review_store) -> None:
    """The AI orchestrator leaves approval cases in Human Review."""
    application = get_application("APP-PERSONA-1", review_store).iloc[0]
    assert application["ai_recommendation"] == "Approve"
    assert application["stage"] == "Human Review"
    assert get_sanction("APP-PERSONA-1", review_store).empty


def test_review_queue_prioritizes_declines_then_referrals(review_store) -> None:
    """Override candidates and referrals precede cases with an AI approval."""
    queue = get_review_queue(review_store)
    assert len(queue) == 6
    assert queue.iloc[:2]["ai_recommendation"].tolist() == ["Decline", "Decline"]
    assert queue.iloc[2:5]["ai_recommendation"].tolist() == ["Refer", "Refer", "Refer"]


def test_human_review_page_renders_user_created_case(
    review_store, create_user_case
) -> None:
    """The decision-first review workspace opens a user-created application."""
    application_id = create_user_case(
        review_store, "APP-NEW-REVIEW-PAGE", "Review Page Applicant"
    )
    run_assessment(application_id, review_store)
    script = (
        "import streamlit as st\n"
        "st.session_state['auth'] = {'name': 'Test Reviewer', 'role': 'Credit Analyst'}\n"
        "from loanpilot.pages.human_review import render\n"
        "from loanpilot.data.store import SQLiteStore\n"
        f"st.session_state['review_open'] = {application_id!r}\n"
        f"render(SQLiteStore({str(review_store.path)!r}))\n"
    )
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert app.title[0].value == "Review queue"
    assert any(button.label == "Submit decision" for button in app.button)
    assert any(button.label == "Go to Human Review" for button in app.button) is False


def test_recorded_badges_distinguish_authored_and_live_runs() -> None:
    """Recorded mode labels disclose whether replays are authored or live-captured."""
    assert recorded_mode_label("authored sample") == "Recorded (pre-written sample)"
    assert recorded_mode_label("live run 2026-10-27") == "Recorded (live run 2026-10-27)"


def test_sanction_schema_migration_is_safe_and_resettable(tmp_path) -> None:
    """Schema initialization is repeatable and dataset reset empties new tables."""
    store = SQLiteStore(tmp_path / "migration.db")
    seed_demo_data(store, reset=True)
    assert store.table_counts()["cur_sanctions"] == 0
    assert store.table_counts()["cur_disbursements"] == 0
    create_schema(store)
    assert store.table_counts()["cur_applications"] == 66
    seed_demo_data(store, reset=True)
    assert store.table_counts()["cur_sanctions"] == 0
    assert store.table_counts()["cur_disbursements"] == 0


def test_approval_is_the_only_route_from_human_review_to_sanction(review_store) -> None:
    """Non-approval actions cannot create a sanction or set the sanction stage."""
    record_human_decision(
        "APP-PERSONA-2",
        "Refer up",
        VALID_REASON,
        False,
        "Aarav Kulkarni (Credit Analyst)",
        "2026-10-27T10:00:00",
        "Escalated",
        review_store,
    )
    application = get_application("APP-PERSONA-2", review_store).iloc[0]
    assert application["stage"] == "Escalated"
    assert get_sanction("APP-PERSONA-2", review_store).empty


def test_modified_terms_action_is_recorded_as_human_override(review_store) -> None:
    """Modified terms are a human approval and use the explicit override rule."""
    approve_and_sanction(
        "APP-PERSONA-3",
        200000,
        36,
        0.16,
        "Manager approved revised amount after reviewing the case documents.",
        "Nisha Desai (Credit Manager)",
        decision_action="Modify terms",
        store=review_store,
    )
    application = get_application("APP-PERSONA-3", review_store).iloc[0]
    assert application["human_decision"] == "Modify terms"
    assert application["is_override"] == 1
    assert pricing_rate(668) == 0.16
