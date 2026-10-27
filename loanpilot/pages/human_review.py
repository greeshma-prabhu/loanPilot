"""Human review queue and decision workspace."""

import json
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from loanpilot.agent.policy_engine import pricing_rate
from loanpilot.agent.sanction import (
    DEFAULT_CONDITIONS,
    approve_and_sanction,
    modified_terms_preview,
)
from loanpilot.agent.tools import bureau_check, kyc_check
from loanpilot.components import calculate_foir, fmt_inr, status_chip
from loanpilot.data.queries import (
    get_agent_trace,
    get_application,
    get_review_queue,
    record_human_decision,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import render_disclaimer, render_header

REVIEWERS = ("Aarav Kulkarni (Credit Analyst)", "Nisha Desai (Credit Manager)")
ACTIONS = (
    "Approve",
    "Approve with conditions",
    "Modify terms",
    "Refer up",
    "Reject",
    "Request documents",
)


def is_override_decision(ai_decision: str | None, human_action: str) -> bool:
    """Return whether the explicitly defined CP-8.2 override conditions apply."""
    return (
        human_action in {"Approve", "Approve with conditions", "Modify terms"}
        and ai_decision == "Decline"
    ) or (human_action == "Reject" and ai_decision == "Approve")


def _age_days(submitted_at: str) -> int:
    """Return whole elapsed days from the ISO timestamp."""
    try:
        submitted = datetime.fromisoformat(submitted_at)
    except ValueError:
        return 0
    if submitted.tzinfo:
        submitted = submitted.replace(tzinfo=None)
    return max(0, (datetime.now() - submitted).days)


def _load_data(store: SQLiteStore) -> None:
    """Generate the synthetic sample cases in an empty database."""
    counts = seed_demo_data(store, reset=True)
    st.toast("Demo data loaded. " + ", ".join(f"{key}: {value}" for key, value in counts.items()))


def _render_queue(queue: pd.DataFrame) -> str:
    """Show queue counts/table and return its selected application id."""
    st.subheader("Reviewer queue")
    if queue.empty:
        st.info("There are no applications waiting in Human Review.")
        return ""
    frame = pd.DataFrame(
        {
            "Application": queue["application_id"],
            "Applicant": queue["applicant"],
            "AI recommendation": queue["ai_recommendation"].fillna("—"),
            "Risk band": queue["risk_band"].fillna("—"),
            "Age (days)": queue["submitted_at"].map(_age_days),
            "Priority": queue["ai_recommendation"].map(
                lambda value: "Override candidate"
                if value == "Decline"
                else "Referral"
                if value == "Refer"
                else "Standard"
            ),
        }
    )
    st.metric("Cases awaiting human review", len(queue))
    st.dataframe(frame, width="stretch", hide_index=True)
    session_selected = st.session_state.get("review_application")
    application_ids = queue["application_id"].tolist()
    index = application_ids.index(session_selected) if session_selected in application_ids else 0
    return st.selectbox(
        "Open review case",
        application_ids,
        index=index,
        format_func=lambda application_id: (
            f"{application_id} · "
            f"{queue.loc[queue.application_id == application_id, 'applicant'].iloc[0]}"
        ),
        key="review_application",
    )


def _parse_assessment(application_id: str, store: SQLiteStore) -> dict[str, Any] | None:
    """Load assessment summary fields from the persisted trace and decision."""
    trace = get_agent_trace(application_id, store=store)
    application = get_application(application_id, store)
    if trace.empty or application.empty:
        return None
    by_step = {
        int(row["step_no"]): json.loads(row["tool_calls_json"])
        for _, row in trace.iterrows()
    }
    if not all(step in by_step for step in (1, 2, 3, 5)):
        return None
    reasons = json.loads(application.iloc[0]["ai_reasons_json"] or "{}")
    return {
        "application": application.iloc[0],
        "extraction": by_step[1].get("result", {}),
        "finances": by_step[2].get("result", {}),
        "policy": by_step[3].get("result", {}).get("policy", {}),
        "recommendation": application.iloc[0]["ai_recommendation"],
        "risk_band": reasons.get("risk_band", "Unavailable"),
        "reasons_for": reasons.get("reasons_for", []),
        "reasons_against": reasons.get("reasons_against", []),
        "conditions": reasons.get("conditions", []),
        "explanation": reasons.get("explanation", "No explanation recorded."),
        "mode": reasons.get("explanation_mode", "Recorded (pre-written sample)"),
    }


def _render_ai_summary(summary: dict[str, Any]) -> None:
    """Render recommendation summary and traceable reasons."""
    st.markdown("#### AI summary")
    st.markdown(f"**Recommendation:** {summary['recommendation']}")
    st.markdown(f"**Risk band:** {summary['risk_band']}")
    st.markdown(f"**Explanation mode:** {status_chip(summary['mode'], 'info')}", unsafe_allow_html=True)
    st.write(summary["explanation"])
    st.markdown("**Top reasons for**")
    for reason in summary["reasons_for"][:3]:
        st.write(f"- {reason['clause_id']}: {reason['text']}")
    st.markdown("**Top reasons against**")
    if summary["reasons_against"]:
        for reason in summary["reasons_against"][:3]:
            st.write(f"- {reason['clause_id']}: {reason['text']}")
    else:
        st.caption("No adverse policy findings.")


def _render_evidence(
    application_id: str,
    summary: dict[str, Any],
    store: SQLiteStore,
) -> tuple[float, float, int | None]:
    """Show data evidence and return income/EMI/score values for term editing."""
    st.markdown("#### Evidence")
    finances = summary["finances"]
    stated_income = float(finances.get("stated_income") or 0)
    verified_income = float(finances.get("verified_income") or 0)
    existing_emi = float(finances.get("existing_emi") or 0)
    proposed_emi = float(finances.get("proposed_emi") or 0)
    st.write(f"Stated payslip income: **{fmt_inr(stated_income)}**")
    st.write(f"Verified salary-credit average: **{fmt_inr(verified_income)}**")
    stated_foir = calculate_foir(existing_emi, proposed_emi, stated_income)
    verified_foir = calculate_foir(existing_emi, proposed_emi, verified_income)
    st.write(f"FOIR · stated income: **{stated_foir:.1%}**" if stated_foir is not None else "FOIR · stated income: unavailable")
    st.write(f"FOIR · verified income: **{verified_foir:.1%}**" if verified_foir is not None else "FOIR · verified income: unavailable")
    reconciliation = summary["extraction"].get("reconciliation", {})
    st.write(
        "Document flags: "
        f"payslip arithmetic {'pass' if reconciliation.get('payslip_arithmetic_matches') else 'fail'}; "
        f"salary credits {'within' if reconciliation.get('salary_credits_within_tolerance') else 'outside'} tolerance; "
        f"employer {'matches' if reconciliation.get('employer_matches') else 'differs'}."
    )
    bureau = bureau_check(application_id, store)
    kyc = kyc_check(application_id, store)
    st.write(
        f"Bureau: score {bureau.get('score') if bureau.get('score') is not None else 'thin file'}; "
        f"max DPD {bureau.get('max_dpd_24m', '—')}; written off "
        f"{'yes' if bureau.get('written_off') else 'no'}."
    )
    st.write(
        f"KYC: PAN {kyc.get('pan_status', 'unavailable')}; "
        f"name match {kyc.get('name_match_score', 'unavailable')}."
    )
    st.markdown("**Policy results**")
    clauses = summary["policy"].get("clauses", [])
    if clauses:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Clause": row["clause_id"],
                        "Rule": row["rule_text"],
                        "Observed": json.dumps(row["observed"], ensure_ascii=False),
                        "Result": row["status"].title(),
                    }
                    for row in clauses
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    return (
        verified_income,
        existing_emi,
        bureau.get("score"),
    )


def _save_decision(
    application_id: str,
    action: str,
    reason: str,
    reviewer: str,
    ai_decision: str,
    store: SQLiteStore,
) -> None:
    """Persist non-approval decisions and route the case to its next stage."""
    next_stage = {
        "Reject": "Rejected",
        "Refer up": "Escalated",
        "Request documents": "Awaiting documents",
    }[action]
    record_human_decision(
        application_id,
        action,
        reason,
        is_override_decision(ai_decision, action),
        reviewer,
        datetime.now().isoformat(timespec="seconds"),
        next_stage,
        store,
    )
    st.session_state["review_notice"] = f"{action} recorded; stage is {next_stage}."


def _render_decision_panel(
    application_id: str,
    summary: dict[str, Any],
    store: SQLiteStore,
    verified_income: float,
    existing_emi: float,
    score: int | None,
) -> None:
    """Render reviewer inputs, override warning, and decision submission."""
    st.markdown("#### Human decision")
    st.caption("Fictional reviewer names only; this demo has no authentication.")
    reviewer = st.selectbox("Reviewer", REVIEWERS, key=f"reviewer_{application_id}")
    action = st.selectbox("Action", ACTIONS, key=f"review_action_{application_id}")
    override = is_override_decision(summary["recommendation"], action)
    if override:
        st.warning(
            "This differs from the AI recommendation (CP-8.2): a written reason is required"
        )
    amount = float(summary["application"]["requested_amount"])
    tenure = int(summary["application"]["tenure_months"])
    rate = pricing_rate(score)
    if action == "Modify terms":
        if rate is None:
            st.warning("No CP-7.1 grid rate is available; terms cannot be recalculated.")
        amount = st.number_input(
            "Modified amount (Rs)",
            min_value=50000.0,
            max_value=1500000.0,
            value=float(summary["application"]["requested_amount"]),
            step=10000.0,
            key=f"modified_amount_{application_id}",
        )
        tenure = st.number_input(
            "Modified tenure (months)",
            min_value=12,
            max_value=60,
            value=int(summary["application"]["tenure_months"]),
            step=1,
            key=f"modified_tenure_{application_id}",
        )
        if rate is not None:
            preview = modified_terms_preview(
                amount,
                int(tenure),
                rate,
                existing_emi,
                verified_income,
            )
            st.write(
                f"Recalculated EMI: **{fmt_inr(preview['emi'])}** at {rate:.1%}."
            )
            if preview["foir_verified"] is not None:
                st.write(f"FOIR on verified income: **{preview['foir_verified']:.1%}**")
                if preview["foir_over_limit"]:
                    st.warning("Modified terms remain above the 45% FOIR pass limit.")
    conditions = []
    if action == "Approve with conditions":
        conditions = st.multiselect(
            "Required conditions",
            DEFAULT_CONDITIONS,
            default=list(DEFAULT_CONDITIONS),
            key=f"conditions_{application_id}",
        )
        st.caption("Each selected condition must be marked complete before simulated disbursement.")

    with st.form(f"human_decision_form_{application_id}"):
        reason = st.text_area(
            "Mandatory written reason (at least 20 characters)",
            key=f"decision_reason_{application_id}",
        )
        submitted = st.form_submit_button("Submit human decision", width="stretch")
    if submitted:
        if len(reason.strip()) < 20:
            st.error("Enter a written reason of at least 20 characters.")
            return
        if action == "Approve with conditions" and not conditions:
            st.error("Choose at least one required condition.")
            return
        if action in {"Approve", "Approve with conditions", "Modify terms"}:
            if rate is None:
                st.error("No CP-7.1 rate is available for this application.")
                return
            try:
                result = approve_and_sanction(
                    application_id,
                    amount,
                    int(tenure),
                    rate,
                    reason,
                    reviewer,
                    conditions=conditions,
                    decision_action=action,
                    store=store,
                )
            except ValueError as error:
                st.error(str(error))
                return
            st.session_state["review_notice"] = (
                f"Human approval recorded. Sanction {result['sanction_ref']} created."
            )
        else:
            try:
                _save_decision(
                    application_id,
                    action,
                    reason,
                    reviewer,
                    summary["recommendation"],
                    store,
                )
            except ValueError as error:
                st.error(str(error))
                return
        st.rerun()


def render(store: SQLiteStore | None = None) -> None:
    """Render the review queue and three-column decision workspace."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    render_header(
        "Human Review",
        "A human decision is required before sanction. Fictional reviewers are shown; this demo has no authentication.",
        "OPERATE  /  CREDIT DESK",
    )
    queue = get_review_queue(store)
    if queue.empty and store.table_counts().get("cur_applications", 0) == 0:
        st.info("No demo applications are loaded yet. Load the synthetic sample dataset to begin.")
        st.button(
            "Load demo data",
            on_click=_load_data,
            args=(store,),
            key="load_review_data",
        )
        return
    selected = _render_queue(queue)
    notice = st.session_state.pop("review_notice", None)
    if notice:
        st.success(notice)
    if not selected:
        return
    summary = _parse_assessment(selected, store)
    if summary is None:
        st.warning("Run AI Assessment before human review. The agent cannot sanction a case.")
        return

    st.subheader("Review workspace")
    columns = st.columns([1, 1.15, 1])
    with columns[0]:
        with st.container(border=True):
            _render_ai_summary(summary)
    with columns[1]:
        with st.container(border=True):
            (
                verified_income,
                existing_emi,
                score,
            ) = _render_evidence(selected, summary, store)
    with columns[2]:
        with st.container(border=True):
            _render_decision_panel(
                selected,
                summary,
                store,
                verified_income,
                existing_emi,
                score,
            )
