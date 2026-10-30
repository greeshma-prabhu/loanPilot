"""Parameterized SQL queries used by the applications list and case view."""

import json
from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

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
    if filters.get("user_created_only"):
        clauses.extend(
            (
                "(a.persona_key IS NULL OR a.application_id LIKE 'APP-SYNTH-%')",
                "a.application_id NOT LIKE 'APP-HIST-%'",
            )
        )
    if filters.get("worklist") == "Active":
        clauses.append(
            "a.stage NOT IN ('Rejected', 'Disbursed (simulated)', 'Awaiting documents')"
        )
    elif filters.get("worklist") == "Closed":
        clauses.append(
            "a.stage IN ('Rejected', 'Disbursed (simulated)', 'Awaiting documents')"
        )
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
               d.human_decision,
               COALESCE(NULLIF(d.decided_by, ''), a.owner) AS owner,
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


def get_persona_document_records(
    application_ids: list[str],
    store: SQLiteStore | None = None,
) -> pd.DataFrame:
    """Fetch seeded persona applications and their registered document paths."""
    if not application_ids:
        return pd.DataFrame(columns=["application_id", "doc_type", "file_path"])
    placeholders = ", ".join("?" for _ in application_ids)
    return _store(store).query(
        "SELECT a.application_id, d.doc_type, d.file_path "
        "FROM cur_applications a "
        "LEFT JOIN raw_documents d ON d.application_id = a.application_id "
        f"WHERE a.application_id IN ({placeholders})",
        application_ids,
    )


def get_application(application_id: str, store: SQLiteStore | None = None) -> pd.DataFrame:
    """Fetch one application with applicant, feature, and decision fields."""
    return _store(store).query(
        """
        SELECT a.application_id, a.customer_id, a.requested_amount,
               a.tenure_months, a.purpose, a.channel, a.submitted_at,
               a.stage, a.persona_key,
               c.name, c.dob, c.age, c.city, c.mobile, c.employer, c.employment_type,
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


def list_intake_customers(store: SQLiteStore | None = None) -> pd.DataFrame:
    """Return searchable synthetic core customers and their latest loan term."""
    return _store(store).query(
        """
        SELECT c.customer_id, c.name, c.dob, c.age, c.city, c.mobile,
               c.employer, c.employment_type, c.current_tenure_months,
               c.total_experience_months, c.net_monthly_income, c.pan_demo_id,
               c.kyc_status,
               COALESCE((
                   SELECT a.tenure_months
                   FROM cur_applications a
                   WHERE a.customer_id = c.customer_id
                   ORDER BY a.submitted_at DESC, a.application_id
                   LIMIT 1
               ), 36) AS prior_tenure_months
        FROM cur_customers c
        ORDER BY c.name, c.customer_id
        """
    )


def save_kyc_response(
    application_id: str,
    payload: Mapping[str, Any],
    store: SQLiteStore | None = None,
) -> None:
    """Replace the case's KYC response and synchronize its curated status."""
    database = _store(store)
    now = datetime.now().isoformat(timespec="seconds")
    database.execute(
        """
        INSERT INTO raw_kyc_responses (application_id, payload_json, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(application_id) DO UPDATE SET
            payload_json = excluded.payload_json,
            fetched_at = excluded.fetched_at
        """,
        (application_id, json.dumps(dict(payload), sort_keys=True), now),
    )
    database.execute(
        """
        UPDATE cur_customers
        SET kyc_status = ?
        WHERE customer_id = (
            SELECT customer_id FROM cur_applications WHERE application_id = ?
        )
        """,
        (str(payload.get("status", payload.get("pan_status", "pending"))), application_id),
    )


def get_documents(application_id: str, store: SQLiteStore | None = None) -> pd.DataFrame:
    """Fetch registered document metadata and extracted text."""
    return _store(store).query(
        """
        SELECT doc_id, application_id, doc_type,
               COALESCE(NULLIF(category, ''), doc_type) AS category,
               file_name, file_path,
               text_content, uploaded_at
        FROM raw_documents
        WHERE application_id = ?
        ORDER BY uploaded_at, doc_type
        """,
        (application_id,),
    )


def get_document_verifications(
    application_id: str,
    store: SQLiteStore | None = None,
) -> list[dict[str, Any]]:
    """Fetch parsed, source-linked extraction and consistency results."""
    from loanpilot.data.document_verification import decode_verification_row

    rows = _store(store).query(
        """
        SELECT v.*, d.file_name, d.file_path, d.category, d.doc_type
        FROM raw_document_verifications v
        JOIN raw_documents d ON d.doc_id = v.doc_id
        WHERE v.application_id = ?
        ORDER BY d.uploaded_at, d.doc_id
        """,
        (application_id,),
    )
    return [decode_verification_row(row) for row in rows.to_dict("records")]


def get_document_verification_report(
    application_id: str,
    store: SQLiteStore | None = None,
) -> dict[str, Any] | None:
    """Fetch the persisted case-level completeness and verification summary."""
    result = _store(store).query(
        "SELECT overall_status, report_json, created_at "
        "FROM raw_document_verification_reports WHERE application_id = ?",
        (application_id,),
    )
    if result.empty:
        return None
    row = result.iloc[0]
    try:
        report = json.loads(row["report_json"])
    except (json.JSONDecodeError, TypeError):
        report = {}
    return {
        **report,
        "overall_status": row["overall_status"],
        "created_at": row["created_at"],
    }


def register_document(
    application_id: str,
    document: Mapping[str, Any],
    store: SQLiteStore | None = None,
) -> None:
    """Register one newly captured document in the RAW evidence table."""
    _store(store).execute(
        """
        INSERT INTO raw_documents
            (doc_id, application_id, doc_type, category, file_name, file_path,
             text_content, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"DOC-{uuid4().hex.upper()}",
            application_id,
            document["doc_type"],
            document.get("category", document["doc_type"]),
            document["file_name"],
            document["file_path"],
            document["text_content"],
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def save_persona_documents(
    rows: list[tuple[Any, ...]],
    store: SQLiteStore | None = None,
) -> int:
    """Insert or refresh deterministic seeded-document records."""
    return _store(store).execute_many(
        "INSERT INTO raw_documents "
        "(doc_id, application_id, doc_type, file_name, file_path, text_content, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(doc_id) DO UPDATE SET "
        "application_id = excluded.application_id, "
        "doc_type = excluded.doc_type, file_name = excluded.file_name, "
        "file_path = excluded.file_path, text_content = excluded.text_content, "
        "uploaded_at = excluded.uploaded_at",
        rows,
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


def get_review_queue(store: SQLiteStore | None = None) -> pd.DataFrame:
    """Fetch human-review cases, prioritizing decline overrides and referrals."""
    return _store(store).query(
        """
        SELECT a.application_id, a.submitted_at, a.persona_key, a.stage,
               c.name AS applicant, d.ai_recommendation,
               json_extract(d.ai_reasons_json, '$.risk_band') AS risk_band,
               d.human_decision, d.ai_reasons_json
        FROM cur_applications a
        JOIN cur_customers c ON c.customer_id = a.customer_id
        LEFT JOIN cur_decisions d ON d.application_id = a.application_id
        WHERE a.stage = ?
        ORDER BY CASE
                     WHEN d.ai_recommendation = 'Decline' THEN 0
                     WHEN d.ai_recommendation = 'Refer' THEN 1
                     ELSE 2
                 END,
                 a.submitted_at ASC,
                 a.application_id
        """,
        ("Human Review",),
    )


def get_human_review_cases(
    status_filter: str = "Pending",
    search: str = "",
    store: SQLiteStore | None = None,
    *,
    user_created_only: bool = False,
) -> pd.DataFrame:
    """Fetch cases for the Human Review queue using its status and search filters."""
    stage_filters = {
        "Pending": ("Human Review",),
        "Approved": ("Approved", "Sanction", "Disbursed (simulated)"),
        "Rejected": ("Rejected",),
        "All": None,
    }
    if status_filter not in stage_filters:
        raise ValueError(f"Unknown Human Review status filter: {status_filter}")
    stages = stage_filters[status_filter]
    search_sql = ""
    params: list[Any] = []
    stage_sql = ""
    if stages is not None:
        placeholders = ", ".join("?" for _ in stages)
        stage_sql = f"a.stage IN ({placeholders}) AND "
        params.extend(stages)
    if user_created_only:
        search_sql += (
            "AND (a.persona_key IS NULL OR a.application_id LIKE 'APP-SYNTH-%') "
            "AND a.application_id NOT LIKE 'APP-HIST-%' "
        )
    if search.strip():
        search_sql += "AND (c.name LIKE ? OR a.application_id LIKE ?) "
        pattern = f"%{search.strip()}%"
        params.extend((pattern, pattern))
    return _store(store).query(
        f"""
        SELECT a.application_id, a.submitted_at, a.stage,
               a.requested_amount, a.tenure_months,
               c.name AS applicant, c.age, c.city,
               d.ai_recommendation, d.human_decision, d.human_reason,
               d.is_override, d.decided_by, d.decided_at,
               json_extract(d.ai_reasons_json, '$.risk_band') AS risk_band
        FROM cur_applications a
        JOIN cur_customers c ON c.customer_id = a.customer_id
        LEFT JOIN cur_decisions d ON d.application_id = a.application_id
        WHERE {stage_sql}1 = 1
        {search_sql}
        ORDER BY CASE a.stage
                     WHEN 'Human Review' THEN 0
                     WHEN 'Approved' THEN 1
                     WHEN 'Sanction' THEN 2
                     WHEN 'Disbursed (simulated)' THEN 3
                     WHEN 'Rejected' THEN 4
                     WHEN 'Escalated' THEN 5
                     WHEN 'Awaiting documents' THEN 6
                     ELSE 7
                 END,
                 a.submitted_at ASC,
                 a.application_id
        """,
        params,
    )


def human_decision_is_override(ai_recommendation: str | None, decision: str) -> bool:
    """Return whether a human outcome differs from the AI recommendation."""
    expected_recommendations = {
        "Approve": "Approve",
        "Approve with conditions": "Approve",
        "Modify terms": "Approve",
        "Refer up": "Refer",
        "Request documents": "Refer",
        "Reject": "Decline",
    }
    return expected_recommendations.get(decision) != ai_recommendation


def has_live_gemini_trace(store: SQLiteStore | None = None) -> bool:
    """Return whether a persisted assessment trace used Gemini live."""
    database = _store(store)
    tables = database.query(
        "SELECT name FROM sqlite_master WHERE type = ? AND name = ?",
        ("table", "cur_agent_trace"),
    )
    if tables.empty:
        return False
    result = database.query(
        "SELECT COUNT(*) AS live_steps FROM cur_agent_trace WHERE mode = ?",
        ("Live Gemini",),
    )
    return int(result.iloc[0]["live_steps"]) > 0


def get_sanction(
    application_id: str,
    store: SQLiteStore | None = None,
) -> pd.DataFrame:
    """Fetch the sanction and KFS record for an application."""
    return _store(store).query(
        """
        SELECT application_id, sanction_ref, approved_amount, tenure_months,
               rate, emi, conditions_json, letter_path, kfs_json, generated_at
        FROM cur_sanctions
        WHERE application_id = ?
        """,
        (application_id,),
    )


def get_disbursement(
    application_id: str,
    store: SQLiteStore | None = None,
) -> pd.DataFrame:
    """Fetch a simulated disbursement record for an application."""
    return _store(store).query(
        """
        SELECT application_id, disbursement_ref, gross_amount, fees, net_amount,
               disbursed_at, mode
        FROM cur_disbursements
        WHERE application_id = ?
        """,
        (application_id,),
    )


def record_human_decision(
    application_id: str,
    decision: str,
    reason: str,
    is_override: bool,
    reviewer: str,
    decided_at: str,
    next_stage: str,
    store: SQLiteStore | None = None,
) -> None:
    """Record a human review, enforce a reason, and update stage atomically."""
    if len(reason.strip()) < 20:
        raise ValueError("A written reason of at least 20 characters is required.")
    database = _store(store)
    with database.connection() as connection:
        application = connection.execute(
            """
            SELECT a.stage, d.ai_recommendation
            FROM cur_applications a
            JOIN cur_decisions d ON d.application_id = a.application_id
            WHERE a.application_id = ?
            """,
            (application_id,),
        ).fetchone()
        if application is None:
            raise ValueError(f"Unknown application: {application_id}")
        if application["stage"] != "Human Review":
            raise ValueError("Only cases in Human Review can receive a decision.")
        expected_override = human_decision_is_override(
            application["ai_recommendation"], decision
        )
        if bool(is_override) != expected_override:
            raise ValueError("Override flag does not match the AI and human decisions.")
        if next_stage not in {
            "Sanction",
            "Rejected",
            "Escalated",
            "Awaiting documents",
        }:
            raise ValueError(f"Unsupported human-review stage: {next_stage}")
        connection.execute(
            """
            UPDATE cur_decisions
            SET human_decision = ?, human_reason = ?, is_override = ?,
                decided_by = ?, decided_at = ?
            WHERE application_id = ?
            """,
            (
                decision,
                reason.strip(),
                int(expected_override),
                reviewer,
                decided_at,
                application_id,
            ),
        )
        connection.execute(
            "UPDATE cur_applications SET stage = ? WHERE application_id = ?",
            (next_stage, application_id),
        )
        connection.execute(
            """
            INSERT INTO cur_audit_log
                (event_id, application_id, ts, actor, action, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"HUMAN-{application_id}-{datetime.now().timestamp():.6f}",
                application_id,
                decided_at,
                reviewer,
                f"Human decision: {decision}",
                f"Stage: {next_stage}; override: {int(expected_override)}; reason: {reason.strip()}",
            ),
        )


def create_sanction(
    application_id: str,
    sanction_ref: str,
    approved_amount: float,
    tenure_months: int,
    rate: float,
    emi: float,
    conditions_json: str,
    letter_path: str,
    kfs_json: str,
    generated_at: str,
    store: SQLiteStore | None = None,
) -> None:
    """Persist a sanction only after the human approval stage transition."""
    database = _store(store)
    with database.connection() as connection:
        decision = connection.execute(
            """
            SELECT a.stage, d.human_decision
            FROM cur_applications a
            JOIN cur_decisions d ON d.application_id = a.application_id
            WHERE a.application_id = ?
            """,
            (application_id,),
        ).fetchone()
        if decision is None:
            raise ValueError(f"Unknown application: {application_id}")
        if decision["stage"] != "Sanction" or decision["human_decision"] not in {
            "Approve",
            "Approve with conditions",
            "Modify terms",
        }:
            raise ValueError("A human approval is required before sanction.")
        connection.execute(
            """
            INSERT INTO cur_sanctions
                (application_id, sanction_ref, approved_amount, tenure_months,
                 rate, emi, conditions_json, letter_path, kfs_json, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(application_id) DO NOTHING
            """,
            (
                application_id,
                sanction_ref,
                approved_amount,
                tenure_months,
                rate,
                emi,
                conditions_json,
                letter_path,
                kfs_json,
                generated_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO cur_audit_log
                (event_id, application_id, ts, actor, action, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"SANCTION-{application_id}-{datetime.now().timestamp():.6f}",
                application_id,
                generated_at,
                "Aarambh Bank Human Review",
                "Sanction generated",
                f"{sanction_ref}; approved amount {approved_amount:.2f}",
            ),
        )


def update_sanction_conditions(
    application_id: str,
    conditions_json: str,
    updated_at: str,
    reviewer: str,
    store: SQLiteStore | None = None,
) -> None:
    """Persist completion status for all sanction conditions."""
    database = _store(store)
    result = database.execute(
        "UPDATE cur_sanctions SET conditions_json = ? WHERE application_id = ?",
        (conditions_json, application_id),
    )
    if result == 0:
        raise ValueError(f"No sanction exists for application: {application_id}")
    append_audit_event(
        application_id,
        updated_at,
        reviewer,
        "Updated sanction conditions",
        conditions_json,
        database,
    )


def record_disbursement(
    application_id: str,
    disbursement_ref: str,
    gross_amount: float,
    fees: float,
    net_amount: float,
    disbursed_at: str,
    store: SQLiteStore | None = None,
) -> None:
    """Record simulated disbursement only when every condition is complete."""
    import json

    database = _store(store)
    with database.connection() as connection:
        sanction = connection.execute(
            """
            SELECT a.stage, s.conditions_json
            FROM cur_applications a
            JOIN cur_sanctions s ON s.application_id = a.application_id
            WHERE a.application_id = ?
            """,
            (application_id,),
        ).fetchone()
        if sanction is None:
            raise ValueError("A sanction is required before disbursement.")
        if sanction["stage"] != "Sanction":
            raise ValueError("Only sanctioned cases can be disbursed.")
        conditions = json.loads(sanction["conditions_json"])
        if any(not item.get("complete", False) for item in conditions):
            raise ValueError("All sanction conditions must be completed before disbursement.")
        connection.execute(
            """
            INSERT INTO cur_disbursements
                (application_id, disbursement_ref, gross_amount, fees,
                 net_amount, disbursed_at, mode)
            VALUES (?, ?, ?, ?, ?, ?, 'simulated')
            """,
            (
                application_id,
                disbursement_ref,
                gross_amount,
                fees,
                net_amount,
                disbursed_at,
            ),
        )
        connection.execute(
            "UPDATE cur_applications SET stage = ? WHERE application_id = ?",
            ("Disbursed (simulated)", application_id),
        )
        connection.execute(
            """
            INSERT INTO cur_audit_log
                (event_id, application_id, ts, actor, action, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"DISBURSE-{application_id}-{datetime.now().timestamp():.6f}",
                application_id,
                disbursed_at,
                "LoanPilot Simulated Disbursement",
                "Simulated disbursement completed",
                f"{disbursement_ref}; gross {gross_amount:.2f}; fees {fees:.2f}; net {net_amount:.2f}",
            ),
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


def clear_llm_cache(application_id: str, store: SQLiteStore | None = None) -> None:
    """Clear generated language cache before an explicitly rerun assessment."""
    _store(store).execute(
        "DELETE FROM cur_llm_cache WHERE application_id = ?",
        (application_id,),
    )


def overview_pipeline_counts(store: SQLiteStore | None = None) -> pd.DataFrame:
    """Count active applications grouped by their current stage."""
    return _store(store).query(
        """
        SELECT stage, COUNT(*) AS application_count
        FROM cur_applications
        WHERE stage NOT IN ('Rejected', 'Disbursed (simulated)', 'Awaiting documents')
        GROUP BY stage
        ORDER BY application_count DESC, stage
        """
    )


def overview_recommendation_counts(store: SQLiteStore | None = None) -> pd.DataFrame:
    """Count saved AI recommendations by decision category."""
    return _store(store).query(
        """
        SELECT ai_recommendation AS recommendation, COUNT(*) AS application_count
        FROM cur_decisions
        WHERE ai_recommendation IN ('Approve', 'Refer', 'Decline')
        GROUP BY ai_recommendation
        ORDER BY CASE ai_recommendation
                     WHEN 'Approve' THEN 1 WHEN 'Refer' THEN 2 ELSE 3
                 END
        """
    )


def overview_risk_counts(store: SQLiteStore | None = None) -> pd.DataFrame:
    """Count saved AI risk bands."""
    return _store(store).query(
        """
        SELECT json_extract(ai_reasons_json, '$.risk_band') AS risk_band,
               COUNT(*) AS application_count
        FROM cur_decisions
        WHERE ai_recommendation IN ('Approve', 'Refer', 'Decline')
          AND json_extract(ai_reasons_json, '$.risk_band') IS NOT NULL
        GROUP BY risk_band
        ORDER BY CASE risk_band
                     WHEN 'Low' THEN 1 WHEN 'Medium' THEN 2 WHEN 'High' THEN 3
                     ELSE 4
                 END
        """
    )


def overview_metrics(store: SQLiteStore | None = None) -> dict[str, float | int | None]:
    """Return database-backed pipeline, recommendation, turnaround and review metrics."""
    row = _store(store).query(
        """
        SELECT
            (SELECT COUNT(*) FROM cur_applications
             WHERE stage NOT IN ('Rejected', 'Disbursed (simulated)', 'Awaiting documents'))
                AS pipeline_count,
            (SELECT COUNT(*) FROM cur_decisions
             WHERE ai_recommendation = 'Approve') AS approve_count,
            (SELECT COUNT(*) FROM cur_decisions
             WHERE ai_recommendation = 'Refer') AS refer_count,
            (SELECT COUNT(*) FROM cur_decisions
             WHERE ai_recommendation = 'Decline') AS decline_count,
            (SELECT COUNT(*) FROM cur_applications WHERE stage = 'Human Review')
                AS pending_review_count,
            (SELECT COUNT(*) FROM cur_applications WHERE stage = 'Rejected')
                AS rejected_count,
            (SELECT COUNT(*) FROM cur_applications WHERE stage = 'Sanction')
                AS approved_count,
            (SELECT COUNT(*) FROM cur_applications WHERE stage = 'Disbursed (simulated)')
                AS disbursed_count,
            (SELECT AVG((julianday(d.decided_at) - julianday(a.submitted_at)) * 24)
             FROM cur_applications a
             JOIN cur_decisions d ON d.application_id = a.application_id
             WHERE a.application_id LIKE 'APP-HIST-%'
               AND d.decided_at IS NOT NULL)
                AS historical_processing_hours
        """
    ).iloc[0]
    return {
        key: None if pd.isna(value) else value.item() if hasattr(value, "item") else value
        for key, value in row.items()
    }


def overview_attention_cases(store: SQLiteStore | None = None) -> pd.DataFrame:
    """List operational review cases and synthetic examples needing attention."""
    return _store(store).query(
        """
        SELECT a.application_id, c.name AS applicant, a.submitted_at,
               a.requested_amount, a.stage, d.ai_recommendation,
               json_extract(d.ai_reasons_json, '$.risk_band') AS risk_band,
               json_extract(d.ai_reasons_json, '$.attention_priority')
                   AS attention_priority,
               json_extract(d.ai_reasons_json, '$.attention_reason')
                   AS attention_reason,
               a.application_id LIKE 'APP-SYNTH-%' AS is_synthetic
        FROM cur_applications a
        JOIN cur_customers c ON c.customer_id = a.customer_id
        LEFT JOIN cur_decisions d ON d.application_id = a.application_id
        WHERE (a.stage = ? OR (
              a.application_id LIKE 'APP-SYNTH-%'
              AND json_extract(d.ai_reasons_json, '$.attention_reason') IS NOT NULL
              AND a.stage NOT IN ('Approved', 'Rejected', 'Disbursed (simulated)')
        ))
          AND (a.persona_key IS NULL OR a.application_id LIKE 'APP-SYNTH-%')
          AND a.application_id NOT LIKE 'APP-HIST-%'
          AND a.application_id NOT LIKE 'APP-CUSTOM-%'
        ORDER BY CASE json_extract(d.ai_reasons_json, '$.attention_priority')
                     WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2
                     ELSE 3
                 END,
                 a.submitted_at, a.application_id
        """,
        ("Human Review",),
    )


def overview_dashboard_records(store: SQLiteStore | None = None) -> pd.DataFrame:
    """Return one row per operational or explicitly seeded synthetic case."""
    return _store(store).query(
        """
        SELECT a.application_id, c.name AS applicant, a.requested_amount,
               a.submitted_at, a.stage, a.persona_key,
               d.human_decision, d.ai_recommendation,
               json_extract(d.ai_reasons_json, '$.risk_band') AS risk_band,
               json_extract(d.ai_reasons_json, '$.attention_reason')
                   AS attention_reason,
               CASE WHEN a.application_id LIKE 'APP-SYNTH-%'
                    THEN 1 ELSE 0 END AS is_synthetic
        FROM cur_applications a
        JOIN cur_customers c ON c.customer_id = a.customer_id
        LEFT JOIN cur_decisions d ON d.application_id = a.application_id
        WHERE (a.persona_key IS NULL OR a.application_id LIKE 'APP-SYNTH-%')
          AND a.application_id NOT LIKE 'APP-HIST-%'
          AND a.application_id NOT LIKE 'APP-CUSTOM-%'
        ORDER BY a.submitted_at DESC, a.application_id
        """
    )


def overview_cases(store: SQLiteStore | None = None) -> pd.DataFrame:
    """Return the six personas and permanent/custom intake cases for the dashboard."""
    return _store(store).query(
        """
        SELECT a.application_id, a.persona_key, a.stage, a.requested_amount,
               c.name AS applicant, d.ai_recommendation, d.human_decision,
               d.is_override, d.decided_by, d.human_reason, d.decided_at
        FROM cur_applications a
        JOIN cur_customers c ON c.customer_id = a.customer_id
        LEFT JOIN cur_decisions d ON d.application_id = a.application_id
        WHERE a.persona_key IS NOT NULL
           OR a.application_id LIKE 'APP-CUSTOM-%'
        ORDER BY CASE WHEN a.persona_key IS NOT NULL THEN 0 ELSE 1 END,
                 a.persona_key, a.application_id
        """
    )


def overview_historical_metrics(store: SQLiteStore | None = None) -> dict[str, int | float]:
    """Summarize only the 60 historical applications, outside the active pipeline."""
    row = _store(store).query(
        """
        SELECT COUNT(*) AS case_count,
               SUM(CASE WHEN d.ai_recommendation = 'Approved' THEN 1 ELSE 0 END)
                   AS approved_count,
               SUM(CASE WHEN d.ai_recommendation = 'Declined' THEN 1 ELSE 0 END)
                   AS declined_count,
               SUM(CASE WHEN d.ai_recommendation = 'Referred' THEN 1 ELSE 0 END)
                   AS referred_count,
               AVG(julianday(d.decided_at) - julianday(a.submitted_at))
                   AS average_processing_days
        FROM cur_applications a
        JOIN cur_decisions d ON d.application_id = a.application_id
        WHERE a.application_id LIKE 'APP-HIST-%'
        """
    ).iloc[0]
    return {
        key: 0 if pd.isna(value) else value.item() if hasattr(value, "item") else value
        for key, value in row.items()
    }


def create_intake_application(
    applicant: Mapping[str, Any],
    application: Mapping[str, Any],
    bureau: Mapping[str, Any],
    kyc: Mapping[str, Any],
    documents: list[Mapping[str, Any]],
    store: SQLiteStore | None = None,
    *,
    application_id: str | None = None,
    customer_id: str | None = None,
    owner: str = "",
    verification_report: Mapping[str, Any] | None = None,
) -> str:
    """Atomically register a new synthetic applicant, case, evidence and audit event."""
    database = _store(store)
    application_id = application_id or f"APP-NEW-{uuid4().hex[:12].upper()}"
    customer_id = customer_id or f"CUST-NEW-{uuid4().hex[:12].upper()}"
    submitted_at = str(application["submitted_at"])
    now = datetime.now().isoformat(timespec="seconds")
    with database.connection() as connection:
        if applicant.get("existing_customer"):
            customer_exists = connection.execute(
                "SELECT 1 FROM cur_customers WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
            if customer_exists is None:
                raise ValueError(f"Unknown existing customer id: {customer_id}")
            connection.execute(
                "UPDATE cur_customers SET kyc_status = ? WHERE customer_id = ?",
                (str(kyc.get("status", "verified")), customer_id),
            )
        else:
            connection.execute(
                """
                INSERT INTO cur_customers
                    (customer_id, name, dob, age, city, mobile, employer, employment_type,
                     current_tenure_months, total_experience_months, net_monthly_income,
                     pan_demo_id, kyc_status, relationship_since)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_id,
                    applicant["name"],
                    applicant["dob"],
                    int(applicant["age"]),
                    applicant["city"],
                    applicant["mobile"],
                    applicant["employer"],
                    applicant["employment_type"],
                    int(applicant["current_tenure_months"]),
                    int(applicant["total_experience_months"]),
                    float(applicant["net_monthly_income"]),
                    applicant["pan_demo_id"],
                    str(kyc.get("status", "pending")),
                    now[:10],
                ),
            )
        connection.execute(
            """
            INSERT INTO cur_applications
                (application_id, customer_id, requested_amount, tenure_months,
                 purpose, channel, submitted_at, stage, persona_key, owner)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Submitted', NULL, ?)
            """,
            (
                application_id,
                customer_id,
                float(application["requested_amount"]),
                int(application["tenure_months"]),
                application["purpose"],
                "Guided demo",
                submitted_at,
                owner,
            ),
        )
        if not applicant.get("existing_customer"):
            connection.execute(
                """
                INSERT INTO cur_accounts
                    (account_id, customer_id, type, avg_monthly_balance, opened_on)
                VALUES (?, ?, 'Savings (synthetic)', 0, ?)
                """,
                (f"ACCT-{customer_id}", customer_id, now[:10]),
            )
            if float(applicant["existing_emi"]) > 0:
                connection.execute(
                    """
                    INSERT INTO cur_existing_loans
                        (loan_id, customer_id, product, sanctioned_amount, emi,
                         outstanding, tenure_remaining_months, status)
                    VALUES (?, ?, 'Existing obligation (declared)', 0, ?, 0, 0, 'Active')
                    """,
                    (f"LOAN-{customer_id}", customer_id, float(applicant["existing_emi"])),
                )
        month = datetime.fromisoformat(submitted_at).date().replace(day=1)
        if not applicant.get("existing_customer"):
            transaction_rows = []
            for offset in range(6):
                month_index = month.year * 12 + month.month - 1 - offset
                transaction_month = datetime(
                    month_index // 12,
                    month_index % 12 + 1,
                    1,
                ).strftime("%Y-%m")
                transaction_rows.append(
                    (
                        customer_id,
                        transaction_month,
                        float(applicant["net_monthly_income"]),
                        0.0,
                        0,
                    )
                )
            connection.executemany(
                """
                INSERT INTO cur_transactions
                    (customer_id, month, salary_credit, total_debits, cheque_bounces)
                VALUES (?, ?, ?, ?, ?)
                """,
                transaction_rows,
            )
        connection.execute(
            """
            INSERT INTO raw_bureau_responses (application_id, payload_json, fetched_at)
            VALUES (?, ?, ?)
            """,
            (application_id, json.dumps(bureau, sort_keys=True), now),
        )
        connection.execute(
            """
            INSERT INTO raw_kyc_responses (application_id, payload_json, fetched_at)
            VALUES (?, ?, ?)
            """,
            (application_id, json.dumps(kyc, sort_keys=True), now),
        )
        document_rows = []
        verification_rows = []
        for document in documents:
            doc_id = f"DOC-{uuid4().hex.upper()}"
            document_rows.append(
                (
                    doc_id,
                    application_id,
                    document["doc_type"],
                    document.get("category", document["doc_type"]),
                    document["file_name"],
                    document["file_path"],
                    document["text_content"],
                    now,
                )
            )
            verification = document.get("verification")
            if verification:
                verification_rows.append(
                    (
                        doc_id,
                        application_id,
                        str(verification.get("extraction_status", "Unavailable")),
                        str(verification.get("extraction_method", "Unavailable")),
                        json.dumps(
                            verification.get("extracted_fields", {}),
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            verification.get("field_evidence", {}),
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            verification.get("checks", []),
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                        str(verification.get("ai_explanation", "")),
                        str(verification.get("verification_status", "Unable to verify")),
                        str(verification.get("explanation", "")),
                        str(
                            verification.get(
                                "authenticity_status", "Not independently verified"
                            )
                        ),
                    )
                )
        connection.executemany(
            """
            INSERT INTO raw_documents
                (doc_id, application_id, doc_type, category, file_name, file_path,
                 text_content, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            document_rows,
        )
        connection.executemany(
            """
            INSERT INTO raw_document_verifications
                (doc_id, application_id, extraction_status, extraction_method,
                 extracted_fields_json, field_evidence_json, checks_json,
                 ai_explanation, verification_status, explanation, authenticity_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            verification_rows,
        )
        if verification_report is not None:
            connection.execute(
                """
                INSERT INTO raw_document_verification_reports
                    (application_id, overall_status, report_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    application_id,
                    str(verification_report.get("overall_status", "Incomplete")),
                    json.dumps(
                        dict(verification_report), sort_keys=True, ensure_ascii=False
                    ),
                    now,
                ),
            )
        connection.execute(
            """
            INSERT INTO cur_audit_log
                (event_id, application_id, ts, actor, action, detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"INTAKE-{uuid4().hex.upper()}",
                application_id,
                now,
                owner or "LoanPilot Guided Intake",
                "Application submitted",
                "Synthetic applicant and declared documents registered.",
            ),
        )
    return application_id


_EXPLORER_OBJECTS: dict[str, dict[str, str]] = {
    "raw": {
        "raw_documents": "Financial and identity document metadata, extracted text and project-relative file paths.",
        "raw_bureau_responses": "Synthetic bureau request responses stored as JSON.",
        "raw_kyc_responses": "Simulated eKYC and synthetic KYC status, match score, method and document references stored as JSON.",
        "raw_policy_docs": "Policy clause text and version information.",
    },
    "curated": {
        "cur_customers": "Applicant identity and declared financial profile; identifiers are fake.",
        "cur_accounts": "Synthetic account summaries linked to customers.",
        "cur_existing_loans": "Declared or synthetic existing credit obligations.",
        "cur_repayments": "Repayment history by loan and due month.",
        "cur_transactions": "Monthly salary credits, debits and cheque bounces.",
        "cur_applications": "Loan request, stage and submission details.",
        "cur_decisions": "AI recommendation and human review outcome fields.",
        "cur_audit_log": "Timestamped actions and case events.",
        "cur_agent_trace": "Ordered agent steps, tool calls, durations and handoffs.",
        "cur_llm_cache": "Cached language output by application and step.",
        "cur_sanctions": "Human-approved sanction, PDF and illustrative KFS data.",
        "cur_disbursements": "Simulated disbursement records; no funds move.",
    },
    "serving": {
        "srv_application_features": "Joined application features such as proposed EMI, FOIR and bureau values.",
    },
}

_CANNED_READ_QUERIES: dict[str, str] = {
    "Recent applications": (
        "SELECT application_id, stage, requested_amount, submitted_at "
        "FROM cur_applications ORDER BY submitted_at DESC LIMIT 10"
    ),
    "Customer income sample": (
        "SELECT customer_id, name, city, net_monthly_income "
        "FROM cur_customers ORDER BY customer_id LIMIT 10"
    ),
    "Document inventory": (
        "SELECT doc_type, COUNT(*) AS document_count "
        "FROM raw_documents GROUP BY doc_type ORDER BY doc_type LIMIT 10"
    ),
}


def explorer_catalog(
    store: SQLiteStore | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return documented RAW, CURATED and SERVING objects with counts and samples."""
    database = _store(store)
    with database.connection() as connection:
        objects = {
            row["name"]: row["type"]
            for row in connection.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        catalog: dict[str, list[dict[str, Any]]] = {}
        for layer, descriptions in _EXPLORER_OBJECTS.items():
            catalog[layer] = []
            for name, description in descriptions.items():
                if name not in objects:
                    catalog[layer].append(
                        {
                            "name": name,
                            "description": description,
                            "row_count": 0,
                            "sample": pd.DataFrame(),
                        }
                    )
                    continue
                quoted_name = '"' + name.replace('"', '""') + '"'
                count = connection.execute(
                    f"SELECT COUNT(*) FROM {quoted_name}"
                ).fetchone()[0]
                sample = pd.read_sql_query(
                    f"SELECT * FROM {quoted_name} LIMIT 5",
                    connection,
                )
                catalog[layer].append(
                    {
                        "name": name,
                        "description": description,
                        "row_count": int(count),
                        "sample": sample,
                    }
                )
    return catalog


def validate_read_only_select(sql: str) -> str:
    """Validate a single SELECT statement and clamp its explicit row limit."""
    import re

    statement = sql.strip()
    if statement.endswith(";"):
        statement = statement[:-1].rstrip()
    if not statement or not re.match(r"(?is)^SELECT\b", statement):
        raise ValueError("Only a single SELECT statement is allowed.")
    if ";" in statement or "--" in statement or "/*" in statement:
        raise ValueError("Comments and multiple SQL statements are not allowed.")
    if re.search(
        r"(?i)\b(INSERT|UPDATE|DELETE|REPLACE|DROP|ALTER|CREATE|ATTACH|DETACH|"
        r"PRAGMA|VACUUM|REINDEX|TRIGGER)\b",
        statement,
    ):
        raise ValueError("Only read-only SELECT queries are allowed.")
    limit_match = re.search(r"(?i)\bLIMIT\s+(\d+)\s*$", statement)
    if not limit_match:
        return f"{statement} LIMIT 10"
    limit = min(int(limit_match.group(1)), 10)
    return f"{statement[:limit_match.start()]}LIMIT {limit}"


def run_canned_read_query(
    name: str,
    store: SQLiteStore | None = None,
) -> pd.DataFrame:
    """Run one allow-listed SELECT query with a read-only SQLite connection."""
    if name not in _CANNED_READ_QUERIES:
        raise ValueError(f"Unknown canned query: {name}")
    sql = validate_read_only_select(_CANNED_READ_QUERIES[name])
    database = _store(store)
    with database.connection() as connection:
        connection.execute("PRAGMA query_only = ON")
        return pd.read_sql_query(sql, connection)
