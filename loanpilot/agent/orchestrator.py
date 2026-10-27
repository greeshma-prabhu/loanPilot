"""Five-step assessment orchestrator with deterministic policy decisions."""

import json
from datetime import datetime
from time import perf_counter
from uuid import uuid4
from typing import Any

from loanpilot.agent.llm import run_json_step
from loanpilot.agent.tools import (
    bureau_check,
    counterfactuals,
    extract_document_fields,
    financial_assessment,
    get_features,
    kyc_check,
    price_loan,
    policy_check,
    reconcile_documents,
    risk_assessment,
)
from loanpilot.config import BANK_NAME
from loanpilot.data.queries import (
    append_audit_event,
    save_agent_trace_step,
    save_assessment_decision,
)
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore

_STEPS = [
    ("Document Verification", "Document Verification Agent"),
    ("Financial Assessment", "Financial Assessment Agent"),
    ("Credit & Policy", "Credit & Policy Agent"),
    ("Risk", "Risk Assessment Agent"),
    ("Recommendation", "Recommendation Agent"),
]


def _jsonable(value: Any) -> Any:
    """Convert nested tool data into JSON-compatible values."""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        return _jsonable(value.item())
    if isinstance(value, float) and value != value:
        return None
    return value


def _call(
    calls: list[dict[str, Any]],
    name: str,
    inputs: dict[str, Any],
    function: Any,
) -> Any:
    """Execute a named tool and record its inputs and returned output."""
    output = function()
    calls.append(
        {
            "name": name,
            "inputs": _jsonable(inputs),
            "outputs": _jsonable(output),
        }
    )
    return output


def _reason_rows(policy: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Separate supporting and adverse policy reasons with clause references."""
    clauses = policy["clauses"]
    reasons_for = [
        {"clause_id": clause["clause_id"], "text": clause["rule_text"]}
        for clause in clauses
        if clause["status"] == "pass"
    ]
    reasons_against = [
        {
            "clause_id": clause["clause_id"],
            "text": f"{clause['rule_text']} Observed: {clause['observed']}",
        }
        for clause in clauses
        if clause["status"] in ("refer", "decline")
    ]
    return reasons_for, reasons_against


def _recommendation_explanation(
    application_id: str,
    persona_key: str | None,
    recommendation: str,
    policy: dict[str, Any],
    risk: dict[str, Any],
    finances: dict[str, Any],
    features: dict[str, Any],
    store: SQLiteStore,
) -> tuple[str, str]:
    """Ask Gemini for grounded wording without allowing it to alter policy."""
    prompt = (
        "Write a concise plain-English explanation of this deterministic demo "
        "assessment. Do not change the recommendation, infer facts, add a confidence "
        "number, or imply sanction. Mention the cited policy clauses and the required "
        "human handoff. Return JSON with one string field explanation. "
        f"Bank: {BANK_NAME}. Recommendation: {recommendation}. "
        f"Risk: {risk}. Policy results: {policy['clauses']}. "
        f"Financials: {finances}. Customer context: "
        f"{features['customer']['name']}, relationship since "
        f"{features['customer']['relationship_since']}, average account balance "
        f"{features['customer']['average_balance']}."
    )
    response, mode = run_json_step(
        application_id,
        "recommendation",
        prompt,
        persona_key,
        store,
    )
    explanation = response.get("explanation") if response else None
    if not isinstance(explanation, str) or not explanation.strip():
        adverse = [
            f"{item['clause_id']} ({item['status']})"
            for item in policy["clauses"]
            if item["status"] != "pass"
        ]
        explanation = (
            f"The deterministic illustrative policy result is {recommendation}. "
            f"Relevant results: {', '.join(adverse) if adverse else 'all evaluated checks passed'}. "
            "This is a recommendation only; a human reviewer must decide whether to proceed."
        )
    return explanation.strip(), mode


def run_assessment(
    application_id: str,
    store: SQLiteStore | None = None,
) -> dict[str, Any]:
    """Run all five assessment steps and persist the trace and human handoff."""
    store = store or SQLiteStore()
    create_schema(store)
    run_id = str(uuid4())
    state: dict[str, Any] = {}
    tool_calls_by_step: list[list[dict[str, Any]]] = []
    modes: list[str] = []
    step_outputs: dict[str, Any] = {}
    trace_steps: list[dict[str, Any]] = []

    for step_no, (step_name, agent_role) in enumerate(_STEPS, start=1):
        started = datetime.now().isoformat(timespec="milliseconds")
        timer = perf_counter()
        calls: list[dict[str, Any]] = []

        if step_no == 1:
            features = _call(
                calls,
                "get_features",
                {"application_id": application_id},
                lambda: get_features(application_id, store),
            )
            application = features["application"]
            features["bureau"] = _call(
                calls,
                "bureau_check",
                {"application_id": application_id},
                lambda: bureau_check(application_id, store),
            )
            extracted = _call(
                calls,
                "extract_document_fields",
                {"application_id": application_id, "document_count": len(features["documents"])},
                lambda: extract_document_fields(application_id, features, store),
            )
            reconciliation = _call(
                calls,
                "reconcile_documents",
                {"application_id": application_id},
                lambda: reconcile_documents(extracted, features),
            )
            state.update(
                {
                    "features": features,
                    "extracted": extracted,
                    "reconciliation": reconciliation,
                }
            )
            mode = extracted["mode"]
            step_output = {
                "extracted_fields": extracted["fields"],
                "evidence": extracted["evidence"],
                "anomaly_description": extracted["anomaly_description"],
                "reconciliation": reconciliation,
            }
        elif step_no == 2:
            finances = _call(
                calls,
                "financial_assessment",
                {"application_id": application_id},
                lambda: financial_assessment(state["features"], state["extracted"]),
            )
            state["finances"] = finances
            mode = "Deterministic"
            step_output = finances
        elif step_no == 3:
            bureau = state["features"]["bureau"]
            kyc = _call(
                calls,
                "kyc_check",
                {"application_id": application_id},
                lambda: kyc_check(application_id, store),
            )
            policy = _call(
                calls,
                "policy_check",
                {"application_id": application_id},
                lambda: policy_check(
                    state["features"],
                    state["extracted"],
                    state["reconciliation"],
                    bureau,
                    kyc,
                    state["finances"],
                ),
            )
            state.update({"bureau": bureau, "kyc": kyc, "policy": policy})
            mode = "Deterministic"
            step_output = {"bureau": bureau, "kyc": kyc, "policy": policy}
        elif step_no == 4:
            risk = _call(
                calls,
                "risk_assessment",
                {"application_id": application_id},
                lambda: risk_assessment(
                    state["bureau"], state["reconciliation"], state["policy"]
                ),
            )
            state["risk"] = risk
            mode = "Deterministic"
            step_output = risk
        else:
            application = state["features"]["application"]
            pricing = _call(
                calls,
                "price_loan",
                {
                    "requested_amount": application["requested_amount"],
                    "tenure": application["tenure_months"],
                    "score": state["bureau"].get("score"),
                },
                lambda: price_loan(
                    application["requested_amount"],
                    application["tenure_months"],
                    state["bureau"].get("score"),
                ),
            )
            counterfactual = _call(
                calls,
                "counterfactuals",
                {"application_id": application_id, "foir_limit": 0.45},
                lambda: counterfactuals(
                    state["finances"], application["tenure_months"]
                ),
            )
            recommendation = state["policy"]["recommendation"]
            explanation, mode = _recommendation_explanation(
                application_id,
                application.get("persona_key"),
                recommendation,
                state["policy"],
                state["risk"],
                state["finances"],
                state["features"],
                store,
            )
            calls.append(
                {
                    "name": "grounded_explanation",
                    "inputs": {
                        "recommendation": recommendation,
                        "clause_ids": [
                            clause["clause_id"]
                            for clause in state["policy"]["clauses"]
                        ],
                    },
                    "outputs": {"explanation": explanation},
                }
            )
            reasons_for, reasons_against = _reason_rows(state["policy"])
            conditions = []
            if state["policy"]["document_failure"]:
                conditions.append("Refer for human document review (CP-6.2).")
            if any(
                item["clause_id"] == "CP-5.4" and item["status"] == "refer"
                for item in state["policy"]["clauses"]
            ):
                conditions.append("Thin-file amount cap: Rs 75,000 (CP-5.4).")
            if state["policy"]["recommendation"] != "Decline":
                conditions.append("Human approval is required before any sanction (CP-8.1).")
            state["recommendation"] = recommendation
            state["pricing"] = pricing
            state["counterfactual"] = counterfactual
            state["explanation"] = explanation
            state["conditions"] = conditions
            state["reasons_for"] = reasons_for
            state["reasons_against"] = reasons_against
            step_output = {
                "recommendation": recommendation,
                "risk_band": state["risk"]["risk_band"],
                "reasons_for": reasons_for,
                "reasons_against": reasons_against,
                "conditions": conditions,
                "counterfactual": counterfactual,
                "pricing": pricing,
                "explanation": explanation,
                "explanation_mode": mode,
            }

        duration_ms = int((perf_counter() - timer) * 1000)
        next_step = (
            _STEPS[step_no][0] if step_no < len(_STEPS) else "Human Review"
        )
        handoff = f"{step_name} complete; hand off to {next_step}."
        save_agent_trace_step(
            application_id,
            run_id,
            step_no,
            agent_role,
            json.dumps(_jsonable({"calls": calls, "result": step_output}), sort_keys=True),
            started,
            duration_ms,
            mode,
            handoff,
            store,
        )
        append_audit_event(
            application_id,
            started,
            agent_role,
            f"Completed {step_name}",
            handoff,
            store,
        )
        tool_calls_by_step.append(calls)
        modes.append(mode)
        step_outputs[step_name] = _jsonable(step_output)
        trace_steps.append(
            {
                "step_no": step_no,
                "agent": agent_role,
                "started_at": started,
                "duration_ms": duration_ms,
                "mode": mode,
                "handoff": handoff,
                "calls": _jsonable(calls),
                "result": _jsonable(step_output),
            }
        )

    policy = state["policy"]
    recommendation = state["recommendation"]
    reasons = {
        "risk_band": state["risk"]["risk_band"],
        "risk_flags": state["risk"]["flags"],
        "policy_clauses": policy["clauses"],
        "reasons_for": state["reasons_for"],
        "reasons_against": state["reasons_against"],
        "conditions": state["conditions"],
        "pricing": state["pricing"],
        "counterfactual": state["counterfactual"],
        "explanation": state["explanation"],
        "explanation_mode": modes[-1],
        "extraction_mode": modes[0],
        "document_anomaly_description": state["extracted"]["anomaly_description"],
        "foir_stated": state["finances"]["foir_stated"],
        "foir_verified": state["finances"]["foir_verified"],
    }
    save_assessment_decision(
        application_id,
        recommendation,
        json.dumps(_jsonable(reasons), sort_keys=True),
        datetime.now().isoformat(timespec="seconds"),
        store,
    )
    return {
        "application_id": application_id,
        "run_id": run_id,
        "recommendation": recommendation,
        "risk_band": state["risk"]["risk_band"],
        "policy": policy,
        "risk": state["risk"],
        "finances": state["finances"],
        "extracted": state["extracted"],
        "reconciliation": state["reconciliation"],
        "pricing": state["pricing"],
        "counterfactual": state["counterfactual"],
        "reasons_for": state["reasons_for"],
        "reasons_against": state["reasons_against"],
        "conditions": state["conditions"],
        "explanation": state["explanation"],
        "explanation_mode": modes[-1],
        "modes": modes,
        "steps": step_outputs,
        "tool_calls": tool_calls_by_step,
        "trace": trace_steps,
        "handed_to": "Human Review",
    }
