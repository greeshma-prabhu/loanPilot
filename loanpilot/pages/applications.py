"""Applications list and synthetic case view."""

from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd
import streamlit as st

from loanpilot import config
from loanpilot.badges import implementation_badge
from loanpilot.components import (
    calculate_foir,
    case_header_card,
    fmt_inr,
    kpi_card,
    render_decision_card,
    render_human_review_button,
    render_why,
    stage_tracker,
    status_chip,
)
from loanpilot.data.queries import (
    get_application,
    get_agent_trace,
    get_audit_log,
    get_bureau,
    get_customer,
    get_disbursement,
    get_documents,
    get_existing_loans,
    get_kyc,
    get_repayment_summary,
    get_sanction,
    get_transactions,
    list_applications,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.theme import format_datetime, render_disclaimer, render_header

_PERSONA_STORIES = {
    "PERSONA-1": "Clean approve: consistent income and documents, strong bureau profile.",
    "PERSONA-2": "Borderline FOIR: within the refer band with one older 30-day late payment.",
    "PERSONA-3": "FOIR breach: obligations exceed the illustrative policy threshold.",
    "PERSONA-4": "Document mismatch: payslip arithmetic, employer, and salary credits differ.",
    "PERSONA-5": "Thin file: no bureau score; illustrative cap and referral apply.",
    "PERSONA-6": "Override candidate: short current tenure despite a long prior work history.",
}

_PERSONA_SHORT_NAMES = {
    "PERSONA-1": "Priya Menon",
    "PERSONA-2": "Rahul Verma",
    "PERSONA-3": "Imran Sheikh",
    "PERSONA-4": "Anita Rao",
    "PERSONA-5": "Karthik Nair",
    "PERSONA-6": "Meera Iyer",
}
_CLOSED_STAGES = {"Rejected", "Disbursed (simulated)", "Awaiting documents"}


def _select_application(application_id: str) -> None:
    """Store the selected application before rerendering the list page."""
    st.session_state["selected_application"] = application_id


def _clear_application() -> None:
    """Clear the selected case and switch back to the applications list."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state.pop("selected_application", None)
    st.switch_page(OPERATE_PAGES["applications"])


def _open_ai_assessment(application_id: str) -> None:
    """Persist the current case and switch to the assessment placeholder."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state["selected_application"] = application_id
    st.switch_page(OPERATE_PAGES["ai_assessment"])


def _open_human_review(application_id: str) -> None:
    """Open Human Review with this case selected."""
    from loanpilot.navigation import OPERATE_PAGES

    st.session_state["selected_application"] = application_id
    st.session_state["review_open"] = application_id
    st.switch_page(OPERATE_PAGES["human_review"])


def _load_data(store: SQLiteStore) -> None:
    """Load synthetic data into the selected empty demo store."""
    counts = seed_demo_data(store, reset=True)
    count_text = ", ".join(f"{name}: {count}" for name, count in counts.items())
    st.toast(f"Demo data loaded. {count_text}")


def _age_in_days(submitted_at: str) -> int:
    """Return elapsed whole days from an ISO application timestamp."""
    try:
        submitted = datetime.fromisoformat(submitted_at)
    except ValueError:
        return 0
    if submitted.tzinfo is not None:
        submitted = submitted.replace(tzinfo=None)
    return max(0, (datetime.now() - submitted).days)


def _list_frame(applications: pd.DataFrame) -> pd.DataFrame:
    """Create the requested display columns from application query results."""
    if applications.empty:
        return pd.DataFrame(
            columns=[
                "Applicant",
                "Amount",
                "Stage",
                "AI recommendation",
                "Human decision",
                "Risk band",
                "Age (days)",
            ]
        )
    return pd.DataFrame(
        {
            "Applicant": applications["applicant"],
            "Amount": applications["requested_amount"].map(fmt_inr),
            "Stage": applications["stage"].fillna("—"),
            "AI recommendation": applications["ai_recommendation"].fillna("—"),
            "Human decision": applications["human_decision"].fillna("—"),
            "Risk band": applications["risk_band"].fillna("—"),
            "Age (days)": applications["submitted_at"].map(_age_in_days),
        }
    )


def _render_application_table(frame: pd.DataFrame) -> None:
    """Render a compact, accessible table with consistent text status chips."""
    status_columns = {"Stage", "AI recommendation", "Human decision", "Risk band"}
    rows = []
    for _, row in frame.iterrows():
        cells = []
        for column in frame.columns:
            value = str(row[column])
            if column in status_columns:
                kind = (
                    "success" if value in {"Approve", "Approve with conditions", "Low"}
                    else "warning" if value in {"Refer", "Refer up", "Request documents", "Medium"}
                    else "danger" if value in {"Decline", "Reject", "High"}
                    else "info" if column == "Stage" and value != "—"
                    else "neutral"
                )
                cells.append(f"<td>{status_chip(value, kind)}</td>")
            else:
                cells.append(f"<td>{escape(value)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    headers = "".join(f"<th scope='col'>{escape(str(column))}</th>" for column in frame.columns)
    st.markdown(
        '<div class="lp-table-wrap"><table class="lp-data-table">'
        f"<thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def _render_empty_state(store: SQLiteStore) -> None:
    """Show an actionable empty database state."""
    render_header("Applications", "Explore the synthetic personal-loan portfolio.")
    st.info("No demo applications are loaded yet. Load the synthetic sample dataset to begin.")
    st.button("Load demo data", on_click=_load_data, args=(store,), key="load_applications_data")


def _render_demo_cards(rows: pd.DataFrame) -> None:
    """Keep persona cases above the rest of the filtered application list."""
    if rows.empty:
        return
    st.subheader("Demo cases")
    for start in range(0, len(rows), 3):
        row_group = rows.iloc[start : start + 3]
        columns = st.columns(3)
        for column, (_, row) in zip(columns, row_group.iterrows()):
            persona_key = row["persona_key"]
            story = _PERSONA_STORIES[persona_key]
            with column:
                st.markdown(f"**{escape(str(row['applicant']))}**")
                st.markdown(
                    f'<div class="lp-demo-story" title="{escape(story)}">'
                    f"{escape(story)}</div>",
                    unsafe_allow_html=True,
                )
                st.button(
                    "Open",
                    key=f"open_{row['application_id']}",
                    on_click=_select_application,
                    args=(row["application_id"],),
                    width="stretch",
                )


def _previous_applications_page() -> None:
    """Move the application list to its preceding page."""
    st.session_state["applications_page"] = max(
        0, int(st.session_state.get("applications_page", 0)) - 1
    )


def _next_applications_page(page_count: int) -> None:
    """Move the application list to its following page."""
    st.session_state["applications_page"] = min(
        page_count - 1, int(st.session_state.get("applications_page", 0)) + 1
    )


def _render_applications_list(store: SQLiteStore) -> None:
    """Render filters, counts, pinned personas, and the historical table."""
    render_header(
        "Applications",
        "Browse the synthetic personal-loan queue, spot priority cases, and open a case workspace.",
        "OPERATE  /  PORTFOLIO",
    )
    all_rows = list_applications(store=store)
    if all_rows.empty:
        _render_empty_state(store)
        return

    stage_options = ["All", *sorted(all_rows["stage"].dropna().unique().tolist())]
    recommendation_options = [
        "All",
        *sorted(
            value
            for value in all_rows["ai_recommendation"].dropna().unique().tolist()
        ),
    ]
    filter_columns = st.columns([1.2, 1.2, 1.4, 1, 2])
    with filter_columns[0]:
        stage = st.selectbox("Stage", stage_options, key="applications_stage")
    with filter_columns[1]:
        recommendation = st.selectbox(
            "AI recommendation",
            recommendation_options,
            key="applications_recommendation",
        )
    with filter_columns[2]:
        worklist = st.segmented_control(
            "Cases",
            ("Active", "Closed", "All"),
            default="Active",
            key="applications_worklist",
        )
    with filter_columns[3]:
        demo_only = st.toggle("Demo cases only", key="applications_demo_only")
    with filter_columns[4]:
        search = st.text_input("Search applicant or case reference", key="applications_search")

    active_count = int((~all_rows["stage"].isin(_CLOSED_STAGES)).sum())
    closed_count = int(all_rows["stage"].isin(_CLOSED_STAGES).sum())
    st.caption(
        f"Active {active_count:,} · Closed {closed_count:,} · All {len(all_rows):,}"
    )
    filters = {
        "stage": stage,
        "recommendation": recommendation,
        "worklist": worklist or "Active",
        "demo_only": demo_only,
        "search": search.strip(),
    }
    filtered = list_applications(filters, store)
    pinned_mask = filtered["persona_key"].notna() & ~filtered["stage"].isin(_CLOSED_STAGES)
    demo_rows = filtered.loc[pinned_mask]
    open_options = filtered.loc[~pinned_mask]
    historical_rows = filtered.loc[
        filtered["persona_key"].isna()
        & ~filtered["application_id"].astype(str).str.startswith("APP-CUSTOM-")
    ]

    metric_columns = st.columns(3)
    metric_columns[0].metric("Matching applications", len(filtered))
    metric_columns[1].metric("Open demo cases", len(demo_rows))
    metric_columns[2].metric("Historical applications", len(historical_rows))
    _render_demo_cards(demo_rows)

    st.subheader("Application list")
    page_size = 25
    page_count = max(1, (len(filtered) + page_size - 1) // page_size)
    page_index = min(int(st.session_state.get("applications_page", 0)), page_count - 1)
    st.session_state["applications_page"] = page_index
    if page_count > 1:
        page_controls = st.columns([1, 3, 1])
        with page_controls[0]:
            st.button(
                "Previous",
                key="applications_previous_page",
                on_click=_previous_applications_page,
                disabled=page_index == 0,
            )
        with page_controls[1]:
            st.caption(f"Page {page_index + 1} of {page_count} · {len(filtered):,} applications")
        with page_controls[2]:
            st.button(
                "Next",
                key="applications_next_page",
                on_click=_next_applications_page,
                args=(page_count,),
                disabled=page_index + 1 >= page_count,
            )
    page_rows = filtered.iloc[page_index * page_size : (page_index + 1) * page_size]
    _render_application_table(_list_frame(page_rows))

    if not open_options.empty:
        selectable_ids = open_options["application_id"].tolist()
        selected_historical = st.selectbox(
            "Open a case from the list",
            selectable_ids,
            format_func=lambda application_id: str(
                open_options.loc[
                    open_options.application_id == application_id, "applicant"
                ].iloc[0]
            ),
            key="list_case_select",
        )
        with st.expander("Selected case reference"):
            st.code(str(selected_historical))
        st.button(
            "Open selected application",
            key="open_historical_case",
            on_click=_select_application,
            args=(selected_historical,),
        )


def _single_bureau(application_id: str, store: SQLiteStore) -> dict[str, Any]:
    """Return the decoded bureau payload or an empty mapping."""
    response = get_bureau(application_id, store)
    return {} if response.empty else response.iloc[0]["payload"]


def _single_kyc(application_id: str, store: SQLiteStore) -> dict[str, Any]:
    """Return the decoded KYC payload or an empty mapping."""
    response = get_kyc(application_id, store)
    return {} if response.empty else response.iloc[0]["payload"]


def _rate_for_score(score: Any) -> float | None:
    """Return the illustrative annual grid rate for a known score band."""
    if pd.isna(score):
        return None
    if score >= 750:
        return 0.115
    if score >= 700:
        return 0.135
    if score >= 650:
        return 0.16
    return None


def _indicative_emi(principal: float, rate: float, months: int) -> float:
    """Calculate an indicative EMI using annual reducing-balance pricing."""
    monthly_rate = rate / 12
    factor = (1 + monthly_rate) ** months
    return principal * monthly_rate * factor / (factor - 1)


def _payslip_net(documents: pd.DataFrame, fallback: float) -> float:
    """Read the payslip net from the registered extracted text."""
    payslip_rows = documents.loc[documents["doc_type"] == "payslip"]
    if payslip_rows.empty:
        return fallback
    match = re.search(
        r"Net pay:\s*Rs\s*([\d,]+(?:\.\d{2})?)",
        payslip_rows.iloc[0]["text_content"],
    )
    return float(match.group(1).replace(",", "")) if match else fallback


def _render_summary(application: pd.Series, documents: pd.DataFrame) -> None:
    """Render applicant profile, request, indicative EMI, and persona story."""
    st.subheader("Applicant profile")
    columns = st.columns(4)
    fields = [
        ("Age", f"{application['age']} years"),
        ("City", application["city"]),
        ("Employment", application["employment_type"]),
        ("Employer", application["employer"]),
        ("Current tenure", f"{application['current_tenure_months']} months"),
        ("Total experience", f"{application['total_experience_months']} months"),
        ("KYC status", application["kyc_status"]),
        ("Relationship since", application["relationship_since"]),
    ]
    for index, (label, value) in enumerate(fields):
        with columns[index % len(columns)]:
            st.markdown(f"**{label}**")
            st.write(value)

    st.subheader("Loan request")
    rate = _rate_for_score(application["bureau_score"])
    request_columns = st.columns(4)
    request_columns[0].metric("Requested amount", fmt_inr(application["requested_amount"]))
    request_columns[1].metric("Tenure", f"{application['tenure_months']} months")
    request_columns[2].metric("Purpose", application["purpose"])
    if rate is None:
        request_columns[3].metric("Indicative EMI", "No grid rate: thin file")
    else:
        request_columns[3].metric(
            "Indicative EMI",
            fmt_inr(
                _indicative_emi(
                    application["requested_amount"],
                    rate,
                    application["tenure_months"],
                )
            ),
        )
        st.caption(f"Illustrative pricing: {rate:.1%} annual reducing-balance rate.")

    persona_key = application["persona_key"]
    if persona_key:
        st.info(f"**Demo case · {_PERSONA_SHORT_NAMES[persona_key]}**  \n{_PERSONA_STORIES[persona_key]}")


def _render_documents(
    application_id: str,
    documents: pd.DataFrame,
) -> None:
    """Render registered synthetic documents and downloadable PDFs."""
    st.subheader("Application documents")
    if documents.empty:
        st.info("No documents have been registered for this application.")
        return
    st.caption("Every sample PDF is synthetic and carries a diagonal demo-only watermark.")
    for _, document in documents.iterrows():
        with st.container(border=True):
            st.markdown(
                f"**{document['doc_type'].replace('_', ' ').title()}** · "
                f"uploaded {format_datetime(document['uploaded_at'])}"
            )
            with st.expander("View extracted text"):
                st.text(document["text_content"])
            path = (config.PROJECT_ROOT / Path(document["file_path"])).resolve()
            if path.is_relative_to(config.PROJECT_ROOT.resolve()) and path.is_file():
                st.download_button(
                    f"Download {document['file_name']}",
                    data=path.read_bytes(),
                    file_name=document["file_name"],
                    mime="application/pdf",
                    key=f"download_{document['doc_id']}",
                    width="stretch",
                )
            else:
                st.warning(f"Document file is unavailable: {document['file_name']}")


def _render_financials(
    application: pd.Series,
    customer: pd.Series,
    documents: pd.DataFrame,
    transactions: pd.DataFrame,
    loans: pd.DataFrame,
) -> None:
    """Render source income and calculated FOIRs with formulas."""
    payslip_net = _payslip_net(documents, float(application["income"]))
    salary_avg = (
        float(transactions["salary_credit"].mean())
        if not transactions.empty
        else 0.0
    )
    salary_variance_pct = (
        (salary_avg - payslip_net) / payslip_net * 100 if payslip_net else 0.0
    )
    existing_emi = float(loans.loc[loans["status"] == "Active", "emi"].sum())
    proposed_emi = float(application["proposed_emi"] or 0)
    stated_foir = calculate_foir(existing_emi, proposed_emi, payslip_net)
    verified_foir = calculate_foir(existing_emi, proposed_emi, salary_avg)
    average_balance = float(customer["average_balance"])
    cheque_bounces = int(transactions["cheque_bounces"].sum()) if not transactions.empty else 0
    real_badge = implementation_badge("real")

    st.caption(f"{real_badge} Computed from the synthetic records available in this demo.", unsafe_allow_html=True)
    columns = st.columns(4)
    metrics = [
        ("Payslip net income", fmt_inr(payslip_net), "Net income stated on the payslip."),
        ("Average salary credit · 6 months", fmt_inr(salary_avg), "Mean of the six monthly salary-credit aggregates."),
        ("Salary-credit difference", f"{salary_variance_pct:+.1f}%", "(average salary credit − payslip net) / payslip net × 100."),
        ("Existing active EMIs", fmt_inr(existing_emi), "Sum of EMI for active existing loans."),
        ("Proposed EMI", fmt_inr(proposed_emi), "Reducing-balance EMI at the indicative bureau-grid rate."),
        ("FOIR · stated income", f"{stated_foir:.1%}" if stated_foir is not None else "Unavailable", "(existing EMIs + proposed EMI) / payslip net income."),
        ("FOIR · verified income", f"{verified_foir:.1%}" if verified_foir is not None else "Unavailable", "(existing EMIs + proposed EMI) / average salary credit."),
        ("Average account balance", fmt_inr(average_balance), "Average monthly balance from the synthetic core banking record."),
        ("Cheque bounces · 6 months", str(cheque_bounces), "Sum of monthly cheque-bounce aggregates across the six-month window."),
    ]
    for index, (label, value, formula) in enumerate(metrics):
        with columns[index % len(columns)]:
            kpi_card(label, value, help_text=formula)


def _render_checks(
    application_id: str,
    loans: pd.DataFrame,
    repayment_summary: pd.Series,
    store: SQLiteStore,
) -> None:
    """Render source panels for core banking, bureau, KYC, and CERSAI."""
    simulated_badge = implementation_badge("simulated")
    st.markdown(
        f"### Source checks {simulated_badge}",
        unsafe_allow_html=True,
    )
    bureau = _single_bureau(application_id, store)
    kyc = _single_kyc(application_id, store)

    with st.container(border=True):
        st.markdown("#### Core banking record")
        st.write(f"Existing loans: {len(loans)}")
        if loans.empty:
            st.caption("No existing loans recorded.")
        else:
            st.dataframe(
                loans[["product", "emi", "outstanding", "status"]],
                width="stretch",
                hide_index=True,
            )
        st.write(
            f"Repayment months tracked: {int(repayment_summary['months_tracked'])} · "
            f"Maximum days past due: {int(repayment_summary['max_days_past_due'])}"
        )

    with st.container(border=True):
        st.markdown("#### Credit bureau response")
        st.write(f"Score: {bureau.get('score') if bureau.get('score') is not None else 'No history (thin file)'}")
        st.write(
            f"Active accounts: {bureau.get('active_accounts', '—')} · "
            f"Enquiries (6 months): {bureau.get('enquiries_6m', '—')} · "
            f"Max DPD (24 months): {bureau.get('max_dpd_24m', '—')}"
        )
        st.write(f"Written off: {'Yes' if bureau.get('written_off') else 'No'}")

    with st.container(border=True):
        st.markdown("#### KYC response")
        st.write(f"PAN status: {kyc.get('pan_status', 'Unavailable')}")
        st.write(f"Name-match score: {kyc.get('name_match_score', 'Unavailable')}")

    with st.container(border=True):
        st.markdown("#### CERSAI")
        st.write("Not applicable (unsecured personal loan)")


def _render_audit(application_id: str, store: SQLiteStore) -> None:
    """Render newest audit events for this application."""
    audit = get_audit_log(application_id, store)
    if audit.empty:
        st.info("No audit events are recorded for this application.")
    else:
        display = audit.rename(
            columns={
                "time": "Date and time",
                "actor": "Who",
                "action": "Action",
                "detail": "What happened",
            }
        ).copy()
        display["Date and time"] = display["Date and time"].map(format_datetime)
        st.dataframe(display, width="stretch", hide_index=True)


def _render_agent_trace(application_id: str, store: SQLiteStore) -> None:
    """Render the shared decision view and collapsible agent trace."""
    render_decision_card(application_id, store)
    render_why(application_id, store)
    trace = get_agent_trace(application_id, store=store)
    if trace.empty:
        st.info("No agent trace has been saved for this case.")
        return
    st.subheader("Agent steps")
    for _, step in trace.iterrows():
        with st.expander(
            f"{int(step['step_no'])}. {step['agent']} · "
            f"{int(step['duration_ms'])} ms · {step['mode']}"
        ):
            payload = json.loads(step["tool_calls_json"])
            for call in payload.get("calls", []):
                st.markdown(f"**{call['name']}**")
                with st.expander("Show raw inputs"):
                    st.json(call.get("inputs", {}))
                with st.expander("Show raw outputs"):
                    st.json(call.get("outputs", {}))
            st.markdown(f"**Handoff:** {step['handoff']}")


def _render_decision(application_id: str, application: pd.Series, store: SQLiteStore) -> None:
    """Show the shared AI summary beside the saved human outcome."""
    render_decision_card(application_id, store)
    if application.get("ai_recommendation"):
        render_human_review_button(application_id)
    render_why(application_id, store)
    st.subheader("Human decision")
    human_decision = application.get("human_decision")
    if application.get("stage") == "Rejected":
        st.markdown(
            status_chip("Rejected", "danger"),
            unsafe_allow_html=True,
        )
    st.write(f"Decision: **{human_decision or 'Pending'}**")
    st.write(f"Reviewer: {application.get('decided_by') or '—'}")
    st.write(f"Decided at: {format_datetime(application.get('decided_at'))}")
    st.write(f"Override: **{'Yes' if application.get('is_override') else 'No'}**")
    if human_decision:
        st.write(f"Reason: {application.get('human_reason') or '—'}")


def _disbursement_callback(
    application_id: str,
    conditions: list[dict[str, Any]],
    store: SQLiteStore,
) -> None:
    """Persist the checklist and create a simulated disbursement."""
    from loanpilot.agent.sanction import run_simulated_disbursement, update_conditions

    updated = [
        {
            **item,
            "complete": bool(
                st.session_state.get(
                    f"sanction_condition_{application_id}_{index}", False
                )
            ),
        }
        for index, item in enumerate(conditions)
    ]
    try:
        update_conditions(
            application_id,
            updated,
            "Aarav Kulkarni (Credit Analyst)",
            store,
        )
        result = run_simulated_disbursement(application_id, store)
    except ValueError as error:
        st.session_state["disbursement_error"] = str(error)
        return
    st.session_state["disbursement_success"] = result


def _render_sanction(application_id: str, store: SQLiteStore) -> None:
    """Render the sanction letter, KFS preview, conditions, and simulated payout."""
    simulated_badge = implementation_badge("simulated")
    sanction_rows = get_sanction(application_id, store)
    if sanction_rows.empty:
        st.info("No human sanction has been issued for this case.")
        return
    sanction = sanction_rows.iloc[0]
    st.markdown(f"### Sanction {simulated_badge}", unsafe_allow_html=True)
    st.write(f"Reference: **{sanction['sanction_ref']}**")
    st.write(
        f"Approved amount: **{fmt_inr(sanction['approved_amount'])}** · "
        f"Tenure: **{int(sanction['tenure_months'])} months** · "
        f"Rate: **{float(sanction['rate']):.2%}** · EMI: **{fmt_inr(sanction['emi'])}**"
    )
    letter_path = (config.PROJECT_ROOT / Path(sanction["letter_path"])).resolve()
    if letter_path.is_relative_to(config.PROJECT_ROOT.resolve()) and letter_path.is_file():
        st.download_button(
            "Download sanction letter",
            data=letter_path.read_bytes(),
            file_name=letter_path.name,
            mime="application/pdf",
            key=f"download_sanction_{application_id}",
            width="stretch",
        )
    else:
        st.warning("The sanction letter file is unavailable.")

    kfs = json.loads(sanction["kfs_json"])
    st.markdown(f"### Key Fact Statement preview {simulated_badge}", unsafe_allow_html=True)
    st.warning(kfs["label"])
    kfs_columns = st.columns(4)
    for column, (label, value) in zip(
        kfs_columns,
        (
            ("Amount", fmt_inr(kfs["loan_amount"])),
            ("Annual rate", f"{kfs['annual_rate']:.2%}"),
            ("APR estimate", f"{kfs['apr']:.2%}"),
            ("Monthly EMI", fmt_inr(kfs["emi"])),
            ("Tenure", f"{kfs['tenure_months']} months"),
            ("Processing fee", fmt_inr(kfs["processing_fee"])),
            ("Total interest", fmt_inr(kfs["total_interest"])),
            ("Total payable", fmt_inr(kfs["total_amount_payable"])),
        ),
    ):
        column.metric(label, value)
    st.write("**Repayment schedule summary**")
    st.write(
        f"{kfs['repayment_schedule_summary']['installments']} monthly instalments of "
        f"approximately {fmt_inr(kfs['repayment_schedule_summary']['monthly_installment'])}."
    )
    st.write(f"**Grievance contact:** {kfs['grievance_contact']}")
    st.caption(kfs["cooling_off_note"])

    conditions = json.loads(sanction["conditions_json"])
    st.markdown(f"### Conditions before disbursement {simulated_badge}", unsafe_allow_html=True)
    for index, item in enumerate(conditions):
        st.checkbox(
            item["name"],
            value=bool(item.get("complete", False)),
            key=f"sanction_condition_{application_id}_{index}",
        )
    all_complete = all(
        st.session_state.get(
            f"sanction_condition_{application_id}_{index}",
            item.get("complete", False),
        )
        for index, item in enumerate(conditions)
    )
    disbursement = get_disbursement(application_id, store)
    existing_error = st.session_state.pop("disbursement_error", None)
    if existing_error:
        st.error(existing_error)
    if not disbursement.empty:
        record = disbursement.iloc[0]
        st.markdown(f"### Disbursement {simulated_badge}", unsafe_allow_html=True)
        st.write(f"Reference: **{record['disbursement_ref']}**")
        st.write(
            f"Gross: {fmt_inr(record['gross_amount'])} · Fees: {fmt_inr(record['fees'])} · "
            f"Net credited (simulated): **{fmt_inr(record['net_amount'])}**"
        )
        st.write(
            f"Date: {format_datetime(record['disbursed_at'])} · "
            f"Mode: **{record['mode']}**"
        )
    else:
        st.button(
            "Run simulated disbursement",
            disabled=not all_complete,
            on_click=_disbursement_callback,
            args=(application_id, conditions, store),
            key=f"run_disbursement_{application_id}",
            width="stretch",
        )
        if not all_complete:
            st.caption("Complete every required condition to enable simulated disbursement.")
    success = st.session_state.pop("disbursement_success", None)
    if success and success["application_id"] == application_id:
        st.success(
            f"Simulated disbursement created: {success['disbursement_ref']} · "
            f"net {fmt_inr(success['net_amount'])}"
        )


def _render_case(application_id: str, store: SQLiteStore) -> None:
    """Render the full case view across summary and data-source tabs."""
    result = get_application(application_id, store)
    if result.empty:
        st.error("That application could not be found in the demo database.")
        st.button(
            "Back to applications",
            on_click=_clear_application,
            key="back_missing_case",
        )
        return
    application = result.iloc[0]
    customer_result = get_customer(application["customer_id"], store)
    customer = customer_result.iloc[0]
    documents = get_documents(application_id, store)
    transactions = get_transactions(application["customer_id"], store)
    loans = get_existing_loans(application["customer_id"], store)
    repayment = get_repayment_summary(application["customer_id"], store).iloc[0]

    render_header(
        "Case workspace",
        f"{application['name']} · {application['stage']}",
        "OPERATE  /  CASE FILE",
    )
    if str(application_id).startswith("APP-CUSTOM-"):
        st.markdown(status_chip("Custom case", "info"), unsafe_allow_html=True)
    if application["stage"] == "Rejected":
        st.markdown(
            f"{status_chip('Rejected', 'danger')} "
            f"Reviewed by **{escape(str(application.get('decided_by') or 'Unknown reviewer'))}** · "
            f"{escape(str(application.get('human_reason') or 'No written reason recorded.'))}",
            unsafe_allow_html=True,
        )
    back_column, assessment_column = st.columns([1, 1])
    with back_column:
        st.button(
            "Back to applications",
            key="back_to_applications",
            on_click=_clear_application,
        )
    with assessment_column:
        st.button(
            "Open in AI Assessment",
            key="open_ai_assessment",
            on_click=_open_ai_assessment,
            args=(application_id,),
        )
    case_header_card(application)
    with st.expander("Technical case reference"):
        st.code(str(application_id))
    stage_tracker(str(application["stage"]))

    tabs = st.tabs(
        [
            "Summary",
            "Documents",
            "Financials",
            "Checks",
            "AI Trace",
            "Decision",
            "Sanction & Disbursement",
            "Audit Log",
        ]
    )
    with tabs[0]:
        _render_summary(application, documents)
    with tabs[1]:
        _render_documents(application_id, documents)
    with tabs[2]:
        _render_financials(application, customer, documents, transactions, loans)
    with tabs[3]:
        _render_checks(application_id, loans, repayment, store)
    with tabs[4]:
        _render_agent_trace(application_id, store)
    with tabs[5]:
        _render_decision(application_id, application, store)
    with tabs[6]:
        _render_sanction(application_id, store)
    with tabs[7]:
        _render_audit(application_id, store)


def render(store: SQLiteStore | None = None) -> None:
    """Render the applications list or its selected application case."""
    render_disclaimer()
    store = store or SQLiteStore()
    create_schema(store)
    counts = store.table_counts()
    if counts.get("cur_applications", 0) == 0:
        _render_empty_state(store)
        return
    selected_application = st.session_state.get("selected_application")
    if selected_application:
        _render_case(selected_application, store)
        return
    _render_applications_list(store)
