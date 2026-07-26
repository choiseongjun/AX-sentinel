from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewDecision:
    expert_review_required: bool
    manager_approval_required: bool
    reasons: tuple[str, ...]


def evaluate_review_policy(
    *,
    confidence: float,
    has_related_documents: bool,
    risk_level: str,
) -> ReviewDecision:
    reasons: list[str] = []
    if confidence < 0.7:
        reasons.append("low_confidence")
    if not has_related_documents:
        reasons.append("no_related_documents")

    return ReviewDecision(
        expert_review_required=bool(reasons),
        manager_approval_required=risk_level in {"high", "critical"},
        reasons=tuple(reasons),
    )
