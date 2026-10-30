"""Shared human decision actions and AI comparison rules."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionAction:
    """Persisted label, next stage, and AI-alignment for one action code."""

    label: str
    stage: str
    ai_recommendation: str


HUMAN_ACTIONS = {
    "approve": DecisionAction("Approve", "Sanction", "Approve"),
    "approve_with_conditions": DecisionAction(
        "Approve with conditions", "Sanction", "Approve"
    ),
    "modify_terms": DecisionAction("Modify terms", "Sanction", "Approve"),
    "refer_up": DecisionAction("Refer up", "Escalated", "Refer"),
    "reject": DecisionAction("Reject", "Rejected", "Decline"),
    "request_documents": DecisionAction(
        "Request documents", "Awaiting documents", "Refer"
    ),
}


@dataclass(frozen=True)
class HumanActionAssessment:
    """Whether an action differs from AI guidance and meets the override rule."""

    differs: bool
    is_override: bool


def action_code_for_label(decision: str) -> str:
    """Resolve the persisted human-readable decision to its canonical code."""
    for action_code, action in HUMAN_ACTIONS.items():
        if action.label == decision:
            return action_code
    raise ValueError(f"Unsupported human decision: {decision}")


def evaluate_human_action(
    ai_recommendation: str | None,
    action_code: str,
) -> HumanActionAssessment:
    """Apply the shared action alignment and CP-8.2 override rules."""
    action = HUMAN_ACTIONS.get(action_code)
    if action is None:
        raise ValueError(f"Unsupported human action code: {action_code}")
    differs = action.ai_recommendation != ai_recommendation
    is_approval = action_code in {
        "approve",
        "approve_with_conditions",
        "modify_terms",
    }
    is_override = (
        (is_approval and ai_recommendation == "Decline")
        or (action_code == "reject" and ai_recommendation == "Approve")
    )
    return HumanActionAssessment(differs=differs, is_override=is_override)
