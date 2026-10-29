"""Deterministic, auditable evaluation of the illustrative credit policy."""

import json
import math
from pathlib import Path
from typing import Any

from loanpilot.config import POLICY_PATH


def pricing_rate(score: int | float | None) -> float | None:
    """Return the CP-7.1 annual rate for a score, or None without a grid rate."""
    if score is None:
        return None
    try:
        if math.isnan(float(score)):
            return None
    except (TypeError, ValueError):
        return None
    for band in _load_policy()["clauses"]:
        if band["clause_id"] != "CP-7.1":
            continue
        for rate in band["criteria"]["rates"]:
            if score >= rate["score_min"] and (
                "score_max" not in rate or score <= rate["score_max"]
            ):
                return float(rate["annual_rate"])
    return None


def _load_policy() -> dict[str, Any]:
    """Load the illustrative policy from its project-rooted JSON resource."""
    with Path(POLICY_PATH).open(encoding="utf-8") as policy_file:
        return json.load(policy_file)


def max_affordable_amount(
    income: float,
    existing_emi: float,
    rate: float,
    tenure: int,
    foir_limit: float = 0.45,
) -> float:
    """Return the largest reducing-balance principal within a FOIR limit."""
    monthly_capacity = income * foir_limit - existing_emi
    if monthly_capacity <= 0 or tenure <= 0 or rate < 0:
        return 0.0
    monthly_rate = rate / 12
    if monthly_rate == 0:
        return monthly_capacity * tenure
    factor = (1 + monthly_rate) ** tenure
    return monthly_capacity * (factor - 1) / (monthly_rate * factor)


def _result(
    clause_id: str,
    rule_text: str,
    observed: Any,
    status: str,
    severity: str,
) -> dict[str, Any]:
    """Build the stable clause-evaluation result shape."""
    return {
        "clause_id": clause_id,
        "rule_text": rule_text,
        "observed": observed,
        "status": status,
        "severity": severity,
    }


def evaluate_policy(
    features: dict[str, Any],
    extracted: dict[str, Any],
    reconciliation: dict[str, Any],
    bureau: dict[str, Any],
    kyc: dict[str, Any],
    finances: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate every CP-2.1 through CP-6.2 clause from code, never from an LLM."""
    clauses_by_id = {
        clause["clause_id"]: clause for clause in _load_policy()["clauses"]
    }
    results: list[dict[str, Any]] = []

    def add(clause_id: str, observed: Any, status: str, severity: str) -> None:
        results.append(
            _result(
                clause_id,
                clauses_by_id[clause_id]["text"],
                observed,
                status,
                severity,
            )
        )

    age = int(features["age"])
    maturity_age = age + int(features["tenure_months"]) / 12
    age_pass = 21 <= age <= 58 and maturity_age <= 60
    add(
        "CP-2.1",
        {"age": age, "age_at_maturity": round(maturity_age, 2)},
        "pass" if age_pass else "decline",
        "low" if age_pass else "high",
    )

    stated_income = float(
        extracted.get("net") or features["net_monthly_income"] or 0
    )
    income_pass = stated_income >= 25000
    add(
        "CP-2.2",
        {"stated_net_monthly_income": stated_income},
        "pass" if income_pass else "decline",
        "low" if income_pass else "high",
    )

    current_months = int(features["current_tenure_months"])
    experience_months = int(features["total_experience_months"])
    employment_pass = current_months >= 6 and experience_months >= 12
    employment_failure = clauses_by_id["CP-2.3"]["criteria"].get(
        "failure_status", "refer"
    )
    add(
        "CP-2.3",
        {
            "current_employer_months": current_months,
            "total_experience_months": experience_months,
        },
        "pass" if employment_pass else employment_failure,
        "low" if employment_pass else "high",
    )

    amount = float(features["requested_amount"])
    amount_maximum = min(1500000, stated_income * 15)
    amount_pass = 50000 <= amount <= amount_maximum
    add(
        "CP-3.1",
        {
            "requested_amount": amount,
            "maximum_for_income": amount_maximum,
        },
        "pass" if amount_pass else "decline",
        "low" if amount_pass else "high",
    )

    tenure = int(features["tenure_months"])
    tenure_pass = 12 <= tenure <= 60
    add(
        "CP-3.2",
        {"tenure_months": tenure},
        "pass" if tenure_pass else "decline",
        "low" if tenure_pass else "high",
    )

    stated_foir = finances.get("foir_stated")
    if stated_foir is None:
        foir_status, foir_severity = "refer", "medium"
    elif stated_foir <= 0.45:
        foir_status, foir_severity = "pass", "low"
    elif stated_foir <= 0.50:
        foir_status, foir_severity = "refer", "medium"
    else:
        foir_status, foir_severity = "decline", "high"
    add(
        "CP-4.1",
        {
            "foir_on_stated_income": stated_foir,
            "foir_on_verified_salary_credit": finances.get("foir_verified"),
        },
        foir_status,
        foir_severity,
    )

    score = bureau.get("score")
    if score is None:
        score_status = "refer"
    elif score >= 750:
        score_status = "pass"
    elif score >= 700:
        score_status = "pass"
    elif score >= 650:
        score_status = "refer"
    else:
        score_status = "decline"
    add(
        "CP-5.1",
        {"bureau_score": score},
        score_status,
        "low" if score_status == "pass" else "medium" if score_status == "refer" else "high",
    )

    max_dpd = int(bureau.get("max_dpd_24m") or 0)
    dpd_pass = max_dpd <= 90
    add(
        "CP-5.2",
        {"max_dpd_24m": max_dpd},
        "pass" if dpd_pass else "decline",
        "low" if dpd_pass else "high",
    )

    enquiries = int(bureau.get("enquiries_6m") or 0)
    enquiries_pass = enquiries <= 5
    add(
        "CP-5.3",
        {"enquiries_6m": enquiries},
        "pass" if enquiries_pass else "refer",
        "low" if enquiries_pass else "medium",
    )

    thin_file = score is None or bool(bureau.get("thin_file"))
    add(
        "CP-5.4",
        {
            "thin_file": thin_file,
            "requested_amount": amount,
            "amount_cap": 75000 if thin_file else None,
        },
        "refer" if thin_file else "pass",
        "medium" if thin_file else "low",
    )

    kyc_status = str(kyc.get("status", kyc.get("pan_status", "pending"))).casefold()
    name_score = float(kyc.get("name_match", kyc.get("name_match_score")) or 0)
    pan_status = str(kyc.get("pan_status", kyc_status)).casefold()
    kyc_reason = str(kyc.get("reason", "")).casefold()
    if kyc_status in {"invalid", "not_found", "not found"} or pan_status in {
        "invalid",
        "not_found",
        "not found",
    }:
        kyc_status_result, kyc_reason_text = "decline", "PAN is invalid or not found."
    elif name_score < 0.85 and (
        kyc_status == "verified" or "manual identity review" in kyc_reason
    ):
        kyc_status_result, kyc_reason_text = "refer", "Manual identity review is required."
    elif kyc_status != "verified":
        kyc_status_result, kyc_reason_text = "refer", "Complete eKYC before a decision."
    elif name_score < 0.85:
        kyc_status_result, kyc_reason_text = "refer", "Manual identity review is required."
    else:
        kyc_status_result, kyc_reason_text = "pass", "Identity check passed."
    add(
        "CP-6.1",
        {
            "status": kyc_status,
            "pan_status": kyc.get("pan_status", kyc_status),
            "name_match": name_score,
            "name_match_score": name_score,
            "reason": kyc_reason_text,
        },
        kyc_status_result,
        "low" if kyc_status_result == "pass" else "medium" if kyc_status_result == "refer" else "high",
    )

    document_pass = all(
        reconciliation.get(key, False)
        for key in ("payslip_arithmetic_matches", "salary_credits_within_tolerance", "employer_matches")
    )
    add(
        "CP-6.2",
        {
            "payslip_arithmetic_matches": reconciliation.get(
                "payslip_arithmetic_matches", False
            ),
            "salary_credit_variance_pct": reconciliation.get(
                "salary_credit_variance_pct"
            ),
            "employer_matches": reconciliation.get("employer_matches", False),
        },
        "pass" if document_pass else "refer",
        "low" if document_pass else "high",
    )

    if any(item["status"] == "decline" for item in results):
        recommendation = "Decline"
    elif any(item["status"] == "refer" for item in results):
        recommendation = "Refer"
    else:
        recommendation = "Approve"
    return {
        "recommendation": recommendation,
        "clauses": results,
        "pricing_rate": pricing_rate(score),
        "document_failure": not document_pass,
        "foir_stated": stated_foir,
        "foir_verified": finances.get("foir_verified"),
    }
