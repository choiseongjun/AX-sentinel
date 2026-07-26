from services.ai_analysis.app.policy import evaluate_review_policy


def test_high_risk_requires_manager_approval() -> None:
    decision = evaluate_review_policy(
        confidence=0.95,
        has_related_documents=True,
        risk_level="high",
    )

    assert decision.manager_approval_required is True
    assert decision.expert_review_required is False


def test_low_confidence_or_missing_documents_requires_expert() -> None:
    decision = evaluate_review_policy(
        confidence=0.45,
        has_related_documents=False,
        risk_level="medium",
    )

    assert decision.expert_review_required is True
    assert decision.reasons == ("low_confidence", "no_related_documents")


def test_ai_output_is_never_directly_executable() -> None:
    from services.ai_analysis.app.main import AnalysisResult

    assert AnalysisResult.model_fields["executable"].default is False
