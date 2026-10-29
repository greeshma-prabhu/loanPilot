"""SQLite schema for the RAW, CURATED, and SERVING data layers."""

from loanpilot.data.store import SQLiteStore

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS raw_library_documents (
    document_id TEXT PRIMARY KEY,
    original_filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    processing_status TEXT NOT NULL
        CHECK (processing_status IN ('Uploaded', 'Processed', 'Failed')),
    extracted_text TEXT NOT NULL DEFAULT '',
    processing_error TEXT NOT NULL DEFAULT '',
    summary_status TEXT NOT NULL DEFAULT 'Not requested',
    summary_method TEXT NOT NULL DEFAULT '',
    summary_version INTEGER NOT NULL DEFAULT 0,
    summary_headline TEXT NOT NULL DEFAULT '',
    summary_text TEXT NOT NULL DEFAULT '',
    summary_error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS raw_documents (
    doc_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    text_content TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES cur_applications(application_id)
);
CREATE TABLE IF NOT EXISTS raw_bureau_responses (
    application_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES cur_applications(application_id)
);
CREATE TABLE IF NOT EXISTS raw_kyc_responses (
    application_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES cur_applications(application_id)
);
CREATE TABLE IF NOT EXISTS raw_policy_docs (
    policy_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    clause_id TEXT NOT NULL,
    text TEXT NOT NULL,
    version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cur_customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dob TEXT NOT NULL,
    age INTEGER NOT NULL,
    city TEXT NOT NULL,
    employer TEXT NOT NULL,
    employment_type TEXT NOT NULL,
    current_tenure_months INTEGER NOT NULL,
    total_experience_months INTEGER NOT NULL,
    net_monthly_income REAL NOT NULL,
    pan_demo_id TEXT NOT NULL UNIQUE,
    kyc_status TEXT NOT NULL,
    relationship_since TEXT NOT NULL,
    mobile TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cur_accounts (
    account_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    type TEXT NOT NULL,
    avg_monthly_balance REAL NOT NULL,
    opened_on TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES cur_customers(customer_id)
);
CREATE TABLE IF NOT EXISTS cur_existing_loans (
    loan_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    product TEXT NOT NULL,
    sanctioned_amount REAL NOT NULL,
    emi REAL NOT NULL,
    outstanding REAL NOT NULL,
    tenure_remaining_months INTEGER NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES cur_customers(customer_id)
);
CREATE TABLE IF NOT EXISTS cur_repayments (
    loan_id TEXT NOT NULL,
    due_month TEXT NOT NULL,
    due_date TEXT NOT NULL,
    paid_date TEXT,
    days_past_due INTEGER NOT NULL,
    PRIMARY KEY (loan_id, due_month),
    FOREIGN KEY (loan_id) REFERENCES cur_existing_loans(loan_id)
);
CREATE TABLE IF NOT EXISTS cur_transactions (
    customer_id TEXT NOT NULL,
    month TEXT NOT NULL,
    salary_credit REAL NOT NULL,
    total_debits REAL NOT NULL,
    cheque_bounces INTEGER NOT NULL,
    PRIMARY KEY (customer_id, month),
    FOREIGN KEY (customer_id) REFERENCES cur_customers(customer_id)
);
CREATE TABLE IF NOT EXISTS cur_applications (
    application_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    requested_amount REAL NOT NULL,
    tenure_months INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    channel TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    stage TEXT NOT NULL,
    persona_key TEXT,
    owner TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (customer_id) REFERENCES cur_customers(customer_id)
);
CREATE TABLE IF NOT EXISTS cur_decisions (
    application_id TEXT PRIMARY KEY,
    ai_recommendation TEXT NOT NULL,
    ai_reasons_json TEXT NOT NULL,
    human_decision TEXT,
    human_reason TEXT,
    is_override INTEGER NOT NULL DEFAULT 0,
    decided_by TEXT,
    decided_at TEXT,
    FOREIGN KEY (application_id) REFERENCES cur_applications(application_id)
);
CREATE TABLE IF NOT EXISTS cur_audit_log (
    event_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES cur_applications(application_id)
);
CREATE TABLE IF NOT EXISTS cur_agent_trace (
    application_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step_no INTEGER NOT NULL,
    agent TEXT NOT NULL,
    tool_calls_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    mode TEXT NOT NULL,
    handoff TEXT NOT NULL,
    PRIMARY KEY (application_id, run_id, step_no),
    FOREIGN KEY (application_id) REFERENCES cur_applications(application_id)
);
CREATE TABLE IF NOT EXISTS cur_llm_cache (
    application_id TEXT NOT NULL,
    step TEXT NOT NULL,
    mode TEXT NOT NULL,
    response_json TEXT NOT NULL,
    cached_at TEXT NOT NULL,
    PRIMARY KEY (application_id, step),
    FOREIGN KEY (application_id) REFERENCES cur_applications(application_id)
);
CREATE TABLE IF NOT EXISTS cur_sanctions (
    application_id TEXT PRIMARY KEY,
    sanction_ref TEXT NOT NULL UNIQUE,
    approved_amount REAL NOT NULL,
    tenure_months INTEGER NOT NULL,
    rate REAL NOT NULL,
    emi REAL NOT NULL,
    conditions_json TEXT NOT NULL,
    letter_path TEXT NOT NULL,
    kfs_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES cur_applications(application_id)
);
CREATE TABLE IF NOT EXISTS cur_disbursements (
    application_id TEXT PRIMARY KEY,
    disbursement_ref TEXT NOT NULL UNIQUE,
    gross_amount REAL NOT NULL,
    fees REAL NOT NULL,
    net_amount REAL NOT NULL,
    disbursed_at TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode = 'simulated'),
    FOREIGN KEY (application_id) REFERENCES cur_applications(application_id)
);
CREATE TABLE IF NOT EXISTS demo_seed_markers (
    seed_name TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cur_applications_customer
    ON cur_applications(customer_id);
CREATE INDEX IF NOT EXISTS idx_cur_agent_trace_run
    ON cur_agent_trace(application_id, run_id, step_no);
CREATE INDEX IF NOT EXISTS idx_cur_existing_loans_customer
    ON cur_existing_loans(customer_id);
CREATE INDEX IF NOT EXISTS idx_cur_repayments_due_month
    ON cur_repayments(due_month);
CREATE VIEW IF NOT EXISTS srv_application_features AS
WITH bureau AS (
    SELECT application_id,
           json_extract(payload_json, '$.score') AS bureau_score,
           COALESCE(json_extract(payload_json, '$.enquiries_6m'), 0) AS enquiries_6m
    FROM raw_bureau_responses
),
repayment AS (
    SELECT l.customer_id, MAX(r.days_past_due) AS max_dpd_24m
    FROM cur_existing_loans l
    JOIN cur_repayments r ON r.loan_id = l.loan_id
    GROUP BY l.customer_id
),
salary AS (
    SELECT customer_id, AVG(salary_credit) AS salary_credit_avg_6m
    FROM cur_transactions
    GROUP BY customer_id
),
document_flags AS (
    SELECT application_id,
           COUNT(*) AS document_count,
           GROUP_CONCAT(doc_type, ',') AS document_types
    FROM raw_documents
    GROUP BY application_id
)
SELECT a.application_id,
       c.net_monthly_income AS income,
       COALESCE((
           SELECT SUM(l.emi)
           FROM cur_existing_loans l
           WHERE l.customer_id = c.customer_id AND l.status = 'Active'
       ), 0) AS existing_emi_total,
       a.requested_amount * (
           (CASE
               WHEN b.bureau_score >= 750 THEN 0.115
               WHEN b.bureau_score >= 700 THEN 0.135
               ELSE 0.16
           END / 12.0) *
           POWER(1.0 + (CASE
               WHEN b.bureau_score >= 750 THEN 0.115
               WHEN b.bureau_score >= 700 THEN 0.135
               ELSE 0.16
           END / 12.0), a.tenure_months)
       ) / (
           POWER(1.0 + (CASE
               WHEN b.bureau_score >= 750 THEN 0.115
               WHEN b.bureau_score >= 700 THEN 0.135
               ELSE 0.16
           END / 12.0), a.tenure_months) - 1.0
       ) AS proposed_emi,
       (
           COALESCE((
               SELECT SUM(l.emi)
               FROM cur_existing_loans l
               WHERE l.customer_id = c.customer_id AND l.status = 'Active'
           ), 0) +
           a.requested_amount * (
               (CASE
                   WHEN b.bureau_score >= 750 THEN 0.115
                   WHEN b.bureau_score >= 700 THEN 0.135
                   ELSE 0.16
               END / 12.0) *
               POWER(1.0 + (CASE
                   WHEN b.bureau_score >= 750 THEN 0.115
                   WHEN b.bureau_score >= 700 THEN 0.135
                   ELSE 0.16
               END / 12.0), a.tenure_months)
           ) / (
               POWER(1.0 + (CASE
                   WHEN b.bureau_score >= 750 THEN 0.115
                   WHEN b.bureau_score >= 700 THEN 0.135
                   ELSE 0.16
               END / 12.0), a.tenure_months) - 1.0
           )
       ) / NULLIF(c.net_monthly_income, 0) AS foir,
       b.bureau_score,
       COALESCE(r.max_dpd_24m, 0) AS max_dpd_24m,
       COALESCE(b.enquiries_6m, 0) AS enquiries_6m,
       COALESCE(s.salary_credit_avg_6m, 0) AS salary_credit_avg_6m,
       CASE WHEN d.document_count IS NULL THEN 'missing'
            ELSE d.document_types END AS document_flags
FROM cur_applications a
JOIN cur_customers c ON c.customer_id = a.customer_id
LEFT JOIN bureau b ON b.application_id = a.application_id
LEFT JOIN repayment r ON r.customer_id = c.customer_id
LEFT JOIN salary s ON s.customer_id = c.customer_id
LEFT JOIN document_flags d ON d.application_id = a.application_id;
"""


def create_schema(store: SQLiteStore) -> None:
    """Create all demo data tables, indexes, and the serving view."""
    with store.connection() as connection:
        connection.executescript(SCHEMA_SQL)
        customer_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(cur_customers)")
        }
        if "mobile" not in customer_columns:
            connection.execute(
                "ALTER TABLE cur_customers ADD COLUMN mobile TEXT NOT NULL DEFAULT ''"
            )
        application_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(cur_applications)")
        }
        if "owner" not in application_columns:
            connection.execute(
                "ALTER TABLE cur_applications ADD COLUMN owner TEXT NOT NULL DEFAULT ''"
            )
        document_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(raw_library_documents)")
        }
        for column, definition in (
            ("summary_status", "TEXT NOT NULL DEFAULT 'Not requested'"),
            ("summary_method", "TEXT NOT NULL DEFAULT ''"),
            ("summary_version", "INTEGER NOT NULL DEFAULT 0"),
            ("summary_headline", "TEXT NOT NULL DEFAULT ''"),
            ("summary_text", "TEXT NOT NULL DEFAULT ''"),
            ("summary_error", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in document_columns:
                connection.execute(
                    f"ALTER TABLE raw_library_documents ADD COLUMN {column} {definition}"
                )
