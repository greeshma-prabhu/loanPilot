"""Isolated, synthetic walkthrough of the LoanPilot personal-loan journey."""

import math
import time
from typing import Any

import streamlit as st

from loanpilot.agent.policy_engine import (
    evaluate_policy,
    max_affordable_amount,
    pricing_rate,
)
from loanpilot.agent.sanction import reducing_balance_emi
from loanpilot.components import calculate_foir, fmt_inr, status_chip
from loanpilot.decisions import HUMAN_ACTIONS, evaluate_human_action
from loanpilot.theme import render_disclaimer, render_header

ASSESSMENT_WAIT_SECONDS = 5
STAGES = (
    "Application Submission",
    "AI Assessment",
    "Human Review",
    "Final Decision",
)
APPLICANT = {
    "name": "Priya Menon",
    "employment": "Salaried",
    "monthly_income": 75_000,
    "existing_emi": 10_000,
    "requested_amount": 300_000,
    "tenure_months": 36,
    "purpose": "Travel",
    "credit_score": 742,
}
_STATE_KEYS = (
    "guided_demo_started",
    "guided_demo_step",
    "guided_demo_assessment_started_at",
    "guided_demo_assessment_ready",
    "guided_demo_action",
    "guided_demo_reviewer_rationale",
)


def _assessment_results() -> dict[str, Any]:
    """Calculate synthetic affordability and policy signals without persistence."""
    rate = pricing_rate(APPLICANT["credit_score"])
    if rate is None:
        raise RuntimeError("The configured policy has no rate for the demo score.")
    emi = reducing_balance_emi(
        APPLICANT["requested_amount"], rate, APPLICANT["tenure_months"]
    )
    foir = calculate_foir(
        APPLICANT["existing_emi"], emi, APPLICANT["monthly_income"]
    )
    if foir is None:
        raise RuntimeError("The synthetic income must be positive for FOIR.")

    features = {
        "age": 32,
        "current_tenure_months": 36,
        "total_experience_months": 120,
        "net_monthly_income": APPLICANT["monthly_income"],
        "requested_amount": APPLICANT["requested_amount"],
        "tenure_months": APPLICANT["tenure_months"],
    }
    reconciliation = {
        "payslip_arithmetic_matches": True,
        "salary_credits_within_tolerance": True,
        "employer_matches": True,
        "salary_credit_variance_pct": 0.0,
    }
    bureau = {
        "score": APPLICANT["credit_score"],
        "thin_file": False,
        "max_dpd_24m": 0,
        "enquiries_6m": 1,
    }
    policy = evaluate_policy(
        features=features,
        extracted={"net": APPLICANT["monthly_income"]},
        reconciliation=reconciliation,
        bureau=bureau,
        kyc={"status": "verified", "pan_status": "verified", "name_match": 0.98},
        finances={"foir_stated": foir, "foir_verified": foir},
    )
    affordable = max_affordable_amount(
        APPLICANT["monthly_income"],
        APPLICANT["existing_emi"],
        rate,
        APPLICANT["tenure_months"],
    )
    illustrative_limit = math.floor(affordable / 1000) * 1000
    return {
        "rate": rate,
        "emi": emi,
        "foir": foir,
        "affordable_amount": illustrative_limit,
        "policy": policy,
    }


def _assessment_remaining_seconds(
    started_at: float, *, now: float | None = None
) -> float:
    """Return the remaining simulated assessment delay, clamped to its duration."""
    current_time = time.time() if now is None else now
    elapsed = max(0.0, current_time - started_at)
    return max(0.0, ASSESSMENT_WAIT_SECONDS - elapsed)


def _start_demo() -> None:
    """Start a fresh walkthrough in transient Streamlit session state."""
    st.session_state["guided_demo_started"] = True
    st.session_state["guided_demo_step"] = 0
    st.session_state["guided_demo_assessment_ready"] = False
    st.session_state.pop("guided_demo_assessment_started_at", None)
    st.session_state.pop("guided_demo_action", None)
    st.session_state.pop("guided_demo_reviewer_rationale", None)


def _go_to_step(step: int) -> None:
    """Move through the local journey, starting the assessment timer on entry."""
    st.session_state["guided_demo_step"] = step
    if step == 1 and not st.session_state.get("guided_demo_assessment_ready"):
        st.session_state.setdefault(
            "guided_demo_assessment_started_at", time.time()
        )


def _restart_demo() -> None:
    """Clear only this walkthrough's transient state."""
    for key in _STATE_KEYS:
        st.session_state.pop(key, None)


def _render_journey(current_step: int | None) -> None:
    """Show the four stages and mark completed/current journey progress."""
    with st.container(key="guided-demo-journey"):
        columns = st.columns(4, gap="large")
        for index, (column, stage) in enumerate(zip(columns, STAGES)):
            if current_step is None:
                kind, label = "neutral", f"{index + 1}. {stage}"
            elif index < current_step:
                kind, label = "success", f"✓  {stage}"
            elif index == current_step:
                kind, label = "info", f"{index + 1}. {stage}"
            else:
                kind, label = "neutral", f"{index + 1}. {stage}"
            with column:
                st.markdown(status_chip(label, kind), unsafe_allow_html=True)


def _render_submission() -> None:
    """Render the synthetic applicant details and intake checklist."""
    st.subheader("Application Submission")
    st.caption("Application captured and validated before assessment.")
    with st.container(border=True):
        st.markdown(f"### {APPLICANT['name']}")
        details = st.columns(3, gap="large")
        details[0].metric("Employment", APPLICANT["employment"])
        details[1].metric("Monthly net income", fmt_inr(APPLICANT["monthly_income"]))
        details[2].metric("Existing monthly EMI", fmt_inr(APPLICANT["existing_emi"]))
        details = st.columns(3, gap="large")
        details[0].metric("Requested amount", fmt_inr(APPLICANT["requested_amount"]))
        details[1].metric("Tenure", f"{APPLICANT['tenure_months']} months")
        details[2].metric("Loan purpose", APPLICANT["purpose"])
        st.markdown("**Document checklist**")
        st.write(
            "✓ Identity and address documents · ✓ Recent payslips · "
            "✓ Bank statements — available and consistent (synthetic)"
        )
    with st.expander("What happens in this step?"):
        st.write(
            "The applicant’s details and supporting documents are captured, "
            "checked for completeness, and prepared for assessment."
        )


def _render_assessment_wait() -> None:
    """Poll the simulated five-second assessment without blocking the app."""
    started_at = float(st.session_state["guided_demo_assessment_started_at"])

    @st.fragment(run_every=1)
    def wait_for_assessment() -> None:
        remaining = _assessment_remaining_seconds(started_at)
        progress = 1 - remaining / ASSESSMENT_WAIT_SECONDS
        st.progress(progress, text="Preparing the illustrative assessment...")
        if remaining > 0:
            st.caption(
                "Checking repayment capacity, synthetic document consistency, "
                "and the local illustrative policy."
            )
        else:
            st.session_state["guided_demo_assessment_ready"] = True
            st.rerun()

    wait_for_assessment()


def _render_assessment() -> None:
    """Render the assessment wait, then the policy and repayment results."""
    st.subheader("AI Assessment")
    if not st.session_state.get("guided_demo_assessment_ready"):
        _render_assessment_wait()
        return

    results = _assessment_results()
    policy = results["policy"]
    columns = st.columns(3, gap="large")
    columns[0].metric("Proposed monthly EMI", fmt_inr(results["emi"]))
    columns[1].metric("FOIR", f"{results['foir']:.1%}")
    columns[2].metric("Illustrative policy rate", f"{results['rate']:.1%} p.a.")
    st.markdown("**Illustrative checks**")
    for label, detail in (
        ("Income and repayment capacity", "Income supports the proposed repayment."),
        ("Documents", "Synthetic documents are available and consistent."),
        (
            "Credit information",
            f"Synthetic credit score: {APPLICANT['credit_score']}; "
            "no bureau provider was contacted.",
        ),
    ):
        st.markdown(f"- **{label}:** {detail}")
    for clause in policy["clauses"]:
        status = str(clause["status"])
        kind = {"pass": "success", "refer": "warning", "decline": "danger"}.get(
            status, "neutral"
        )
        st.markdown(
            f"- {clause['rule_text']} "
            + status_chip(status.title(), kind),
            unsafe_allow_html=True,
        )
    st.markdown(
        "**Illustrative AI recommendation:** "
        + status_chip(
            policy["recommendation"],
            "success" if policy["recommendation"] == "Approve" else "warning",
        ),
        unsafe_allow_html=True,
    )
    with st.expander("What happens in this step?"):
        st.write(
            "LoanPilot compares the supplied evidence with affordability and "
            "configured policy rules. This demo uses synthetic information and "
            "does not call an external credit bureau, KYC provider, or banking API."
        )


def _render_human_review() -> None:
    """Let the presenter choose any human action independent of AI advice."""
    st.subheader("Human Review")
    results = _assessment_results()
    st.markdown("**Evidence available to the reviewer**")
    st.write(
        f"Income {fmt_inr(APPLICANT['monthly_income'])} · "
        f"proposed EMI {fmt_inr(results['emi'])} · FOIR {results['foir']:.1%} · "
        "consistent synthetic documents · synthetic credit score 742"
    )
    st.markdown(
        "**AI recommendation:** "
        + status_chip(results["policy"]["recommendation"], "success"),
        unsafe_allow_html=True,
    )
    recommendation = results["policy"]["recommendation"]
    suggested_code = {
        "Approve": "approve",
        "Refer": "refer_up",
        "Decline": "reject",
    }.get(recommendation)
    suggested_action = (
        HUMAN_ACTIONS[suggested_code].label if suggested_code else "No suggested action"
    )
    st.caption(
        "A reviewer considers the evidence and chooses an action independently "
        "of the AI recommendation."
    )
    st.caption(f"Suggested for this story: {suggested_action}")
    action_code = st.selectbox(
        "Simulated reviewer action",
        ["", *HUMAN_ACTIONS],
        format_func=lambda code: (
            "Choose an action" if not code else HUMAN_ACTIONS[code].label
        ),
        index=0,
        key="guided_demo_action",
    )
    action_assessment = (
        evaluate_human_action(recommendation, action_code) if action_code else None
    )
    if action_assessment and action_assessment.differs:
        notice = (
            "This differs from the AI recommendation (CP-8.2). "
            "You may add a reason to document your decision."
        )
        st.warning(f"Override: {notice}" if action_assessment.is_override else notice)
    st.text_area(
        "Decision reason (optional)",
        key="guided_demo_reviewer_rationale",
        help="This rationale is kept only in the current demo session.",
    )
    with st.expander("What happens in this step?"):
        st.write(
            "A human reviewer checks the evidence and makes the final decision. "
            "The AI recommendation is advisory; the reviewer may choose any action."
        )


def _reviewer_decision_is_valid() -> bool:
    """Require a selected human action; recording a reason is optional."""
    action_code = st.session_state.get("guided_demo_action", "")
    return action_code in HUMAN_ACTIONS


def _render_decision() -> None:
    """Show the selected human outcome and explicitly non-binding next steps."""
    st.subheader("Final Decision")
    results = _assessment_results()
    action_code = st.session_state.get("guided_demo_action", "")
    reason = str(st.session_state.get("guided_demo_reviewer_rationale", "")).strip()
    if action_code not in HUMAN_ACTIONS:
        st.info("Choose an action to continue.")
        return
    action = HUMAN_ACTIONS[action_code]
    action_assessment = evaluate_human_action(
        results["policy"]["recommendation"], action_code
    )
    if action_code in {"approve", "approve_with_conditions", "modify_terms"}:
        approved_amount = min(
            APPLICANT["requested_amount"], results["affordable_amount"]
        )
        kind = "success"
    elif action_code == "reject":
        approved_amount = None
        kind = "danger"
    else:
        approved_amount = None
        kind = "warning"

    st.markdown(
        status_chip(f"{action.label} – Illustrative Demo", kind),
        unsafe_allow_html=True,
    )
    st.write(f"**Your decision:** {action.label}")
    st.write(f"**AI recommendation:** {results['policy']['recommendation']}")
    st.write(f"**Override:** {'Yes' if action_assessment.is_override else 'No'}")
    st.write(f"**Reason:** {reason or 'No reason recorded.'}")
    st.write(f"**New stage:** {action.stage}")
    columns = st.columns(3, gap="large")
    columns[0].metric("Requested amount", fmt_inr(APPLICANT["requested_amount"]))
    columns[1].metric(
        "Illustrative approved amount",
        fmt_inr(approved_amount) if approved_amount is not None else "Not approved",
    )
    columns[2].metric(
        "Tenure / rate",
        f"{APPLICANT['tenure_months']} months · {results['rate']:.1%} p.a.",
    )
    st.metric("Estimated monthly EMI", fmt_inr(results["emi"]))
    next_step = {
        "Sanction": "Complete sanction documentation and authorized verification.",
        "Escalated": "Refer the application to the next authorized credit officer.",
        "Rejected": "No further loan processing is shown for this illustrative case.",
        "Awaiting documents": "Collect the requested documents and resume review.",
    }[action.stage]
    st.markdown("**Next step**")
    st.write(next_step)
    st.info(
        "This is a simulated result using synthetic applicant data, not a real "
        "loan sanction or disbursement."
    )
    with st.expander("What happens in this step?"):
        st.write(
            "A production decision proceeds only through the institution’s "
            "authorized approval, documentation, and disbursement controls."
        )


def render() -> None:
    """Render the session-only guided lending journey."""
    render_disclaimer()
    st.markdown(
        """
        <style>
        @media (max-width: 640px) {
            .st-key-guided-demo-journey [data-testid="stHorizontalBlock"],
            .st-key-guided-demo-controls [data-testid="stHorizontalBlock"] {
                flex-direction: column !important;
                gap: .35rem !important;
            }
            .st-key-guided-demo-journey [data-testid="stColumn"],
            .st-key-guided-demo-controls [data-testid="stColumn"] {
                width: 100% !important;
                max-width: 100% !important;
                min-width: 0 !important;
                flex: 1 1 100% !important;
            }
            .st-key-guided-demo-controls button {
                width: 100% !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    render_header(
        "Guided Loan Journey",
        "Explore how a personal-loan application moves from submission to the final decision.",
    )
    st.info(
        "Illustrative demo using synthetic applicant data. "
        "No real loan decision or money movement occurs."
    )
    started = bool(st.session_state.get("guided_demo_started"))
    current_step = int(st.session_state.get("guided_demo_step", 0)) if started else None
    _render_journey(current_step)

    if not started:
        st.button(
            "Start Guided Demo",
            key="guided_demo_start",
            type="primary",
            on_click=_start_demo,
        )
        return

    st.caption(f"Step {current_step + 1} of {len(STAGES)}")
    if current_step == 0:
        _render_submission()
    elif current_step == 1:
        _render_assessment()
    elif current_step == 2:
        _render_human_review()
    else:
        _render_decision()

    st.divider()
    is_waiting = current_step == 1 and not st.session_state.get(
        "guided_demo_assessment_ready"
    )
    override_invalid = current_step == 2 and not _reviewer_decision_is_valid()
    with st.container(key="guided-demo-controls"):
        controls = st.columns(3, gap="large")
        controls[0].button(
            "Previous Step",
            key="guided_demo_previous",
            disabled=current_step == 0,
            on_click=_go_to_step,
            args=(max(0, current_step - 1),),
        )
        if current_step < len(STAGES) - 1:
            controls[1].button(
                "Next Step",
                key="guided_demo_next",
                type="primary",
                disabled=is_waiting or override_invalid,
                on_click=_go_to_step,
                args=(current_step + 1,),
            )
        controls[2].button(
            "Restart Demo",
            key="guided_demo_restart",
            on_click=_restart_demo,
        )
