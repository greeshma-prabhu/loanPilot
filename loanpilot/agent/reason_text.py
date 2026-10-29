"""Deterministic plain-English summaries for policy outcomes."""

from typing import Any

from loanpilot.components import fmt_inr

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_STRENGTH_ORDER = (
    "CP-4.1",
    "CP-5.1",
    "CP-2.3",
    "CP-2.1",
    "CP-3.1",
    "CP-3.2",
    "CP-5.2",
    "CP-5.3",
    "CP-6.1",
    "CP-6.2",
)


def _observed(clause: dict[str, Any]) -> dict[str, Any]:
    """Return a clause's structured values as a mapping."""
    value = clause.get("observed")
    return value if isinstance(value, dict) else {}


def _reason_sentence(clause: dict[str, Any]) -> str:
    """Build one short explanation using observed values, never policy prose."""
    clause_id = str(clause.get("clause_id", ""))
    observed = _observed(clause)
    if clause_id == "CP-2.1":
        return f"Applicant age is {observed.get('age', 'unavailable')} years."
    if clause_id == "CP-2.2":
        return (
            f"Stated monthly income is {fmt_inr(observed.get('stated_net_monthly_income'))}; "
            "the minimum is Rs 25,000."
        )
    if clause_id == "CP-2.3":
        return (
            f"Current-job tenure is {observed.get('current_employer_months', 'unavailable')} "
            f"months and total experience is {observed.get('total_experience_months', 'unavailable')} "
            "months; the minimums are 6 and 12 months."
        )
    if clause_id == "CP-3.1":
        return (
            f"Requested amount is {fmt_inr(observed.get('requested_amount'))}; "
            f"the income-based maximum is {fmt_inr(observed.get('maximum_for_income'))}."
        )
    if clause_id == "CP-3.2":
        return f"Requested tenure is {observed.get('tenure_months', 'unavailable')} months."
    if clause_id == "CP-4.1":
        stated = observed.get("foir_on_stated_income")
        verified = observed.get("foir_on_verified_salary_credit")
        stated_text = f"{float(stated):.1%}" if stated is not None else "unavailable"
        verified_text = f"{float(verified):.1%}" if verified is not None else "unavailable"
        return (
            f"FOIR is {stated_text} on stated income and {verified_text} on verified income; "
            "the limit is 45%."
        )
    if clause_id == "CP-5.1":
        score = observed.get("bureau_score")
        return "Bureau file is thin; no score is available." if score is None else f"Bureau score is {score}."
    if clause_id == "CP-5.2":
        return f"Maximum reported delinquency is {observed.get('max_dpd_24m', 'unavailable')} days past due."
    if clause_id == "CP-5.3":
        return f"Recent bureau enquiries number {observed.get('enquiries_6m', 'unavailable')} in six months."
    if clause_id == "CP-5.4":
        return (
            f"The thin-file request is {fmt_inr(observed.get('requested_amount'))}; "
            f"the demo amount cap is {fmt_inr(observed.get('amount_cap'))}."
        )
    if clause_id == "CP-6.1":
        if observed.get("reason"):
            return str(observed["reason"])
        return (
            f"KYC status is {observed.get('status', observed.get('pan_status')) or 'unavailable'} "
            f"with a name-match score of "
            f"{float(observed.get('name_match', observed.get('name_match_score')) or 0):.2f}."
        )
    if clause_id == "CP-6.2":
        issues = []
        if not observed.get("payslip_arithmetic_matches"):
            issues.append("payslip totals")
        variance = observed.get("salary_credit_variance_pct")
        if variance is not None and float(variance) > 10:
            issues.append("salary credits")
        if not observed.get("employer_matches"):
            issues.append("employer name")
        return "Documents need review: " + (", ".join(issues) or "evidence mismatch") + "."
    return "This policy check needs review."


def build_why(
    recommendation: str,
    clauses: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build up to five deterministic reason lines ordered by decision relevance."""
    if recommendation == "Approve":
        passing = {str(item.get("clause_id")): item for item in clauses if item.get("status") == "pass"}
        strengths = [
            passing[clause_id]
            for clause_id in _STRENGTH_ORDER
            if clause_id in passing
        ][:3]
        lines = [
            {
                "status": "pass",
                "clause_id": str(item["clause_id"]),
                "text": _reason_sentence(item),
            }
            for item in strengths
        ]
        lines.append(
            {
                "status": "pass",
                "clause_id": "Policy",
                "text": f"All {len(clauses)} policy checks passed.",
            }
        )
        return lines[:5]

    triggered = [
        item for item in clauses if item.get("status") in {"decline", "refer"}
    ]
    triggered.sort(
        key=lambda item: (
            _SEVERITY_ORDER.get(str(item.get("severity", "")).casefold(), 3),
            str(item.get("clause_id", "")),
        )
    )
    return [
        {
            "status": str(item.get("status", "refer")),
            "clause_id": str(item.get("clause_id", "Policy")),
            "text": _reason_sentence(item),
        }
        for item in triggered[:5]
    ]
