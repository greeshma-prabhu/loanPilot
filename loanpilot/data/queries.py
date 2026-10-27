"""Parameterized SQL queries used by the applications list and case view."""

import json
from datetime import datetime
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
               json_extract(d.ai_reasons_json, '$.risk_band') AS risk_band,
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


def count_agent_audit_events(
    application_id: str,
    store: SQLiteStore | None = None,
) -> int:
    """Count audit events written by assessment agents for one application."""
    result = _store(store).query(
        """
        SELECT COUNT(*) AS event_count
        FROM cur_audit_log
        WHERE application_id = ? AND actor LIKE ?
        """,
        (application_id, "%Agent%"),
    )
    return int(result.iloc[0]["event_count"])


def get_agent_trace(
    application_id: str,
    run_id: str | None = None,
    store: SQLiteStore | None = None,
) -> pd.DataFrame:
    """Fetch the newest assessment trace, optionally for a specific run."""
    if run_id is None:
        return _store(store).query(
            """
            SELECT application_id, run_id, step_no, agent, tool_calls_json,
                   started_at, duration_ms, mode, handoff
            FROM cur_agent_trace
            WHERE application_id = ?
              AND run_id = (
                  SELECT run_id FROM cur_agent_trace
                  WHERE application_id = ?
                  ORDER BY started_at DESC, step_no DESC LIMIT 1
              )
            ORDER BY step_no
            """,
            (application_id, application_id),
        )
    return _store(store).query(
        """
        SELECT application_id, run_id, step_no, agent, tool_calls_json,
               started_at, duration_ms, mode, handoff
        FROM cur_agent_trace
        WHERE application_id = ? AND run_id = ?
        ORDER BY step_no
        """,
        (application_id, run_id),
    )


def save_agent_trace_step(
    application_id: str,
    run_id: str,
    step_no: int,
    agent: str,
    tool_calls_json: str,
    started_at: str,
    duration_ms: int,
    mode: str,
    handoff: str,
    store: SQLiteStore | None = None,
) -> None:
    """Persist one orchestrator step trace."""
    _store(store).execute(
        """
        INSERT INTO cur_agent_trace
            (application_id, run_id, step_no, agent, tool_calls_json,
             started_at, duration_ms, mode, handoff)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            application_id,
            run_id,
            step_no,
            agent,
            tool_calls_json,
            started_at,
            duration_ms,
            mode,
            handoff,
        ),
    )


def save_assessment_decision(
    application_id: str,
    recommendation: str,
    reasons_json: str,
    decided_at: str,
    store: SQLiteStore | None = None,
) -> None:
    """Persist AI recommendation and move the application to human review."""
    database = _store(store)
    database.execute(
        """
        INSERT INTO cur_decisions
            (application_id, ai_recommendation, ai_reasons_json)
        VALUES (?, ?, ?)
        ON CONFLICT(application_id) DO UPDATE SET
            ai_recommendation = excluded.ai_recommendation,
            ai_reasons_json = excluded.ai_reasons_json
        """,
        (application_id, recommendation, reasons_json),
    )
    database.execute(
        "UPDATE cur_applications SET stage = ? WHERE application_id = ?",
        ("Human Review", application_id),
    )
    append_audit_event(
        application_id,
        decided_at,
        "LoanPilot Orchestrator",
        "AI recommendation recorded",
        f"Recommendation: {recommendation}; handoff to Human Review",
        store=database,
    )


def append_audit_event(
    application_id: str,
    timestamp: str,
    actor: str,
    action: str,
    detail: str,
    store: SQLiteStore | None = None,
) -> None:
    """Append one auditable action with a unique event identifier."""
    _store(store).execute(
        """
        INSERT INTO cur_audit_log (event_id, application_id, ts, actor, action, detail)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            f"AGENT-{application_id}-{datetime.now().timestamp():.6f}",
            application_id,
            timestamp,
            actor,
            action,
            detail,
        ),
    )


def get_llm_cache(
    application_id: str,
    step: str,
    store: SQLiteStore | None = None,
) -> pd.DataFrame:
    """Fetch cached language-model output for an application step."""
    return _store(store).query(
        """
        SELECT application_id, step, mode, response_json, cached_at
        FROM cur_llm_cache
        WHERE application_id = ? AND step = ?
        """,
        (application_id, step),
    )


def save_llm_cache(
    application_id: str,
    step: str,
    mode: str,
    response_json: str,
    cached_at: str,
    store: SQLiteStore | None = None,
) -> None:
    """Cache language-model output per application and named step."""
    _store(store).execute(
        """
        INSERT INTO cur_llm_cache (application_id, step, mode, response_json, cached_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(application_id, step) DO UPDATE SET
            mode = excluded.mode,
            response_json = excluded.response_json,
            cached_at = excluded.cached_at
        """,
        (application_id, step, mode, response_json, cached_at),
    )
