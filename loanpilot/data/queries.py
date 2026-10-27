"""Parameterized SQL queries used by the applications list and case view."""

import json
from typing import Any, Mapping

import pandas as pd

from loanpilot.data.store import SQLiteStore

_DEFAULT_STORE = SQLiteStore()


def _store(store: SQLiteStore | None) -> SQLiteStore:
    """Return the requested store or the project database."""
    return store if store is not None else _DEFAULT_STORE


def list_applications(
    filters: Mapping[str, Any] | None = None,
    store: SQLiteStore | None = None,
) -> pd.DataFrame:
    """List applications with applicant, recommendation, risk, and owner fields."""
    filters = filters or {}
    clauses = []
    params: list[Any] = []
    if filters.get("stage") and filters["stage"] != "All":
        clauses.append("a.stage = ?")
        params.append(filters["stage"])
    if filters.get("recommendation") and filters["recommendation"] != "All":
        clauses.append("COALESCE(d.ai_recommendation, '') = ?")
        params.append(filters["recommendation"])
    if filters.get("demo_only"):
        clauses.append("a.persona_key IS NOT NULL")
    if filters.get("search"):
        clauses.append("(a.application_id LIKE ? OR c.name LIKE ?)")
        search = f"%{filters['search']}%"
        params.extend((search, search))
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT a.application_id,
               c.name AS applicant,
               a.requested_amount,
               a.tenure_months,
               a.purpose,
               a.submitted_at,
               a.stage,
               a.persona_key,
               d.ai_recommendation,
               d.decided_by AS owner,
               f.bureau_score
        FROM cur_applications a
        JOIN cur_customers c ON c.customer_id = a.customer_id
        LEFT JOIN cur_decisions d ON d.application_id = a.application_id
        LEFT JOIN srv_application_features f ON f.application_id = a.application_id
        {where_sql}
        ORDER BY CASE WHEN a.persona_key IS NOT NULL THEN 0 ELSE 1 END,
                 a.persona_key, a.submitted_at DESC, a.application_id
    """
    return _store(store).query(sql, params)


def get_application(application_id: str, store: SQLiteStore | None = None) -> pd.DataFrame:
    """Fetch one application with applicant, feature, and decision fields."""
    return _store(store).query(
        """
        SELECT a.application_id, a.customer_id, a.requested_amount,
               a.tenure_months, a.purpose, a.channel, a.submitted_at,
               a.stage, a.persona_key,
               c.name, c.dob, c.age, c.city, c.employer, c.employment_type,
               c.current_tenure_months, c.total_experience_months,
               c.net_monthly_income, c.pan_demo_id, c.kyc_status,
               c.relationship_since,
               f.income, f.existing_emi_total, f.proposed_emi, f.foir,
               f.bureau_score, f.max_dpd_24m, f.enquiries_6m,
               f.salary_credit_avg_6m, f.document_flags,
               d.ai_recommendation, d.ai_reasons_json, d.human_decision,
               d.human_reason, d.is_override, d.decided_by, d.decided_at
        FROM cur_applications a
        JOIN cur_customers c ON c.customer_id = a.customer_id
        LEFT JOIN srv_application_features f ON f.application_id = a.application_id
        LEFT JOIN cur_decisions d ON d.application_id = a.application_id
        WHERE a.application_id = ?
        """,
        (application_id,),
    )


def get_customer(customer_id: str, store: SQLiteStore | None = None) -> pd.DataFrame:
    """Fetch the curated customer profile and average account balance."""
    return _store(store).query(
        """
        SELECT c.*,
               COALESCE((
                   SELECT AVG(ac.avg_monthly_balance)
                   FROM cur_accounts ac WHERE ac.customer_id = c.customer_id
               ), 0) AS average_balance
        FROM cur_customers c
        WHERE c.customer_id = ?
        """,
        (customer_id,),
    )


def get_documents(application_id: str, store: SQLiteStore | None = None) -> pd.DataFrame:
    """Fetch registered document metadata and extracted text."""
    return _store(store).query(
        """
        SELECT doc_id, application_id, doc_type, file_name, file_path,
               text_content, uploaded_at
        FROM raw_documents
        WHERE application_id = ?
        ORDER BY uploaded_at, doc_type
        """,
        (application_id,),
    )


def get_bureau(application_id: str, store: SQLiteStore | None = None) -> pd.DataFrame:
    """Fetch and decode the mock bureau response for one application."""
    result = _store(store).query(
        """
        SELECT application_id, payload_json, fetched_at
        FROM raw_bureau_responses WHERE application_id = ?
        """,
        (application_id,),
    )
    if not result.empty:
        result["payload"] = result["payload_json"].map(json.loads)
    return result


def get_kyc(application_id: str, store: SQLiteStore | None = None) -> pd.DataFrame:
    """Fetch and decode the mock KYC response for one application."""
    result = _store(store).query(
        """
        SELECT application_id, payload_json, fetched_at
        FROM raw_kyc_responses WHERE application_id = ?
        """,
        (application_id,),
    )
    if not result.empty:
        result["payload"] = result["payload_json"].map(json.loads)
    return result


def get_existing_loans(customer_id: str, store: SQLiteStore | None = None) -> pd.DataFrame:
    """Fetch existing curated loans for one customer."""
    return _store(store).query(
        """
        SELECT loan_id, customer_id, product, sanctioned_amount, emi,
               outstanding, tenure_remaining_months, status
        FROM cur_existing_loans
        WHERE customer_id = ?
        ORDER BY status, loan_id
        """,
        (customer_id,),
    )


def get_repayment_summary(
    customer_id: str,
    store: SQLiteStore | None = None,
) -> pd.DataFrame:
    """Summarize months tracked and worst days past due across customer loans."""
    return _store(store).query(
        """
        SELECT COUNT(DISTINCT r.due_month) AS months_tracked,
               COALESCE(MAX(r.days_past_due), 0) AS max_days_past_due,
               COALESCE(SUM(CASE WHEN r.days_past_due > 0 THEN 1 ELSE 0 END), 0)
                   AS late_payment_count
        FROM cur_existing_loans l
        LEFT JOIN cur_repayments r ON r.loan_id = l.loan_id
        WHERE l.customer_id = ?
        """,
        (customer_id,),
    )


def get_transactions(customer_id: str, store: SQLiteStore | None = None) -> pd.DataFrame:
    """Fetch monthly salary, debit, and cheque-bounce aggregates."""
    return _store(store).query(
        """
        SELECT customer_id, month, salary_credit, total_debits, cheque_bounces
        FROM cur_transactions
        WHERE customer_id = ?
        ORDER BY month DESC
        LIMIT ?
        """,
        (customer_id, 6),
    )


def get_audit_log(
    application_id: str,
    store: SQLiteStore | None = None,
) -> pd.DataFrame:
    """Fetch the newest audit events for one application."""
    return _store(store).query(
        """
        SELECT ts AS time, actor, action, detail
        FROM cur_audit_log
        WHERE application_id = ?
        ORDER BY ts DESC, event_id DESC
        """,
        (application_id,),
    )
