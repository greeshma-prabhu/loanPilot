"""Human review queue and decision workspace."""

import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from loanpilot import config
from loanpilot.agent.policy_engine import pricing_rate
from loanpilot.agent.sanction import (
    DEFAULT_CONDITIONS,
    approve_and_sanction,
    modified_terms_preview,
    run_simulated_disbursement,
    update_conditions,
)
from loanpilot.components import (
    calculate_foir,
    fmt_inr,
    render_decision_card,
    render_key_numbers,
    render_why,
    status_chip,
)
from loanpilot.data.queries import (
    get_agent_trace,
    get_application,
    get_documents,
    get_disbursement,
    get_human_review_cases,
    get_sanction,
    human_decision_is_override,
    record_human_decision,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import render_disclaimer

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
    """Return whether the review action differs from the AI recommendation."""
    return human_decision_is_override(ai_decision, ACTIONS.get(action_code, ""))


def _age_days(submitted_at: str) -> int:
    """Return whole elapsed days from the ISO timestamp."""
    try:
        submitted = datetime.fromisoformat(submitted_at)
    except ValueError:
        return 0
    if submitted.tzinfo:
        submitted = submitted.replace(tzinfo=None)
    return max(0, (datetime.now() - submitted).days)


def _open_ai_assessment() -> None:
    """Open assessment to select and assess a case."""
    from loanpilot.navigation import OPERATE_PAGES

    st.switch_page(OPERATE_PAGES["ai_assessment"])


def _open_review_case(application_id: str) -> None:
    """Open the one expanded case panel, replacing any previous selection."""
    st.session_state["review_open"] = application_id


def _close_review_case(application_id: str) -> None:
    """Close the selected review panel without changing the saved decision."""
    if st.session_state.get("review_open") == application_id:
        st.session_state["review_open"] = None


def _set_review_filter(value: str) -> None:
    """Change the queue filter and close any currently open case."""
    st.session_state["review_filter"] = value
    st.session_state["review_open"] = None


def _queue_chip(label: str, kind: str) -> None:
    """Render a compact, text-labelled chip for a queue cell."""
    palette = {
        "neutral": ("#f0eef0", "#62555c"),
        "success": ("#e5f4e9", "#1f6b3b"),
        "warning": ("#fff2d6", "#805400"),
        "danger": ("#fde8e7", "#9d2f2a"),
        "info": ("#e6f0ff", "#31598a"),
    }
    background, foreground = palette.get(kind, palette["neutral"])
    st.markdown(
        f'<span style="display:inline-block;border-radius:999px;padding:.2rem .55rem;'
        f'background:{background};color:{foreground};border:1px solid {foreground}33;'
        f'font-size:.82rem;font-weight:650;white-space:nowrap">{escape(label)}</span>',
        unsafe_allow_html=True,
    )


def _case_status(stage: str) -> tuple[str, str]:
    """Map persisted stages to short queue labels and accessible chip kinds."""
    return {
        "Human Review": ("Pending", "warning"),
        "Sanction": ("Approved", "success"),
        "Disbursed (simulated)": ("Disbursed (simulated)", "success"),
        "Rejected": ("Rejected", "danger"),
        "Escalated": ("Referred up", "info"),
        "Awaiting documents": ("Documents requested", "info"),
    }.get(stage, (stage, "neutral"))


def _render_queue_filters(store: SQLiteStore) -> tuple[pd.DataFrame, str]:
    """Render filter buttons with case counts and a lightweight search field."""
    active_filter = st.session_state.get("review_filter", "Pending")
    all_cases = get_human_review_cases("All", "", store)
    if all_cases.empty:
        counts = {"Pending": 0, "Approved": 0, "Rejected": 0, "All": 0}
    else:
        stages = all_cases["stage"].astype(str)
        counts = {
            "Pending": int((stages == "Human Review").sum()),
            "Approved": int(stages.isin(("Sanction", "Disbursed (simulated)")).sum()),
            "Rejected": int((stages == "Rejected").sum()),
            "All": len(all_cases),
        }
    columns = st.columns(4)
    for column, label in zip(columns, ("Pending", "Approved", "Rejected", "All"), strict=True):
        column.button(
            f"{label} · {counts[label]}",
            key=f"review_filter_{label.casefold()}",
            type="primary" if active_filter == label else "secondary",
            on_click=_set_review_filter,
            args=(label,),
            width="stretch",
        )
    search = st.text_input(
        "Search by applicant or case ID",
        placeholder="Name or case ID",
        key="review_search",
    )
    cases = get_human_review_cases(active_filter, search, store)
    return cases, active_filter


def _render_queue_row(row: pd.Series) -> None:
    """Render a compact review row with only the fields the queue is meant to show."""
    stage = str(row["stage"])
    status, status_kind = _case_status(stage)
    recommendation = str(row["ai_recommendation"] or "—")
    risk = str(row["risk_band"] or "—")
    decision_state = stage != "Human Review"
    columns = st.columns([2.2, 1.2, 1.0, 0.9, 1.3, 0.8], vertical_alignment="center")
    with columns[0]:
        st.markdown(
            f'<strong>{escape(str(row["applicant"]))}</strong>',
            unsafe_allow_html=True,
        )
    with columns[1]:
        _queue_chip(recommendation, {
            "Approve": "success", "Refer": "warning", "Decline": "danger"
        }.get(recommendation, "neutral"))
    with columns[2]:
        _queue_chip(risk, {
            "Low": "success", "Medium": "warning", "High": "danger"
        }.get(risk, "neutral"))
    with columns[3]:
        st.markdown(f"{_age_days(str(row['submitted_at']))}d")
    with columns[4]:
        _queue_chip(status, status_kind)
    with columns[5]:
        st.button(
            "View" if decision_state else "Review",
            key=f"review_open_{row['application_id']}",
            on_click=_open_review_case,
            args=(str(row["application_id"]),),
            width="stretch",
        )
    st.markdown(
        '<div style="height:1px;background:#eee7eb;margin:.45rem 0"></div>',
        unsafe_allow_html=True,
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
    """Read keyed widgets in the callback, persist the choice, then close the panel."""
    error_key = f"review_error_{application_id}"
    action_code = str(st.session_state.get(f"review_action_{application_id}", ""))
    action = ACTIONS.get(action_code)
    if action is None:
        st.session_state[error_key] = "Select a valid review action."
        return
    reviewer = str(st.session_state.get("auth", {}).get("name", ""))
    if not reviewer:
        raise RuntimeError("An authenticated reviewer is required to save decisions.")
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

    saved = get_application(application_id, store)
    if saved.empty:
        raise RuntimeError(f"Could not reload the saved case {application_id}.")
    st.session_state["review_open"] = None
    st.session_state.pop(error_key, None)


def _render_decision_panel(
    application_id: str,
    summary: dict[str, Any],
    store: SQLiteStore,
    verified_income: float,
    existing_emi: float,
    score: int | None,
) -> None:
    """Render the pending-case form using case-specific stable widget keys."""
    st.subheader("Your decision")
    st.caption(
        "Demo-grade sign-in: sessions persist for up to 7 days or until sign out; "
        "there is no MFA or single sign-on."
    )
    action_key = f"review_action_{application_id}"
    reason_key = f"decision_reason_{application_id}"
    reviewer = str(st.session_state.get("auth", {}).get("name", ""))
    default_action = {
        "Approve": "approve",
        "Refer": "refer_up",
        "Decline": "reject",
    }.get(str(summary["recommendation"]), "refer_up")
    if action_key not in st.session_state:
        st.session_state[action_key] = default_action
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
        st.text_input(
            "Reviewer",
            value=reviewer,
            key=f"reviewer_display_{application_id}",
            disabled=True,
        )
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
        with st.container(key=f"hr-reason-{application_id}", border=True):
            st.markdown("**Required · written reason**")
            st.text_area(
                "Explain your decision (minimum 20 characters)",
                key=reason_key,
                height=130,
            )
            reason_length = len(str(st.session_state.get(reason_key, "")).strip())
            st.caption(f"{reason_length} / 20 characters")

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
    if not conditions_ready:
        st.warning("Select at least one condition before submitting.")
    st.button(
        "Submit decision",
        key=f"submit_review_{application_id}",
        on_click=_submit_review_decision,
        args=(
            application_id,
            str(summary["recommendation"]),
            store,
            float(summary["application"]["requested_amount"]),
            int(summary["application"]["tenure_months"]),
            verified_income,
            existing_emi,
            score,
        ),
        disabled=not (reason_ready and conditions_ready and rate_ready),
        type="primary",
        width="stretch",
    )
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


def _submit_disbursement(application_id: str, store: SQLiteStore) -> None:
    """Persist checked conditions and execute the explicitly simulated transfer."""
    sanctions = get_sanction(application_id, store)
    if sanctions.empty:
        raise RuntimeError(f"No sanction exists for {application_id}.")
    sanction = sanctions.iloc[0]
    conditions = json.loads(sanction["conditions_json"] or "[]")
    for index, condition in enumerate(conditions):
        condition["complete"] = bool(
            st.session_state.get(f"hr_condition_{application_id}_{index}", False)
        )
    reviewer = str(st.session_state.get("auth", {}).get("name", ""))
    if not reviewer:
        raise RuntimeError("An authenticated reviewer is required to update conditions.")
    try:
        update_conditions(application_id, conditions, reviewer, store)
        run_simulated_disbursement(application_id, store)
    except ValueError as error:
        st.session_state[f"hr_disbursement_error_{application_id}"] = str(error)
        return
    saved = get_application(application_id, store)
    if saved.empty:
        raise RuntimeError(f"Could not reload the disbursed case {application_id}.")
    st.session_state["review_open"] = None


def _render_readonly_panel(application_id: str, row: pd.Series, store: SQLiteStore) -> None:
    """Show the saved human outcome and approved-case artifacts without an edit form."""
    st.subheader(f"Saved decision · {row['human_decision'] or _case_status(str(row['stage']))[0]}")
    st.write(f"**Reviewer:** {row['decided_by'] or 'Unavailable'}")
    st.write(f"**Reason:** {row['human_reason'] or 'No written reason recorded.'}")
    st.write(f"**Override:** {'Yes' if bool(row['is_override']) else 'No'}")
    st.write(f"**Time:** {row['decided_at'] or 'Unavailable'}")
    if row["stage"] not in {"Sanction", "Disbursed (simulated)"}:
        return
    sanctions = get_sanction(application_id, store)
    if sanctions.empty:
        st.info("The sanction record is not available.")
        return
    sanction = sanctions.iloc[0]
    letter_path = Path(str(sanction["letter_path"]))
    if not letter_path.is_absolute():
        letter_path = config.PROJECT_ROOT / letter_path
    letter_path = letter_path.resolve()
    try:
        letter_path.relative_to(config.PROJECT_ROOT.resolve())
    except ValueError as error:
        raise ValueError("Sanction letter path is outside the project directory.") from error
    if letter_path.is_file():
        st.download_button(
            "Download sanction letter",
            data=letter_path.read_bytes(),
            file_name=letter_path.name,
            mime="application/pdf",
            key=f"hr_sanction_download_{application_id}",
        )
    else:
        st.info("The sanction letter file is unavailable.")
    kfs = json.loads(sanction["kfs_json"] or "{}")
    st.markdown("**Key Fact Statement preview**")
    st.table(
        [
            {"Item": "Approved amount", "Value": fmt_inr(sanction["approved_amount"])},
            {"Item": "Annual rate", "Value": f"{float(sanction['rate']):.2%}"},
            {"Item": "Monthly EMI", "Value": fmt_inr(sanction["emi"])},
            {"Item": "Tenure", "Value": f"{int(sanction['tenure_months'])} months"},
            {"Item": "Processing fee", "Value": fmt_inr(kfs.get("processing_fee", 0))},
            {"Item": "Net disbursed", "Value": fmt_inr(kfs.get("net_disbursed", 0))},
        ]
    )
    if row["stage"] == "Disbursed (simulated)":
        disbursement = get_disbursement(application_id, store)
        if not disbursement.empty:
            st.success(
                f"Simulated disbursement {disbursement.iloc[0]['disbursement_ref']} "
                f"· {fmt_inr(disbursement.iloc[0]['net_amount'])} net."
            )
        return
    conditions = json.loads(sanction["conditions_json"] or "[]")
    st.markdown("**Conditions before simulated disbursement**")
    for index, condition in enumerate(conditions):
        key = f"hr_condition_{application_id}_{index}"
        if key not in st.session_state:
            st.session_state[key] = bool(condition.get("complete", False))
        st.checkbox(str(condition["name"]), key=key)
    can_disburse = all(
        bool(st.session_state.get(f"hr_condition_{application_id}_{index}", False))
        for index in range(len(conditions))
    )
    button_columns = st.columns([1, 2])
    with button_columns[0]:
        st.button(
            "Run simulated disbursement",
            key=f"hr_disburse_{application_id}",
            type="primary",
            disabled=not can_disburse,
            on_click=_submit_disbursement,
            args=(application_id, store),
            width="stretch",
        )
    if not can_disburse:
        button_columns[1].caption("Complete every listed condition first.")
    if st.session_state.get(f"hr_disbursement_error_{application_id}"):
        st.error(st.session_state.pop(f"hr_disbursement_error_{application_id}"))


def _render_case_panel(
    application_id: str,
    row: pd.Series,
    store: SQLiteStore,
) -> None:
    """Render the one expanded inline detail panel for a queue row."""
    panel_columns = st.columns([5, 1])
    with panel_columns[0]:
        st.markdown(f"### {row['applicant']}")
    with panel_columns[1]:
        st.button(
            "✕",
            key=f"close_review_details_{application_id}",
            help="Close this panel without saving a decision.",
            on_click=_close_review_case,
            args=(application_id,),
            width="stretch",
        )
    with st.container(border=True):
        summary = _parse_assessment(application_id, store)
        if row["stage"] == "Human Review":
            if summary is None:
                st.info("Run AI Assessment before human review.")
            else:
                render_decision_card(application_id, store, compact=True)
                render_why(application_id, store)
                render_key_numbers(application_id, store)
                with st.expander("Full evidence"):
                    _render_evidence_tabs(application_id, summary, store)
                _render_decision_panel(
                    application_id,
                    summary,
                    store,
                    float(summary["finances"].get("verified_income") or 0),
                    float(summary["finances"].get("existing_emi") or 0),
                    summary["bureau"].get("score"),
                )
        else:
            _render_readonly_panel(application_id, row, store)


def render(store: SQLiteStore | None = None) -> None:
    """Render the review queue with summary metrics, inline case panels, and action form."""
    if not st.session_state.get("auth"):
        st.info("Sign in to access Human Review.")
        return
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    st.title("Review queue")
    cases, active_filter = _render_queue_filters(store)
    if cases.empty:
        if active_filter == "Pending":
            st.info("Nothing waiting for review. Run an assessment first.")
            st.button(
                "Open AI Assessment",
                key="review_open_assessment",
                on_click=_open_ai_assessment,
            )
        else:
            st.info("No cases match this filter and search.")
        return

    labels = ("APPLICANT", "AI DECISION", "RISK", "WAITING", "STATUS", "")
    selected = st.session_state.get("review_open")
    visible_ids = set(cases["application_id"].astype(str))
    if selected not in visible_ids:
        selected = None
    displayed_cases = (
        cases.loc[cases["application_id"].astype(str) == selected]
        if selected is not None
        else cases
    )
    with st.container(border=True):
        heading_columns = st.columns([2.4, 1, .85, .75, 1.4, .75])
        for column, label in zip(heading_columns, labels, strict=True):
            with column:
                st.markdown(
                    f'<div style="font-size:.68rem;letter-spacing:.08em;font-weight:750;'
                    f'color:#817780">{label}</div>',
                    unsafe_allow_html=True,
                )
        for _, row in displayed_cases.iterrows():
            application_id = str(row["application_id"])
            row_key = (
                f"hr-decided-{application_id}"
                if row["stage"] != "Human Review"
                else f"hr-pending-{application_id}"
            )
            with st.container(key=row_key, gap="small"):
                _render_queue_row(row)
                if selected == application_id:
                    _render_case_panel(application_id, row, store)
