"""Human review queue and decision workspace."""

import json
from datetime import datetime
from html import escape
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
    get_documents,
    get_review_queue,
    list_applications,
    record_human_decision,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import render_disclaimer, render_header
from loanpilot.components import render_decision_card, render_why

REVIEWERS = (
    "Aarav Kulkarni (Credit Analyst)",
    "Nisha Desai (Credit Manager)",
    "Greeshma Prabhu",
)
ACTIONS = {
    "approve": "Approve",
    "approve_with_conditions": "Approve with conditions",
    "modify_terms": "Modify terms",
    "refer_up": "Refer up",
    "reject": "Reject",
    "request_documents": "Request documents",
}
_ACTION_STAGES = {
    "approve": "Sanction",
    "approve_with_conditions": "Sanction",
    "modify_terms": "Sanction",
    "refer_up": "Escalated",
    "reject": "Rejected",
    "request_documents": "Awaiting documents",
}


def is_override_decision(ai_decision: str | None, action_code: str) -> bool:
    """Return whether the explicitly defined CP-8.2 override conditions apply."""
    return (
        action_code in {"approve", "approve_with_conditions", "modify_terms"}
        and ai_decision == "Decline"
    ) or (action_code == "reject" and ai_decision == "Approve")


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


def _open_overview() -> None:
    """Open Overview so the presenter can prepare the demo cases."""
    from loanpilot.navigation import OPERATE_PAGES

    st.switch_page(OPERATE_PAGES["overview"])


def _render_queue(queue: pd.DataFrame, store: SQLiteStore) -> str:
    """Show queue counts/table and return its selected application id."""
    st.subheader("Reviewer queue")
    if queue.empty:
        cases = list_applications({"demo_only": True}, store)
        has_assessments = (
            not cases.empty
            and (
                cases["ai_recommendation"].notna()
                & cases["ai_recommendation"].astype(str).str.strip().ne("")
            ).any()
        )
        if not has_assessments:
            st.info(
                "No AI assessments are saved yet. Prepare the demo cases on Overview "
                "to populate this queue."
            )
            st.button(
                "Prepare demo on Overview",
                on_click=_open_overview,
                key="review_prepare_demo",
            )
        else:
            st.info("There are no applications waiting in Human Review.")
        return ""
    st.metric("Cases awaiting human review", len(queue))
    body = []
    for _, row in queue.iterrows():
        recommendation = str(row["ai_recommendation"] or "—")
        risk = str(row["risk_band"] or "—")
        recommendation_kind = (
            "success" if recommendation == "Approve"
            else "warning" if recommendation == "Refer"
            else "danger" if recommendation == "Decline"
            else "neutral"
        )
        risk_kind = (
            "success" if risk == "Low"
            else "warning" if risk == "Medium"
            else "danger" if risk == "High"
            else "neutral"
        )
        body.append(
            "<tr>"
            f"<td>{escape(str(row['applicant']))}</td>"
            f"<td>{status_chip(recommendation, recommendation_kind)}</td>"
            f"<td>{status_chip(risk, risk_kind)}</td>"
            f"<td>{_age_days(row['submitted_at'])}</td>"
            "</tr>"
        )
    st.markdown(
        '<div class="lp-table-wrap"><table class="lp-data-table">'
        "<thead><tr><th>Applicant</th><th>AI recommendation</th><th>Risk</th>"
        f"<th>Age (days)</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>",
        unsafe_allow_html=True,
    )
    session_selected = st.session_state.get("review_application")
    application_ids = queue["application_id"].tolist()
    index = application_ids.index(session_selected) if session_selected in application_ids else 0
    selected_application = st.selectbox(
        "Open review case",
        application_ids,
        index=index,
        format_func=lambda application_id: (
            f"{queue.loc[queue.application_id == application_id, 'applicant'].iloc[0]}"
        ),
        key="review_application",
    )
    with st.expander("Selected case reference"):
        st.code(str(selected_application))
    return selected_application


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
        "bureau": by_step[3].get("result", {}).get("bureau", {}),
        "kyc": by_step[3].get("result", {}).get("kyc", {}),
        "policy": by_step[3].get("result", {}).get("policy", {}),
        "risk": by_step[4].get("result", {}),
        "pricing": by_step[5].get("result", {}).get("pricing", {}),
        "counterfactual": by_step[5].get("result", {}).get("counterfactual", {}),
        "recommendation": application.iloc[0]["ai_recommendation"],
        "risk_band": reasons.get("risk_band", "Unavailable"),
        "reasons_for": reasons.get("reasons_for", []),
        "reasons_against": reasons.get("reasons_against", []),
        "conditions": reasons.get("conditions", []),
        "explanation": reasons.get("explanation", "No explanation recorded."),
        "mode": reasons.get("explanation_mode", "Recorded (pre-written sample)"),
    }


def _submit_review_decision(
    application_id: str,
    ai_decision: str,
    store: SQLiteStore,
    default_amount: float,
    default_tenure: int,
    verified_income: float,
    existing_emi: float,
    score: int | None,
) -> None:
    """Read the current keyed widget values and persist the selected action."""
    error_key = f"review_error_{application_id}"
    action_code = str(st.session_state.get(f"review_action_{application_id}", ""))
    action = ACTIONS.get(action_code)
    if action is None:
        st.session_state[error_key] = "Select a valid review action."
        return
    reviewer = str(st.session_state.get(f"reviewer_{application_id}", REVIEWERS[0]))
    reason = str(st.session_state.get(f"decision_reason_{application_id}", "")).strip()
    if len(reason) < 20:
        st.session_state[error_key] = "Enter a written reason of at least 20 characters."
        return

    rate = pricing_rate(score)
    amount = float(st.session_state.get(f"modified_amount_{application_id}", default_amount))
    tenure = int(st.session_state.get(f"modified_tenure_{application_id}", default_tenure))
    conditions = list(st.session_state.get(f"conditions_{application_id}", DEFAULT_CONDITIONS))
    override = is_override_decision(ai_decision, action_code)
    try:
        if action_code in {"approve", "approve_with_conditions", "modify_terms"}:
            if rate is None:
                raise ValueError("No CP-7.1 rate is available for this application.")
            if action_code == "approve_with_conditions" and not conditions:
                raise ValueError("Choose at least one required condition.")
            approve_and_sanction(
                application_id,
                amount,
                tenure,
                rate,
                reason,
                reviewer,
                conditions=conditions if action_code == "approve_with_conditions" else None,
                decision_action=action,
                store=store,
            )
        else:
            record_human_decision(
                application_id,
                action,
                reason,
                override,
                reviewer,
                datetime.now().isoformat(timespec="seconds"),
                _ACTION_STAGES[action_code],
                store,
            )
    except ValueError as error:
        st.session_state[error_key] = str(error)
        return

    st.session_state["review_result_application_id"] = application_id
    st.session_state.pop(error_key, None)
    st.session_state.pop("review_application", None)


def _render_result_card(application_id: str, store: SQLiteStore) -> None:
    """Read and display the committed reviewer outcome and the next step."""
    saved = get_application(application_id, store)
    if saved.empty:
        st.error(f"Could not reload the saved case {application_id}.")
        return
    case = saved.iloc[0]
    decision = str(case["human_decision"] or "Unavailable")
    stage = str(case["stage"])
    override = bool(case["is_override"])
    if stage == "Rejected":
        next_step = "Removed from the active queue."
    elif stage == "Sanction":
        next_step = "Review the sanction letter, then run simulated disbursement."
    elif stage == "Escalated":
        next_step = "Await a credit manager review."
    else:
        next_step = "Await the requested documents before reassessment."
    st.success(
        f"Saved from the database: {case['name']} — {decision}. "
        f"Override: {'Yes' if override else 'No'}. Stage: {stage}. {next_step}"
    )
    st.caption(f"Written reason: {case['human_reason']}")
    st.button(
        "Back to reviewer queue",
        key="review_clear_result",
        on_click=lambda: st.session_state.pop("review_result_application_id", None),
    )
    st.button(
        "Back to Overview",
        key="review_back_overview",
        on_click=_back_to_overview,
    )


def _back_to_overview() -> None:
    """Return to the portfolio command centre after a saved decision."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state.pop("review_result_application_id", None)
    st.switch_page(OPERATE_PAGES["overview"])


def _render_decision_panel(
    application_id: str,
    summary: dict[str, Any],
    store: SQLiteStore,
    verified_income: float,
    existing_emi: float,
    score: int | None,
) -> None:
    """Render a wide decision form driven by stable action codes and keyed state."""
    st.subheader("Your decision")
    st.caption("Fictional reviewer names only; this demo has no authentication.")
    action_key = f"review_action_{application_id}"
    reviewer_key = f"reviewer_{application_id}"
    reason_key = f"decision_reason_{application_id}"
    default_action = {
        "Approve": "approve",
        "Refer": "refer_up",
        "Decline": "reject",
    }.get(str(summary["recommendation"]), "refer_up")
    st.session_state.setdefault(action_key, default_action)
    amount = float(summary["application"]["requested_amount"])
    tenure = int(summary["application"]["tenure_months"])
    rate = pricing_rate(score)
    fields = st.columns(2)
    with fields[0]:
        action_code = st.selectbox(
            "Action",
            list(ACTIONS),
            format_func=ACTIONS.__getitem__,
            key=action_key,
        )
        action = ACTIONS[action_code]
        override = is_override_decision(summary["recommendation"], action_code)
        if override:
            st.warning(
                "This differs from the AI recommendation (CP-8.2): a written reason is required."
            )
        reviewer = st.selectbox("Reviewer", REVIEWERS, key=reviewer_key)
        if action_code == "modify_terms":
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
                preview = modified_terms_preview(amount, int(tenure), rate, existing_emi, verified_income)
                st.caption(
                    f"Recalculated EMI {fmt_inr(preview['emi'])}; "
                    f"FOIR on verified income {preview['foir_verified']:.1%}."
                    if preview["foir_verified"] is not None
                    else f"Recalculated EMI {fmt_inr(preview['emi'])}."
                )
                if preview["foir_over_limit"]:
                    st.warning("Modified terms remain above the 45% FOIR pass limit.")
    with fields[1]:
        st.text_area(
            "Written reason · at least 20 characters",
            key=reason_key,
            height=130,
        )
        reason_length = len(str(st.session_state.get(reason_key, "")).strip())
        st.caption(f"{reason_length} / 20 characters minimum")

    conditions = list(DEFAULT_CONDITIONS)
    if action_code == "approve_with_conditions":
        conditions = st.multiselect(
            "Conditions to complete before disbursement",
            DEFAULT_CONDITIONS,
            default=list(DEFAULT_CONDITIONS),
            key=f"conditions_{application_id}",
        )
    next_stage = _ACTION_STAGES[action_code]
    st.markdown(
        f"**You are about to {action.upper()} {summary['application']['name']}: "
        f"stage will become {next_stage}.**"
    )
    reason_ready = reason_length >= 20
    conditions_ready = action_code != "approve_with_conditions" or bool(conditions)
    rate_ready = action_code not in {"approve", "approve_with_conditions", "modify_terms"} or rate is not None
    disabled_reason = (
        "Enter a reason of at least 20 characters."
        if not reason_ready
        else "Select at least one condition."
        if not conditions_ready
        else "No policy-grid rate is available."
        if not rate_ready
        else ""
    )
    st.button(
        "Submit decision",
        key=f"submit_review_{application_id}",
        on_click=_submit_review_decision,
        args=(
            application_id,
            str(summary["recommendation"]),
            store,
            amount,
            int(tenure),
            verified_income,
            existing_emi,
            score,
        ),
        disabled=bool(disabled_reason),
        type="primary",
        width="stretch",
    )
    if disabled_reason:
        st.caption(disabled_reason)
    error_key = f"review_error_{application_id}"
    if st.session_state.get(error_key):
        st.error(st.session_state[error_key])


def _render_evidence_tabs(
    application_id: str,
    summary: dict[str, Any],
    store: SQLiteStore,
) -> None:
    """Render full-width supporting evidence below the decision workspace."""
    tabs = st.tabs(["Income and FOIR", "Documents", "Bureau and KYC", "Policy results"])
    finances = summary["finances"]
    with tabs[0]:
        st.subheader("Income and FOIR")
        stated = float(finances.get("stated_income") or 0)
        verified = float(finances.get("verified_income") or 0)
        existing_emi = float(finances.get("existing_emi") or 0)
        proposed_emi = float(finances.get("proposed_emi") or 0)
        stated_foir = calculate_foir(existing_emi, proposed_emi, stated)
        verified_foir = calculate_foir(existing_emi, proposed_emi, verified)
        st.table(
            [
                {"Measure": "Stated payslip income", "Value": fmt_inr(stated)},
                {"Measure": "Verified salary-credit average", "Value": fmt_inr(verified)},
                {"Measure": "Existing monthly EMIs", "Value": fmt_inr(existing_emi)},
                {"Measure": "Proposed EMI", "Value": fmt_inr(proposed_emi)},
                {"Measure": "FOIR on stated income", "Value": f"{stated_foir:.1%}" if stated_foir is not None else "Unavailable"},
                {"Measure": "FOIR on verified income", "Value": f"{verified_foir:.1%}" if verified_foir is not None else "Unavailable"},
            ]
        )
    with tabs[1]:
        st.subheader("Documents")
        extraction = summary["extraction"]
        fields = extraction.get("extracted_fields", {})
        evidence = extraction.get("evidence", {})
        rows = [
            {
                "Field": key.replace("_", " ").title(),
                "Extracted value": str(value),
                "Source": (evidence.get(key) or {}).get("source_document", "Unavailable"),
                "Evidence": (evidence.get(key) or {}).get("snippet", "No matching text"),
            }
            for key, value in fields.items()
        ]
        if rows:
            st.table(rows)
        else:
            st.info("No document fields were extracted.")
        st.write(extraction.get("anomaly_description") or "No anomaly description recorded.")
        documents = get_documents(application_id, store)
        if not documents.empty:
            st.caption("Registered synthetic documents")
            st.table(
                documents[["doc_type", "file_name", "uploaded_at"]].rename(
                    columns={"doc_type": "Type", "file_name": "File", "uploaded_at": "Uploaded"}
                )
            )
    with tabs[2]:
        st.subheader("Bureau and KYC")
        st.table(
            [
                {"Source": "Bureau", "Result": f"Score {summary['bureau'].get('score') if summary['bureau'].get('score') is not None else 'thin file'}; max DPD {summary['bureau'].get('max_dpd_24m', '—')}"},
                {"Source": "KYC", "Result": f"PAN {summary['kyc'].get('pan_status', 'unavailable')}; name match {summary['kyc'].get('name_match_score', 'unavailable')}"},
            ]
        )
    with tabs[3]:
        st.subheader("Policy results")
        st.markdown(
            f"{status_chip('Real · deterministic policy', 'success')}",
            unsafe_allow_html=True,
        )
        st.table(
            [
                {
                    "Clause": clause["clause_id"],
                    "Full rule": clause["rule_text"],
                    "Observed": json.dumps(clause["observed"], ensure_ascii=False),
                    "Result": clause["status"].title(),
                }
                for clause in summary["policy"].get("clauses", [])
            ]
        )


def render(store: SQLiteStore | None = None) -> None:
    """Render the reviewer queue, decision-first workspace, and evidence tabs."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    render_header(
        "Human Review",
        "Review the AI recommendation, record a reasoned human decision, and inspect evidence.",
        "OPERATE  /  CREDIT DESK",
    )
    queue = get_review_queue(store)
    if queue.empty and store.table_counts().get("cur_applications", 0) == 0:
        st.info("No demo applications are loaded yet. Prepare demo cases on Overview.")
        st.button(
            "Prepare demo on Overview",
            on_click=_open_overview,
            key="review_prepare_demo_empty",
        )
        return
    selected = _render_queue(queue, store)
    result_application_id = st.session_state.get("review_result_application_id")
    if result_application_id:
        st.subheader("Decision recorded")
        _render_result_card(result_application_id, store)
        return
    if not selected:
        return
    summary = _parse_assessment(selected, store)
    if summary is None:
        st.info("Run AI Assessment before human review. The agent cannot sanction a case.")
        return

    render_decision_card(selected, store, compact=True)
    render_why(selected, store)
    _render_decision_panel(
        selected,
        summary,
        store,
        float(summary["finances"].get("verified_income") or 0),
        float(summary["finances"].get("existing_emi") or 0),
        summary["bureau"].get("score"),
    )
    _render_evidence_tabs(selected, summary, store)
