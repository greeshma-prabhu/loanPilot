"""Applications list and synthetic case view."""

from datetime import datetime
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
    stage_tracker,
    status_chip,
)
from loanpilot.data.queries import (
    get_application,
    get_audit_log,
    get_bureau,
    get_customer,
    get_documents,
    get_existing_loans,
    get_kyc,
    get_repayment_summary,
    get_transactions,
    list_applications,
)
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.store import SQLiteStore

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


def _score_band(score: Any) -> str:
    """Map a synthetic bureau score to an illustrative risk-band label."""
    if pd.isna(score):
        return "—"
    if score >= 750:
        return "Low"
    if score >= 700:
        return "Medium"
    return "Elevated"


def _list_frame(applications: pd.DataFrame) -> pd.DataFrame:
    """Create the requested display columns from application query results."""
    if applications.empty:
        return pd.DataFrame(
            columns=[
                "ID",
                "Applicant",
                "Product",
                "Amount",
                "Stage",
                "AI recommendation",
                "Risk band",
                "Owner",
                "Age (days)",
            ]
        )
    return pd.DataFrame(
        {
            "ID": applications["application_id"],
            "Applicant": applications["applicant"],
            "Product": "Personal loan",
            "Amount": applications["requested_amount"].map(fmt_inr),
            "Stage": applications["stage"],
            "AI recommendation": applications["ai_recommendation"].fillna("—"),
            "Risk band": applications["bureau_score"].map(_score_band),
            "Owner": applications["owner"].fillna("—"),
            "Age (days)": applications["submitted_at"].map(_age_in_days),
        }
    )


def _render_empty_state(store: SQLiteStore) -> None:
    """Show an actionable empty database state."""
    st.title("Applications")
    st.info("No demo applications are loaded yet. Load the synthetic sample dataset to begin.")
    st.button("Load demo data", on_click=_load_data, args=(store,), key="load_applications_data")


def _render_demo_cards(rows: pd.DataFrame) -> None:
    """Keep persona cases above the rest of the filtered application list."""
    if rows.empty:
        return
    st.subheader("Pinned demo cases")
    for start in range(0, len(rows), 2):
        row_group = rows.iloc[start : start + 2]
        columns = st.columns(2)
        for column, (_, row) in zip(columns, row_group.iterrows()):
            persona_key = row["persona_key"]
            with column:
                st.markdown(
                    f"**{row['applicant']}** · `{row['application_id']}` "
                    f"{status_chip('Demo case', 'demo')}",
                    unsafe_allow_html=True,
                )
                st.caption(_PERSONA_STORIES[persona_key])
                st.button(
                    f"Open {row['applicant']} case",
                    key=f"open_{row['application_id']}",
                    on_click=_select_application,
                    args=(row["application_id"],),
                    width="stretch",
                )


def _render_applications_list(store: SQLiteStore) -> None:
    """Render filters, counts, pinned personas, and the historical table."""
    st.title("Applications")
    st.caption("Browse the synthetic personal-loan queue and open an application case.")
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
    filter_columns = st.columns([1.2, 1.2, 1, 2])
    with filter_columns[0]:
        stage = st.selectbox("Stage", stage_options, key="applications_stage")
    with filter_columns[1]:
        recommendation = st.selectbox(
            "AI recommendation",
            recommendation_options,
            key="applications_recommendation",
        )
    with filter_columns[2]:
        demo_only = st.toggle("Demo cases only", key="applications_demo_only")
    with filter_columns[3]:
        search = st.text_input("Search ID or applicant", key="applications_search")

    filters = {
        "stage": stage,
        "recommendation": recommendation,
        "demo_only": demo_only,
        "search": search.strip(),
    }
    filtered = list_applications(filters, store)
    demo_rows = filtered.loc[filtered["persona_key"].notna()]
    historical_rows = filtered.loc[filtered["persona_key"].isna()]

    metric_columns = st.columns(3)
    metric_columns[0].metric("Matching applications", len(filtered))
    metric_columns[1].metric("Demo cases", len(demo_rows))
    metric_columns[2].metric("Historical applications", len(historical_rows))
    _render_demo_cards(demo_rows)

    st.subheader("Application list")
    st.dataframe(
        _list_frame(filtered),
        width="stretch",
        hide_index=True,
        key="applications_table",
    )

    if not historical_rows.empty:
        historical_options = historical_rows["application_id"].tolist()
        selected_historical = st.selectbox(
            "Open historical application",
            historical_options,
            format_func=lambda application_id: (
                f"{application_id} · "
                f"{historical_rows.loc[historical_rows.application_id == application_id, 'applicant'].iloc[0]}"
            ),
            key="historical_case_select",
        )
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
                f"uploaded {document['uploaded_at']}"
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
            kpi_card(label, value, help_text=formula, real=True)


def _render_checks(
    application_id: str,
    loans: pd.DataFrame,
    repayment_summary: pd.Series,
    store: SQLiteStore,
) -> None:
    """Render source panels for core banking, bureau, KYC, and CERSAI."""
    simulated_badge = implementation_badge("simulated")
    bureau = _single_bureau(application_id, store)
    kyc = _single_kyc(application_id, store)

    with st.container(border=True):
        st.markdown(f"### Core banking record {simulated_badge}", unsafe_allow_html=True)
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
        st.markdown(f"### Credit bureau response {simulated_badge}", unsafe_allow_html=True)
        st.write(f"Score: {bureau.get('score') if bureau.get('score') is not None else 'No history (thin file)'}")
        st.write(
            f"Active accounts: {bureau.get('active_accounts', '—')} · "
            f"Enquiries (6 months): {bureau.get('enquiries_6m', '—')} · "
            f"Max DPD (24 months): {bureau.get('max_dpd_24m', '—')}"
        )
        st.write(f"Written off: {'Yes' if bureau.get('written_off') else 'No'}")

    with st.container(border=True):
        st.markdown(f"### KYC response {simulated_badge}", unsafe_allow_html=True)
        st.write(f"PAN status: {kyc.get('pan_status', 'Unavailable')}")
        st.write(f"Name-match score: {kyc.get('name_match_score', 'Unavailable')}")

    with st.container(border=True):
        st.markdown(f"### CERSAI {simulated_badge}", unsafe_allow_html=True)
        st.write("Not applicable (unsecured personal loan)")


def _render_audit(application_id: str, store: SQLiteStore) -> None:
    """Render newest audit events for this application."""
    audit = get_audit_log(application_id, store)
    if audit.empty:
        st.info("No audit events are recorded for this application.")
    else:
        st.dataframe(audit, width="stretch", hide_index=True)


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
        st.info("The AI assessment trace and evidence summary will appear here. Built in phase 4.")
    with tabs[5]:
        st.info("Human review, final decision, and any override rationale will appear here. Built in phase 5.")
    with tabs[6]:
        st.info("Human sanction approval and simulated disbursement details will appear here. Built in phase 5.")
    with tabs[7]:
        _render_audit(application_id, store)


def render(store: SQLiteStore | None = None) -> None:
    """Render the applications list or its selected application case."""
    store = store or SQLiteStore()
    counts = store.table_counts()
    if counts.get("cur_applications", 0) == 0:
        _render_empty_state(store)
        return
    selected_application = st.session_state.get("selected_application")
    if selected_application:
        _render_case(selected_application, store)
        return
    _render_applications_list(store)
