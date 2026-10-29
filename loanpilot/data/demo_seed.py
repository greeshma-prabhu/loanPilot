"""Idempotent persistence for the ten synthetic Overview demo applications."""

from datetime import date, datetime, timedelta
import json

from loanpilot.data.store import SQLiteStore

_SEED_NAME = "overview_synthetic_applications"
_SEED_VERSION = 1
_RECORDS = (
    {
        "name": "Kavya Iyer",
        "age": 34,
        "city": "Bengaluru",
        "employer": "Cedarline Services",
        "employment_type": "Salaried",
        "income": 52000,
        "existing_emi": 18000,
        "amount": 300000,
        "tenure": 36,
        "purpose": "Home improvement",
        "stage": "Human Review",
        "recommendation": "Refer",
        "risk_band": "High",
        "attention_priority": "High",
        "attention_reason": "High stated monthly obligations need an affordability review.",
        "scenario": "Affordability review",
    },
    {
        "name": "Rohan Das",
        "age": 39,
        "city": "Pune",
        "employer": "Northstar Design Collective",
        "employment_type": "Salaried",
        "income": 85000,
        "existing_emi": 9000,
        "amount": 450000,
        "tenure": 48,
        "purpose": "Education",
        "stage": "Human Review",
        "recommendation": "Refer",
        "risk_band": "Medium",
        "attention_priority": "Medium",
        "attention_reason": "Synthetic scenario: declared income needs document reconciliation; no document is attached.",
        "scenario": "Income reconciliation",
    },
    {
        "name": "Nisha Shah",
        "age": 29,
        "city": "Ahmedabad",
        "employer": "Orchid Data Works",
        "employment_type": "Salaried",
        "income": 64000,
        "existing_emi": 7000,
        "amount": 250000,
        "tenure": 36,
        "purpose": "Travel",
        "stage": "Awaiting documents",
        "recommendation": "Refer",
        "risk_band": "Medium",
        "attention_priority": "High",
        "attention_reason": "Synthetic scenario: income proof is not present in this demo record.",
        "scenario": "Income proof needed",
    },
    {
        "name": "Arjun Rao",
        "age": 42,
        "city": "Chennai",
        "employer": "Blue Banyan Digital",
        "employment_type": "Self-employed",
        "income": 70000,
        "existing_emi": 12000,
        "amount": 400000,
        "tenure": 48,
        "purpose": "Business expenses",
        "stage": "Awaiting documents",
        "recommendation": "Refer",
        "risk_band": "Medium",
        "attention_priority": "High",
        "attention_reason": "Synthetic scenario: identity review is pending; no KYC provider was contacted.",
        "scenario": "KYC review pending",
    },
    {
        "name": "Amara Nair",
        "age": 26,
        "city": "Kochi",
        "employer": "Evergreen Process Works",
        "employment_type": "Salaried",
        "income": 78000,
        "existing_emi": 5000,
        "amount": 350000,
        "tenure": 36,
        "purpose": "Medical expenses",
        "stage": "Human Review",
        "recommendation": "Refer",
        "risk_band": "Medium",
        "attention_priority": "Medium",
        "attention_reason": "Credit history is not represented in this demo record; manual review scenario.",
        "scenario": "Credit history review",
    },
    {
        "name": "Dev Balan",
        "age": 37,
        "city": "Kolkata",
        "employer": "Silver Fern Consulting",
        "employment_type": "Salaried",
        "income": 60000,
        "existing_emi": 8000,
        "amount": 200000,
        "tenure": 36,
        "purpose": "Education",
        "stage": "Human Review",
        "recommendation": "Approve",
        "risk_band": "Low",
        "attention_priority": "Medium",
        "attention_reason": "Illustrative recommendation is awaiting a human decision.",
        "scenario": "Human decision pending",
    },
    {
        "name": "Maya Menon",
        "age": 31,
        "city": "Hyderabad",
        "employer": "Juniper Cloud Labs",
        "employment_type": "Salaried",
        "income": 72000,
        "existing_emi": 6000,
        "amount": 280000,
        "tenure": 36,
        "purpose": "Travel",
        "stage": "Awaiting assessment",
        "recommendation": "Not assessed",
        "risk_band": "Not assessed",
        "attention_priority": "Medium",
        "attention_reason": "Recently submitted synthetic example awaiting initial assessment.",
        "scenario": "Initial assessment pending",
    },
    {
        "name": "Priya Ghosh",
        "age": 33,
        "city": "Mumbai",
        "employer": "Cobalt Harbor Systems",
        "employment_type": "Salaried",
        "income": 110000,
        "existing_emi": 10000,
        "amount": 300000,
        "tenure": 36,
        "purpose": "Home improvement",
        "stage": "Approved",
        "recommendation": "Approve",
        "risk_band": "Low",
        "attention_priority": "",
        "attention_reason": "",
        "scenario": "Illustrative approved example",
    },
    {
        "name": "Varun Mishra",
        "age": 45,
        "city": "Lucknow",
        "employer": "Sunrise Logistics Network",
        "employment_type": "Salaried",
        "income": 45000,
        "existing_emi": 14000,
        "amount": 420000,
        "tenure": 36,
        "purpose": "Other",
        "stage": "Rejected",
        "recommendation": "Decline",
        "risk_band": "High",
        "attention_priority": "",
        "attention_reason": "",
        "scenario": "Illustrative rejected example",
    },
    {
        "name": "Ira Kapoor",
        "age": 28,
        "city": "Jaipur",
        "employer": "Mosaic Retail Services",
        "employment_type": "Self-employed",
        "income": 92000,
        "existing_emi": 11000,
        "amount": 500000,
        "tenure": 48,
        "purpose": "Home improvement",
        "stage": "Pending",
        "recommendation": "Not assessed",
        "risk_band": "Not assessed",
        "attention_priority": "",
        "attention_reason": "",
        "scenario": "Pending synthetic example",
    },
)


def _record_dates(anchor: date) -> list[str]:
    """Create stable submission dates within the current portfolio year."""
    offsets = (2, 5, 8, 12, 16, 21, 28, 38, 52, 74)
    return [
        datetime.combine(anchor - timedelta(days=offset), datetime.min.time()).isoformat(
            timespec="seconds"
        )
        for offset in offsets
    ]


def _customer_age_date(anchor: date, age: int) -> str:
    """Derive a synthetic birth date without relying on fabricated KYC data."""
    year = anchor.year - age
    try:
        return anchor.replace(year=year).isoformat()
    except ValueError:
        return anchor.replace(year=year, day=28).isoformat()


def seed_synthetic_applications(store: SQLiteStore) -> int:
    """Insert or safely reconcile exactly ten stable synthetic application rows.

    Existing application and customer IDs are validated before use; a collision
    with a non-seed record raises rather than overwriting user data.
    """
    inserted = 0
    anchor = date.today()
    with store.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for index, (record, submitted_at) in enumerate(
            zip(_RECORDS, _record_dates(anchor), strict=True),
            start=1,
        ):
            suffix = f"{index:03d}"
            application_id = f"APP-SYNTH-{suffix}"
            customer_id = f"C-SYNTH-DEMO-{suffix}"
            pan_demo_id = f"DEMO-SYNTH-PAN-{suffix}"
            existing_customer = connection.execute(
                "SELECT name, pan_demo_id FROM cur_customers WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
            if existing_customer and (
                existing_customer["name"] != record["name"]
                or existing_customer["pan_demo_id"] != pan_demo_id
            ):
                raise RuntimeError(
                    f"Synthetic seed customer ID collision: {customer_id}"
                )
            if not existing_customer:
                connection.execute(
                    """
                    INSERT INTO cur_customers (
                        customer_id, name, dob, age, city, employer,
                        employment_type, current_tenure_months,
                        total_experience_months, net_monthly_income,
                        pan_demo_id, kyc_status, relationship_since
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        customer_id,
                        record["name"],
                        _customer_age_date(anchor, record["age"]),
                        record["age"],
                        record["city"],
                        record["employer"],
                        record["employment_type"],
                        24,
                        72,
                        record["income"],
                        pan_demo_id,
                        "Not checked (synthetic)",
                        "",
                    ),
                )

            existing_application = connection.execute(
                "SELECT customer_id, persona_key FROM cur_applications "
                "WHERE application_id = ?",
                (application_id,),
            ).fetchone()
            if existing_application and (
                existing_application["customer_id"] != customer_id
                or existing_application["persona_key"] != "SYNTHETIC-DEMO"
            ):
                raise RuntimeError(
                    f"Synthetic seed application ID collision: {application_id}"
                )
            if not existing_application:
                connection.execute(
                    """
                    INSERT INTO cur_applications (
                        application_id, customer_id, requested_amount,
                        tenure_months, purpose, channel, submitted_at, stage,
                        persona_key, owner
                    ) VALUES (?, ?, ?, ?, ?, 'Synthetic demo', ?, ?, ?, ?)
                    """,
                    (
                        application_id,
                        customer_id,
                        record["amount"],
                        record["tenure"],
                        record["purpose"],
                        submitted_at,
                        record["stage"],
                        "SYNTHETIC-DEMO",
                        "Synthetic demo",
                    ),
                )
                inserted += 1

            if record["existing_emi"]:
                loan_id = f"LOAN-SYNTH-DEMO-{suffix}"
                existing_loan = connection.execute(
                    "SELECT customer_id FROM cur_existing_loans WHERE loan_id = ?",
                    (loan_id,),
                ).fetchone()
                if existing_loan and existing_loan["customer_id"] != customer_id:
                    raise RuntimeError(f"Synthetic seed loan ID collision: {loan_id}")
                if not existing_loan:
                    connection.execute(
                        """
                        INSERT INTO cur_existing_loans (
                            loan_id, customer_id, product, sanctioned_amount,
                            emi, outstanding, tenure_remaining_months, status
                        ) VALUES (?, ?, 'Synthetic demo obligation', ?, ?, ?, 18, 'Active')
                        """,
                        (
                            loan_id,
                            customer_id,
                            record["existing_emi"] * 18,
                            record["existing_emi"],
                            record["existing_emi"] * 9,
                        ),
                    )

            reasons = {
                "synthetic": True,
                "demo_label": "Synthetic demo record — not an actual assessment or decision.",
                "scenario": record["scenario"],
                "risk_band": record["risk_band"],
                "attention_priority": record["attention_priority"],
                "attention_reason": record["attention_reason"],
                "reasons_for": [],
                "reasons_against": [],
                "conditions": [],
            }
            decision = connection.execute(
                "SELECT application_id FROM cur_decisions WHERE application_id = ?",
                (application_id,),
            ).fetchone()
            if not decision:
                is_final = record["stage"] in {"Approved", "Rejected"}
                human_decision = (
                    "Approve"
                    if record["stage"] == "Approved"
                    else "Reject"
                    if record["stage"] == "Rejected"
                    else None
                )
                decided_at = (
                    (date.fromisoformat(submitted_at[:10]) + timedelta(days=1)).isoformat()
                    if is_final
                    else None
                )
                connection.execute(
                    """
                    INSERT INTO cur_decisions (
                        application_id, ai_recommendation, ai_reasons_json,
                        human_decision, human_reason, is_override, decided_by,
                        decided_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        application_id,
                        record["recommendation"],
                        json.dumps(reasons, sort_keys=True),
                        human_decision,
                        "Synthetic illustrative outcome; not an actual bank decision."
                        if is_final
                        else None,
                        "Synthetic demo" if is_final else None,
                        decided_at,
                    ),
                )

        marker = connection.execute(
            "SELECT version FROM demo_seed_markers WHERE seed_name = ?",
            (_SEED_NAME,),
        ).fetchone()
        if marker is None:
            connection.execute(
                "INSERT INTO demo_seed_markers (seed_name, version, applied_at) "
                "VALUES (?, ?, ?)",
                (_SEED_NAME, _SEED_VERSION, datetime.now().isoformat(timespec="seconds")),
            )
        elif marker["version"] < _SEED_VERSION:
            connection.execute(
                "UPDATE demo_seed_markers SET version = ?, applied_at = ? "
                "WHERE seed_name = ?",
                (
                    _SEED_VERSION,
                    datetime.now().isoformat(timespec="seconds"),
                    _SEED_NAME,
                ),
            )
    return inserted
