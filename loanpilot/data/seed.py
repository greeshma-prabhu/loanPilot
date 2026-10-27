"""Deterministic generator for LoanPilot's synthetic demo dataset."""

import argparse
from datetime import date, datetime, time, timedelta
import json
import math
import random
from typing import Any

from loanpilot.config import DATABASE_PATH
from loanpilot.data.policy import seed_policy_docs
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore

SEED = 42
AS_OF_DATE = date(2026, 10, 1)
PERSONAS: dict[str, dict[str, Any]] = {
    "PERSONA-1": {
        "name": "Priya Menon",
        "age": 31,
        "city": "Bengaluru",
        "employer": "Aarambh Technologies",
        "tenure": 60,
        "experience": 108,
        "income": 95000,
        "amount": 400000,
        "term": 36,
        "score": 782,
        "foir": 0.27,
        "salary_factor": 1.0,
    },
    "PERSONA-2": {
        "name": "Rahul Verma",
        "age": 38,
        "city": "Pune",
        "employer": "Western Operations Services",
        "tenure": 36,
        "experience": 168,
        "income": 60000,
        "amount": 350000,
        "term": 48,
        "score": 712,
        "foir": 0.47,
        "salary_factor": 0.94,
        "dpd": 30,
    },
    "PERSONA-3": {
        "name": "Imran Sheikh",
        "age": 29,
        "city": "Hyderabad",
        "employer": "Deccan Sales Network",
        "tenure": 24,
        "experience": 72,
        "income": 45000,
        "amount": 300000,
        "term": 36,
        "score": 668,
        "foir": 0.59,
        "salary_factor": 1.0,
    },
    "PERSONA-4": {
        "name": "Anita Rao",
        "age": 35,
        "city": "Chennai",
        "employer": "Aarambh Technologies Pvt Ltd",
        "tenure": 48,
        "experience": 132,
        "income": 82000,
        "amount": 500000,
        "term": 48,
        "score": 745,
        "salary_factor": 0.66,
    },
    "PERSONA-5": {
        "name": "Karthik Nair",
        "age": 24,
        "city": "Kochi",
        "employer": "Coastal Analytics",
        "tenure": 8,
        "experience": 16,
        "income": 38000,
        "amount": 100000,
        "term": 24,
        "score": None,
        "foir": None,
        "salary_factor": 1.0,
    },
    "PERSONA-6": {
        "name": "Meera Iyer",
        "age": 42,
        "city": "Mumbai",
        "employer": "Western Financial Services",
        "tenure": 5,
        "experience": 137,
        "income": 72000,
        "amount": 450000,
        "term": 48,
        "score": 706,
        "foir": 0.38,
        "salary_factor": 1.0,
    },
}

_FIRST_NAMES = [
    "Aadhya", "Aarav", "Aditi", "Advait", "Akash", "Amara", "Ananya", "Arjun",
    "Bhavna", "Charan", "Deepa", "Dev", "Esha", "Farah", "Gauri", "Hari",
    "Ira", "Ishaan", "Jaya", "Kabir", "Kavya", "Kiran", "Lakshmi", "Manav",
    "Maya", "Neel", "Nisha", "Ojas", "Pallavi", "Parth", "Rhea", "Rohan",
    "Sana", "Sanjay", "Tara", "Uma", "Varun", "Vidya", "Yash", "Zoya",
]
_LAST_NAMES = [
    "Acharya", "Balan", "Basu", "Bhat", "Chandra", "Das", "Desai", "Ghosh",
    "Gopal", "Iyer", "Jain", "Joshi", "Kapoor", "Khan", "Kulkarni", "Menon",
    "Mishra", "Mukherjee", "Nair", "Pillai", "Prasad", "Rao", "Reddy", "Saha",
    "Shah", "Sharma", "Singh", "Srinivasan", "Verma", "Yadav",
]
_CITIES = [
    "Ahmedabad", "Bengaluru", "Bhopal", "Bhubaneswar", "Chandigarh", "Chennai",
    "Coimbatore", "Delhi", "Hyderabad", "Indore", "Jaipur", "Kochi", "Kolkata",
    "Lucknow", "Mumbai", "Nagpur", "Pune", "Surat", "Thiruvananthapuram",
    "Visakhapatnam",
]
_EMPLOYERS = [
    "Blue Banyan Digital", "Cedarline Services", "Cobalt Harbor Systems",
    "Evergreen Process Works", "Juniper Cloud Labs", "Lakeview Support Group",
    "Mosaic Retail Services", "Northstar Design Collective", "Orchid Data Works",
    "Silver Fern Consulting", "Sunrise Logistics Network", "Verdant Office Systems",
]
_PURPOSES = ["Home improvement", "Medical expenses", "Education", "Travel", "Other"]


def calculate_emi(principal: float, annual_rate: float, months: int) -> float:
    """Calculate an EMI using the standard monthly reducing-balance formula."""
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        return principal / months
    factor = (1 + monthly_rate) ** months
    return principal * monthly_rate * factor / (factor - 1)


def _rate_for_score(score: int | None) -> float:
    """Choose the illustrative pricing rate for a known score band."""
    if score is not None and score >= 750:
        return 0.115
    if score is not None and score >= 700:
        return 0.135
    return 0.16


def _inverse_loan_amount(emi: float, annual_rate: float, months: int) -> float:
    """Calculate principal for a target EMI at the given reducing-balance rate."""
    monthly_rate = annual_rate / 12
    factor = (1 + monthly_rate) ** months
    return emi * (factor - 1) / (monthly_rate * factor)


def _date_months_before(anchor: date, months: int) -> date:
    """Return the first day of a month a fixed number of months before anchor."""
    index = anchor.year * 12 + anchor.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def _drop_schema(store: SQLiteStore) -> None:
    """Remove demo tables and views before a full deterministic reset."""
    with store.connection() as connection:
        views = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view'"
        ).fetchall()
        for row in views:
            connection.execute(f'DROP VIEW IF EXISTS "{row["name"]}"')
        tables = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        connection.execute("PRAGMA foreign_keys = OFF")
        for row in tables:
            connection.execute(f'DROP TABLE IF EXISTS "{row["name"]}"')
        connection.execute("PRAGMA foreign_keys = ON")


def _persona_emi(persona: dict[str, Any]) -> float:
    """Return the proposed EMI at the persona's score-based annual rate."""
    return calculate_emi(
        persona["amount"],
        _rate_for_score(persona["score"]),
        persona["term"],
    )


def _generate_customers(rng: random.Random) -> tuple[list[tuple[Any, ...]], dict[str, dict]]:
    """Generate 500 customers, including the six fixed demo personas."""
    rows = []
    customers: dict[str, dict] = {}
    persona_keys = list(PERSONAS)
    combinations = (
        (first, last)
        for first in _FIRST_NAMES
        for last in _LAST_NAMES
    )
    random_names = iter(combinations)
    for number in range(1, 501):
        if number <= len(persona_keys):
            persona_key = persona_keys[number - 1]
            persona = PERSONAS[persona_key]
            customer_id = f"CUST-{persona_key}"
            age = persona["age"]
            dob = date(AS_OF_DATE.year - age, AS_OF_DATE.month, AS_OF_DATE.day)
            details = {
                **persona,
                "customer_id": customer_id,
                "persona_key": persona_key,
                "dob": dob.isoformat(),
                "name": persona["name"],
            }
        else:
            customer_id = f"CUST-{number:03d}"
            first, last = next(random_names)
            age = rng.randint(22, 58)
            dob = date(AS_OF_DATE.year - age, AS_OF_DATE.month, 1)
            income = round(
                min(200000, max(25000, rng.lognormvariate(math.log(65000), 0.55))),
                2,
            )
            tenure = rng.randint(6, min(144, (age - 18) * 12))
            experience = rng.randint(tenure, (age - 18) * 12)
            details = {
                "customer_id": customer_id,
                "persona_key": None,
                "name": f"{first} {last}",
                "age": age,
                "dob": dob.isoformat(),
                "city": rng.choice(_CITIES),
                "employer": rng.choice(_EMPLOYERS),
                "tenure": tenure,
                "experience": experience,
                "income": income,
                "salary_factor": 1.0,
                "score": None,
            }
        if details["persona_key"] is None:
            details["city"] = details.get("city") or rng.choice(_CITIES)
            details["employer"] = details.get("employer") or rng.choice(_EMPLOYERS)
        if details["persona_key"] == "PERSONA-6":
            relationship_since = date(AS_OF_DATE.year - 8, AS_OF_DATE.month, 1)
            balance = 180000.0
        else:
            relationship_months = rng.randint(
                12, min(180, (details["age"] - 18) * 12)
            )
            relationship_since = _date_months_before(
                AS_OF_DATE, relationship_months
            )
            balance = round(rng.uniform(10000, 160000), 2)
        pan_demo_id = f"DEMO{number:08d}"
        row = (
            customer_id,
            details["name"],
            details["dob"],
            details["age"],
            details["city"],
            details["employer"],
            "Salaried",
            details["tenure"],
            details["experience"],
            details["income"],
            pan_demo_id,
            "Verified",
            relationship_since.isoformat(),
        )
        rows.append(row)
        details["pan_demo_id"] = pan_demo_id
        details["relationship_since"] = relationship_since.isoformat()
        details["balance"] = balance
        customers[customer_id] = details
    return rows, customers


def _generate_credit_history(
    customers: dict[str, dict],
    rng: random.Random,
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]], dict[str, dict]]:
    """Generate accounts, active loans, repayment history, and bureau profiles."""
    account_rows = []
    loan_rows = []
    repayment_rows = []
    profiles: dict[str, dict] = {}
    for customer_number, (customer_id, customer) in enumerate(
        customers.items(), start=1
    ):
        account_rows.append(
            (
                f"ACCT-{customer_number:04d}",
                customer_id,
                "Savings",
                customer["balance"],
                _date_months_before(AS_OF_DATE, rng.randint(12, 120)).isoformat(),
            )
        )
        persona_key = customer["persona_key"]
        if persona_key == "PERSONA-5":
            loan_count = 0
        elif persona_key:
            loan_count = 1
        else:
            loan_count = rng.randint(0, 3)
        customer_loans = []
        if persona_key and persona_key != "PERSONA-5":
            if persona_key == "PERSONA-4":
                target_emi = 20000.0
            else:
                target_emi = (
                    customer["foir"] * customer["income"]
                    - _persona_emi(customer)
                )
            loan_term = 48
            loan_rate = 0.12
            principal = round(_inverse_loan_amount(target_emi, loan_rate, loan_term), 2)
            customer_loans.append((principal, calculate_emi(principal, loan_rate, loan_term)))
        else:
            for _ in range(loan_count):
                term = rng.choice((24, 36, 48, 60))
                annual_rate = rng.choice((0.105, 0.12, 0.145, 0.17))
                target_emi = customer["income"] * rng.uniform(0.035, 0.095)
                principal = round(_inverse_loan_amount(target_emi, annual_rate, term), 2)
                customer_loans.append(
                    (principal, calculate_emi(principal, annual_rate, term))
                )
        all_dpd: list[int] = []
        utilization_balance = 0.0
        sanctioned_total = 0.0
        for loan_index, (principal, loan_emi) in enumerate(customer_loans, start=1):
            loan_id = f"LOAN-{customer_id}-{loan_index}"
            outstanding = round(principal * rng.uniform(0.2, 0.78), 2)
            remaining = rng.randint(1, 48)
            loan_rows.append(
                (
                    loan_id,
                    customer_id,
                    rng.choice(("Personal Loan", "Consumer Loan", "Two-wheeler Loan")),
                    principal,
                    loan_emi,
                    outstanding,
                    remaining,
                    "Active",
                )
            )
            sanctioned_total += principal
            utilization_balance += outstanding
            history_months = rng.randint(12, 24)
            for offset in range(history_months, 0, -1):
                due = _date_months_before(AS_OF_DATE, offset)
                if persona_key == "PERSONA-2" and offset == 14:
                    dpd = 30
                elif persona_key:
                    dpd = 0
                elif rng.random() < 0.045:
                    dpd = rng.choice((1, 7, 15, 30, 60, 90, 120))
                else:
                    dpd = 0
                all_dpd.append(dpd)
                paid_date = due + timedelta(days=dpd)
                repayment_rows.append(
                    (
                        loan_id,
                        due.strftime("%Y-%m"),
                        due.isoformat(),
                        paid_date.isoformat(),
                        dpd,
                    )
                )
        max_dpd = max(all_dpd, default=0)
        utilization = utilization_balance / sanctioned_total if sanctioned_total else 0.0
        if customer["score"] is not None:
            score = customer["score"]
        elif persona_key == "PERSONA-5":
            score = None
        else:
            score = max(
                300,
                min(
                    900,
                    int(round(850 - max_dpd * 1.7 - utilization * 75 + rng.randint(-12, 12))),
                ),
            )
        profiles[customer_id] = {
            "score": score,
            "max_dpd_24m": max_dpd,
            "active_accounts": loan_count,
            "utilization_pct": round(utilization * 100, 2),
        }
    return account_rows, loan_rows, repayment_rows, profiles


def _generate_transactions(
    customers: dict[str, dict], rng: random.Random
) -> list[tuple[Any, ...]]:
    """Generate six monthly salary-credit and debit aggregates per customer."""
    rows = []
    for customer in customers.values():
        factor = customer["salary_factor"]
        for offset in range(6, 0, -1):
            month = _date_months_before(AS_OF_DATE, offset).strftime("%Y-%m")
            salary_credit = customer["income"] * factor
            if customer["persona_key"] is None:
                salary_credit *= rng.uniform(0.97, 1.03)
            rows.append(
                (
                    customer["customer_id"],
                    month,
                    round(salary_credit, 2),
                    round(customer["income"] * rng.uniform(0.52, 0.92), 2),
                    1 if rng.random() < 0.008 else 0,
                )
            )
    return rows


def _application_bureau(
    profile: dict[str, Any], rng: random.Random
) -> dict[str, Any]:
    """Build the CIBIL-like mock bureau payload for an application."""
    thin_file = profile["score"] is None
    return {
        "provider": "Synthetic bureau simulator",
        "score": None if thin_file else profile["score"],
        "thin_file": thin_file,
        "active_accounts": profile["active_accounts"],
        "enquiries_6m": 0 if thin_file else rng.randint(0, 7),
        "max_dpd_24m": profile["max_dpd_24m"],
        "written_off": bool(
            profile["score"] is not None
            and profile["score"] < 620
            and rng.random() < 0.12
        ),
        "utilization_pct": profile["utilization_pct"],
    }


def _seed_rows(store: SQLiteStore, rng: random.Random) -> None:
    """Populate synthetic customers, credit history, transactions, and applications."""
    customer_rows, customers = _generate_customers(rng)
    account_rows, loan_rows, repayment_rows, profiles = _generate_credit_history(
        customers, rng
    )
    transaction_rows = _generate_transactions(customers, rng)

    store.execute_many(
        "INSERT INTO cur_customers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        customer_rows,
    )
    store.execute_many(
        "INSERT INTO cur_accounts VALUES (?, ?, ?, ?, ?)",
        account_rows,
    )
    store.execute_many(
        "INSERT INTO cur_existing_loans VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        loan_rows,
    )
    store.execute_many(
        "INSERT INTO cur_repayments VALUES (?, ?, ?, ?, ?)",
        repayment_rows,
    )
    store.execute_many(
        "INSERT INTO cur_transactions VALUES (?, ?, ?, ?, ?)",
        transaction_rows,
    )

    app_rows: list[tuple[Any, ...]] = []
    decision_rows: list[tuple[Any, ...]] = []
    bureau_rows: list[tuple[Any, ...]] = []
    kyc_rows: list[tuple[Any, ...]] = []
    audit_rows: list[tuple[Any, ...]] = []
    non_persona_ids = [cid for cid, c in customers.items() if not c["persona_key"]]
    historical_customer_ids = rng.sample(non_persona_ids, 60)
    outcomes = ["Approved"] * 30 + ["Declined"] * 18 + ["Referred"] * 12
    rng.shuffle(outcomes)
    for index, (customer_id, outcome) in enumerate(
        zip(historical_customer_ids, outcomes, strict=True), start=1
    ):
        customer = customers[customer_id]
        application_id = f"APP-HIST-{index:03d}"
        submitted = datetime.combine(
            _date_months_before(AS_OF_DATE, rng.randint(2, 18))
            + timedelta(days=rng.randint(0, 27)),
            time(hour=rng.randint(8, 17), minute=rng.choice((0, 15, 30, 45))),
        )
        rate = _rate_for_score(profiles[customer_id]["score"])
        amount = round(min(customer["income"] * rng.uniform(2, 12), 1200000), -3)
        term = rng.choice((12, 18, 24, 36, 48, 60))
        stage = outcome
        app_rows.append(
            (
                application_id,
                customer_id,
                amount,
                term,
                rng.choice(_PURPOSES),
                rng.choice(("Branch", "Web", "Mobile")),
                submitted.isoformat(timespec="seconds"),
                stage,
                None,
            )
        )
        decision_days = rng.randint(1, 9)
        decided_at = (submitted + timedelta(days=decision_days)).isoformat(timespec="seconds")
        decision_rows.append(
            (
                application_id,
                outcome,
                json.dumps(
                    {"demo_reason": "Synthetic historical outcome", "policy_checks": []},
                    sort_keys=True,
                ),
                outcome,
                "Illustrative human review outcome",
                0,
                "Demo Reviewer",
                decided_at,
            )
        )
        bureau = _application_bureau(profiles[customer_id], rng)
        fetched_at = submitted.isoformat(timespec="seconds")
        bureau_rows.append(
            (application_id, json.dumps(bureau, sort_keys=True), fetched_at)
        )
        kyc_rows.append(
            (
                application_id,
                json.dumps(
                    {
                        "pan_status": "verified",
                        "name_match_score": round(rng.uniform(0.88, 1.0), 2),
                        "aadhaar_demo_id": f"XXXX-XXXX-{index:04d}",
                        "cersai": "not applicable (unsecured)",
                    },
                    sort_keys=True,
                ),
                fetched_at,
            )
        )
        audit_rows.append(
            (
                f"EVT-{application_id}",
                application_id,
                decided_at,
                "Demo Reviewer",
                f"Recorded {outcome.lower()} outcome",
                "Synthetic historical application",
            )
        )

    for persona_key, persona in PERSONAS.items():
        customer_id = f"CUST-{persona_key}"
        application_id = f"APP-{persona_key}"
        submitted_at = datetime(2026, 10, 15, 10, 0, 0) + timedelta(
            days=int(persona_key[-1])
        )
        app_rows.append(
            (
                application_id,
                customer_id,
                persona["amount"],
                persona["term"],
                "Personal expenses",
                "Web",
                submitted_at.isoformat(timespec="seconds"),
                "Submitted",
                persona_key,
            )
        )
        bureau = _application_bureau(profiles[customer_id], rng)
        if persona_key == "PERSONA-2":
            bureau["enquiries_6m"] = 2
        if persona_key == "PERSONA-5":
            bureau["enquiries_6m"] = 0
        bureau_rows.append(
            (
                application_id,
                json.dumps(bureau, sort_keys=True),
                submitted_at.isoformat(timespec="seconds"),
            )
        )
        kyc_rows.append(
            (
                application_id,
                json.dumps(
                    {
                        "pan_status": "verified",
                        "name_match_score": 0.94,
                        "aadhaar_demo_id": f"XXXX-XXXX-{int(persona_key[-1]):04d}",
                        "cersai": "not applicable (unsecured)",
                    },
                    sort_keys=True,
                ),
                submitted_at.isoformat(timespec="seconds"),
            )
        )
        audit_rows.append(
            (
                f"EVT-{application_id}",
                application_id,
                submitted_at.isoformat(timespec="seconds"),
                "Demo Applicant",
                "Submitted application",
                "Synthetic persona application",
            )
        )

    store.execute_many(
        "INSERT INTO cur_applications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", app_rows
    )
    store.execute_many(
        "INSERT INTO raw_bureau_responses VALUES (?, ?, ?)", bureau_rows
    )
    store.execute_many("INSERT INTO raw_kyc_responses VALUES (?, ?, ?)", kyc_rows)
    store.execute_many(
        "INSERT INTO cur_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", decision_rows
    )
    store.execute_many(
        "INSERT INTO cur_audit_log VALUES (?, ?, ?, ?, ?, ?)", audit_rows
    )


def validate_seeded_data(store: SQLiteStore) -> None:
    """Raise an explicit error if key dataset realism and integrity rules fail."""
    customer_count = store.query("SELECT COUNT(*) AS n FROM cur_customers").iloc[0, 0]
    application_count = store.query("SELECT COUNT(*) AS n FROM cur_applications").iloc[0, 0]
    if customer_count != 500 or application_count != 66:
        raise ValueError(
            f"Expected 500 customers and 66 applications; got "
            f"{customer_count} and {application_count}"
        )
    broken_foreign_keys = store.query("PRAGMA foreign_key_check")
    if not broken_foreign_keys.empty:
        raise ValueError("Synthetic seed has broken foreign-key references")
    invalid_income = store.query(
        "SELECT customer_id FROM cur_customers "
        "WHERE net_monthly_income < 25000 OR net_monthly_income > 200000"
    )
    if not invalid_income.empty:
        raise ValueError("Generated salary falls outside the configured income range")
    mismatch = store.query(
        "SELECT c.customer_id FROM cur_customers c "
        "JOIN (SELECT customer_id, AVG(salary_credit) AS avg_salary "
        "      FROM cur_transactions GROUP BY customer_id) t "
        "ON t.customer_id = c.customer_id "
        "WHERE c.customer_id NOT IN "
        "('CUST-PERSONA-2', 'CUST-PERSONA-4') "
        "AND ABS(t.avg_salary - c.net_monthly_income) / c.net_monthly_income > 0.10"
    )
    if not mismatch.empty:
        raise ValueError("Generated salary credits do not match net income")
    persona_features = store.query(
        "SELECT a.persona_key, f.income, f.proposed_emi, f.foir, f.bureau_score, "
        "f.max_dpd_24m FROM srv_application_features f "
        "JOIN cur_applications a USING (application_id) "
        "WHERE a.persona_key IS NOT NULL ORDER BY a.persona_key"
    )
    for row in persona_features.to_dict("records"):
        persona = PERSONAS[row["persona_key"]]
        target_foir = persona.get("foir")
        if target_foir is not None and abs(row["foir"] - target_foir) > 0.015:
            raise ValueError(
                f"{row['persona_key']} FOIR {row['foir']:.4f} misses its target"
            )
        actual_score = row["bureau_score"]
        if persona["score"] is None:
            if actual_score is not None and not math.isnan(actual_score):
                raise ValueError(f"{row['persona_key']} should have a thin bureau file")
        elif actual_score != persona["score"]:
            raise ValueError(f"{row['persona_key']} bureau score does not match target")
    p2 = persona_features.loc[persona_features.persona_key == "PERSONA-2"].iloc[0]
    if p2["max_dpd_24m"] != 30:
        raise ValueError("Persona 2 must have exactly one 30-day late repayment")


def seed_demo_data(
    store: SQLiteStore | None = None,
    *,
    reset: bool = False,
) -> dict[str, int]:
    """Generate the deterministic synthetic dataset and return table counts."""
    store = store or SQLiteStore(DATABASE_PATH)
    if reset:
        _drop_schema(store)
    elif store.table_counts().get("cur_customers", 0):
        raise ValueError("Demo data already exists; pass reset=True to regenerate it")
    create_schema(store)
    _seed_rows(store, random.Random(SEED))
    seed_policy_docs(store)
    from loanpilot.data.documents import seed_persona_documents, validate_persona_documents

    seed_persona_documents(store)
    validate_seeded_data(store)
    validate_persona_documents(store)
    return store.table_counts()


def main() -> None:
    """CLI entry point for deterministic dataset generation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="replace existing synthetic demo data",
    )
    args = parser.parse_args()
    counts = seed_demo_data(reset=args.reset)
    print("Synthetic demo data row counts:")
    for table, count in counts.items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
