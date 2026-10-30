"""Deterministic data and policy tools used by the orchestrator."""

import re
import unicodedata
from pathlib import Path
from typing import Any

from loanpilot.config import PROJECT_ROOT
from loanpilot.agent.llm import LIVE_MODE, run_json_step
from loanpilot.agent.policy_engine import (
    evaluate_policy,
    max_affordable_amount,
    pricing_rate,
)
from loanpilot.data.queries import (
    get_application,
    get_bureau,
    get_customer,
    get_document_verification_report,
    get_document_verifications,
    get_documents,
    get_existing_loans,
    get_kyc,
    get_repayment_summary,
    get_transactions,
    save_document_verification_results,
)
from loanpilot.data.store import SQLiteStore
from loanpilot.data.document_verification import (
    SALARY_BANK_CATEGORIES,
    analyze_uploads,
)

def _number(text: str, label: str) -> float | None:
    """Read a labelled money value from an extracted synthetic document."""
    match = re.search(
        rf"{re.escape(label)}\s*:\s*Rs\s*([\d,]+(?:\.\d{{2}})?)",
        text,
        re.IGNORECASE,
    )
    return float(match.group(1).replace(",", "")) if match else None


def _snippet(documents: list[dict[str, Any]], expression: str) -> dict[str, str] | None:
    """Find the source document and exact line supporting an extracted field."""
    pattern = re.compile(expression, re.IGNORECASE)
    for document in documents:
        for line in document["text_content"].splitlines():
            if pattern.search(line):
                return {"source_document": document["file_name"], "snippet": line.strip()}
    return None


def _regex_fields(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract the requested structured fields with auditable regex fallbacks."""
    payslip = next(
        (
            doc["text_content"]
            for doc in documents
            if doc.get("category", doc["doc_type"]) in {"payslip", "salary_slip"}
        ),
        "",
    )
    statement = next(
        (
            doc["text_content"]
            for doc in documents
            if doc.get("category", doc["doc_type"])
            in {"bank_statement_summary", "bank_statement"}
        ),
        "",
    )
    employer_match = re.search(
        r"Employer on payslip:\s*(.+)", payslip, re.IGNORECASE
    )
    salary_avg_match = re.search(
        r"Average monthly salary credits:\s*Rs\s*([\d,]+(?:\.\d{2})?)",
        statement,
        re.IGNORECASE,
    )
    return {
        "gross": _number(payslip, "Gross pay"),
        "deductions": _number(payslip, "Deductions"),
        "net": _number(payslip, "Net pay"),
        "employer": employer_match.group(1).strip() if employer_match else None,
        "salary_credits_avg": (
            float(salary_avg_match.group(1).replace(",", ""))
            if salary_avg_match
            else None
        ),
    }


def _matches_source_fields(
    candidate: dict[str, Any], source: dict[str, Any]
) -> bool:
    """Prevent model-extracted values from changing deterministic inputs."""
    for key in ("gross", "deductions", "net", "salary_credits_avg"):
        candidate_value = candidate[key]
        source_value = source[key]
        if candidate_value is None or source_value is None:
            if candidate_value is not source_value:
                return False
        elif abs(float(candidate_value) - float(source_value)) > 0.01:
            return False
    employer = str(candidate["employer"] or "")
    source_employer = str(source["employer"] or "")
    return _normalize_employer(employer) == _normalize_employer(source_employer)


def get_features(application_id: str, store: SQLiteStore) -> dict[str, Any]:
    """Fetch case, customer, transactions, loans, repayments, and documents."""
    application_rows = get_application(application_id, store)
    if application_rows.empty:
        raise ValueError(f"Unknown application id: {application_id}")
    application = application_rows.iloc[0].to_dict()
    customer = get_customer(application["customer_id"], store).iloc[0].to_dict()
    documents = get_documents(application_id, store).to_dict("records")
    uploads = []
    root = Path(PROJECT_ROOT).resolve()
    for document in documents:
        category = str(document.get("category") or document.get("doc_type") or "")
        category = {
            "payslip": "salary_slip",
            "bank_statement_summary": "bank_statement",
        }.get(category, category)
        if category not in SALARY_BANK_CATEGORIES:
            continue
        try:
            path = (root / str(document.get("file_path") or "")).resolve()
            path.relative_to(root)
            content = path.read_bytes() if path.is_file() else b""
        except (OSError, ValueError):
            content = b""
        uploads.append(
            {
                "doc_id": document["doc_id"],
                "file_name": document["file_name"],
                "category": category,
                "content": content,
                "text_content": document.get("text_content", ""),
            }
        )
    analyzed_documents, analyzed_report = analyze_uploads(
        uploads,
        {
            "name": customer.get("name", ""),
            "employer": customer.get("employer", ""),
            "income": customer.get("net_monthly_income"),
            "job_months": customer.get("current_tenure_months"),
        },
        required_categories=SALARY_BANK_CATEGORIES,
    )
    save_document_verification_results(
        application_id, analyzed_documents, analyzed_report, store
    )
    documents = get_documents(application_id, store).to_dict("records")
    document_verifications = get_document_verifications(application_id, store)
    document_verification_report = get_document_verification_report(
        application_id, store
    )
    transactions = get_transactions(application["customer_id"], store).to_dict("records")
    loans = get_existing_loans(application["customer_id"], store).to_dict("records")
    repayment = get_repayment_summary(application["customer_id"], store).iloc[0].to_dict()
    return {
        "application": application,
        "customer": customer,
        "documents": documents,
        "document_verifications": document_verifications,
        "document_verification_report": document_verification_report,
        "transactions": transactions,
        "loans": loans,
        "repayment": repayment,
    }


def extract_document_fields(
    application_id: str,
    features: dict[str, Any],
    store: SQLiteStore,
) -> dict[str, Any]:
    """Extract payslip and bank statement fields and retain source snippets."""
    documents = features["documents"]
    regex_fields = _regex_fields(documents)
    persona_key = features["application"].get("persona_key")
    prompt = (
        "Extract only facts explicitly present in these synthetic loan documents. "
        "Return a JSON object with numeric keys gross, deductions, net, "
        "salary_credits_avg, string employer, and a concise string "
        "anomaly_description describing document inconsistencies only. Use null "
        "for absent extracted values. Do not infer or repair values. "
        f"Documents: {documents}"
    )
    output, mode = run_json_step(
        application_id,
        "document_verification",
        prompt,
        persona_key,
        store,
    )
    output_fields = (
        output.get("extracted_fields", output)
        if isinstance(output, dict)
        else {}
    )
    required = ("gross", "deductions", "net", "employer", "salary_credits_avg")
    llm_valid = (
        isinstance(output_fields, dict)
        and all(key in output_fields for key in required)
        and all(output_fields[key] is None or isinstance(output_fields[key], (int, float)) for key in (
            "gross", "deductions", "net", "salary_credits_avg"
        ))
        and (output_fields["employer"] is None or isinstance(output_fields["employer"], str))
    )
    model_fields = {key: output_fields[key] for key in required} if llm_valid else {}
    source_matches = llm_valid and _matches_source_fields(model_fields, regex_fields)
    fields = model_fields if source_matches else regex_fields
    evidence_patterns = {
        "gross": r"Gross pay:",
        "deductions": r"Deductions:",
        "net": r"Net pay:",
        "employer": r"Employer on payslip:",
        "salary_credits_avg": r"Average monthly salary credits:",
    }
    evidence = {
        key: _snippet(documents, pattern)
        for key, pattern in evidence_patterns.items()
    }
    persisted_evidence_fields = {
        "gross": "gross_salary",
        "deductions": "deductions",
        "net": "net_salary",
        "employer": "employer_name",
        "salary_credits_avg": "average_monthly_salary_credits",
    }
    for verification in features.get("document_verifications", []):
        source_fields = verification.get("extracted_fields", {})
        for field, source_field in persisted_evidence_fields.items():
            value = source_fields.get(source_field)
            if value is not None:
                fields[field] = value
                snippet = verification.get("field_evidence", {}).get(source_field)
                if snippet:
                    evidence[field] = {
                        "source_document": verification.get("file_name", "Uploaded PDF"),
                        "snippet": snippet,
                    }
    report = features.get("document_verification_report") or {}
    salary_statement = report.get("salary_statement_verification") or {}
    document_net = salary_statement.get("salary_slip_net_salary")
    bank_average = salary_statement.get(
        "bank_statement_average_monthly_salary_credit"
    )
    if salary_statement:
        fields["net"] = (
            float(document_net) if isinstance(document_net, (int, float)) else None
        )
        fields["salary_credits_avg"] = (
            float(bank_average) if isinstance(bank_average, (int, float)) else None
        )
    salary_name = (salary_statement.get("name_comparison") or {}).get(
        "salary_slip_name"
    )
    if salary_name:
        fields["applicant_name_salary_slip"] = salary_name
    bank_name = (salary_statement.get("name_comparison") or {}).get(
        "bank_statement_name"
    )
    if bank_name:
        fields["applicant_name_bank_statement"] = bank_name
    anomalies = (
        output.get("anomaly_description")
        if llm_valid and isinstance(output, dict)
        else None
    )
    if report:
        anomalies = str(report.get("explanation") or anomalies)
    if not anomalies:
        anomalies = "Anomaly description is unavailable; see deterministic reconciliation results."
    return {
        "fields": fields,
        "evidence": evidence,
        "anomaly_description": str(anomalies),
        "document_verifications": features.get("document_verifications", []),
        "document_report": report,
        "extraction_method": (
            "Gemini JSON"
            if source_matches and mode == LIVE_MODE
            else "Recorded fields"
            if source_matches
            else "Regex fallback"
        ),
        "mode": mode,
    }


def reconcile_documents(
    extracted: dict[str, Any], features: dict[str, Any]
) -> dict[str, Any]:
    """Compare payslip arithmetic, salary credits, and employer with records."""
    fields = extracted["fields"]
    payslip_net = fields.get("net")
    gross = fields.get("gross")
    deductions = fields.get("deductions")
    salary_average = fields.get("salary_credits_avg")
    employer_document = str(fields.get("employer") or "")
    employer_record = str(features["customer"]["employer"])
    arithmetic_matches = (
        gross is not None
        and deductions is not None
        and payslip_net is not None
        and abs(float(gross) - float(deductions) - float(payslip_net)) <= 1
    )
    salary_variance_pct = (
        abs(float(salary_average) - float(payslip_net)) / float(payslip_net) * 100
        if salary_average is not None and payslip_net
        else None
    )
    salary_within_tolerance = (
        salary_variance_pct is not None and salary_variance_pct <= 10
    )
    employer_matches = _normalize_employer(employer_document) == _normalize_employer(
        employer_record
    )
    report = features.get("document_verification_report") or {}
    verification_status = str(report.get("overall_status", ""))
    salary_statement = report.get("salary_statement_verification") or {}
    salary_statement_status = str(salary_statement.get("status", ""))
    manual_document_review = verification_status in {
        "Needs manual review",
        "Incomplete",
        "Partially verified",
    }
    if salary_statement_status:
        document_failure = salary_statement_status != "MATCH"
    else:
        document_failure = manual_document_review or not (
            arithmetic_matches and salary_within_tolerance and employer_matches
        )
    return {
        "payslip_arithmetic_matches": arithmetic_matches,
        "salary_credits_within_tolerance": salary_within_tolerance,
        "salary_credit_variance_pct": salary_variance_pct,
        "employer_matches": employer_matches,
        "payslip_net": payslip_net,
        "salary_credits_avg": salary_average,
        "employer_on_document": employer_document,
        "employer_on_record": employer_record,
        "document_failure": document_failure,
        "document_verification_status": verification_status or "Not assessed",
        "document_verification_explanation": report.get("explanation", ""),
        "salary_statement_status": salary_statement_status or None,
        "salary_statement_verification": salary_statement or None,
    }


def _normalize_employer(value: str) -> str:
    """Normalize case, punctuation, and whitespace without fuzzy matching names."""
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", normalized).split())


def financial_assessment(
    features: dict[str, Any], extracted: dict[str, Any]
) -> dict[str, Any]:
    """Compute requested-loan EMI and stated/verified-income FOIR."""
    application = features["application"]
    customer = features["customer"]
    bureau_rows = features.get("bureau", {})
    score = bureau_rows.get("score")
    rate = pricing_rate(score)
    calculation_rate = rate if rate is not None else 0.16
    monthly_rate = calculation_rate / 12
    amount = float(application["requested_amount"])
    term = int(application["tenure_months"])
    factor = (1 + monthly_rate) ** term
    proposed_emi = amount * monthly_rate * factor / (factor - 1)
    existing_emi = sum(
        float(loan["emi"])
        for loan in features["loans"]
        if loan["status"] == "Active"
    )
    document_report = features.get("document_verification_report") or {}
    salary_statement = document_report.get("salary_statement_verification") or {}
    has_salary_documents = any(
        str(document.get("category") or document.get("doc_type") or "")
        in {"salary_slip", "payslip", "bank_statement", "bank_statement_summary"}
        for document in features.get("documents", [])
    )
    payslip_net = salary_statement.get("salary_slip_net_salary")
    bank_average = salary_statement.get(
        "bank_statement_average_monthly_salary_credit"
    )
    stated_income = float(
        payslip_net
        if isinstance(payslip_net, (int, float))
        else customer["net_monthly_income"]
        if has_salary_documents
        else extracted["fields"].get("net") or customer["net_monthly_income"]
    )
    if has_salary_documents:
        verified_income = (
            float(bank_average) if isinstance(bank_average, (int, float)) else 0.0
        )
    else:
        salary_values = [
            float(row["salary_credit"]) for row in features["transactions"]
        ]
        verified_income = (
            sum(salary_values) / len(salary_values) if salary_values else 0.0
        )
    return {
        "stated_income": stated_income,
        "verified_income": verified_income,
        "average_salary_credit": verified_income,
        "existing_emi": existing_emi,
        "proposed_emi": proposed_emi,
        "foir_stated": (
            (existing_emi + proposed_emi) / stated_income if stated_income else None
        ),
        "foir_verified": (
            (existing_emi + proposed_emi) / verified_income
            if verified_income
            else None
        ),
        "pricing_rate": rate,
        "calculation_rate": calculation_rate,
        "rate_source": "CP-7.1" if rate is not None else "16% calculation proxy; no CP-7.1 grid rate",
        "average_balance": float(customer.get("average_balance") or 0),
        "cheque_bounces_6m": sum(
            int(row["cheque_bounces"]) for row in features["transactions"]
        ),
    }


def bureau_check(application_id: str, store: SQLiteStore) -> dict[str, Any]:
    """Return the decoded synthetic bureau response."""
    response = get_bureau(application_id, store)
    return {} if response.empty else response.iloc[0]["payload"]


def kyc_check(application_id: str, store: SQLiteStore) -> dict[str, Any]:
    """Return the decoded synthetic KYC response."""
    response = get_kyc(application_id, store)
    return {} if response.empty else response.iloc[0]["payload"]


def policy_check(
    features: dict[str, Any],
    extracted: dict[str, Any],
    reconciliation: dict[str, Any],
    bureau: dict[str, Any],
    kyc: dict[str, Any],
    finances: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate every policy clause deterministically."""
    application = features["application"]
    customer = features["customer"]
    policy_features = {
        **application,
        "age": customer["age"],
        "net_monthly_income": customer["net_monthly_income"],
        "current_tenure_months": customer["current_tenure_months"],
        "total_experience_months": customer["total_experience_months"],
    }
    return evaluate_policy(
        policy_features,
        extracted["fields"],
        reconciliation,
        bureau,
        kyc,
        finances,
    )


def price_loan(
    requested_amount: float, tenure: int, score: int | None
) -> dict[str, Any]:
    """Calculate CP-7.1 pricing and reducing-balance EMI."""
    rate = pricing_rate(score)
    if rate is None:
        return {
            "rate": None,
            "annual_rate_pct": None,
            "emi": None,
            "pricing_clause": "CP-7.1",
            "note": "No grid rate: thin file or score outside the defined bands.",
        }
    monthly_rate = rate / 12
    factor = (1 + monthly_rate) ** tenure
    emi = requested_amount * monthly_rate * factor / (factor - 1)
    return {
        "rate": rate,
        "annual_rate_pct": rate * 100,
        "emi": emi,
        "pricing_clause": "CP-7.1",
        "basis": "annual reducing balance",
    }


def risk_assessment(
    bureau: dict[str, Any], reconciliation: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    """Assign the requested rule-based risk band without confidence estimates."""
    score = bureau.get("score")
    if score is None or score < 700 or reconciliation["document_failure"]:
        risk_band = "High"
    elif score >= 750 and not any(
        clause["status"] in ("refer", "decline") for clause in policy["clauses"]
    ):
        risk_band = "Low"
    else:
        risk_band = "Medium"
    flags = [
        clause["clause_id"]
        for clause in policy["clauses"]
        if clause["status"] in ("refer", "decline")
    ]
    return {"risk_band": risk_band, "flags": flags, "score": score}


def counterfactuals(
    finances: dict[str, Any], tenure: int, foir_limit: float = 0.45
) -> dict[str, Any]:
    """Compute the largest amount within the illustrative FOIR limit."""
    rate = finances["pricing_rate"]
    if rate is None:
        return {
            "max_affordable_amount": None,
            "foir_limit": foir_limit,
            "note": "No score-band pricing rate is defined by CP-7.1.",
        }
    amount = max_affordable_amount(
        finances["verified_income"],
        finances["existing_emi"],
        rate,
        tenure,
        foir_limit,
    )
    return {
        "max_affordable_amount": round(amount, 2),
        "foir_limit": foir_limit,
        "income_basis": "six-month average salary credit",
        "clause_id": "CP-4.1",
    }
