from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from services.ai_analysis.app import main


class MemoryRepository:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], Any] = {}

    def put(self, entity_type: str, entity_id: str, value: Any) -> None:
        self.items[(entity_type, entity_id)] = value

    def get(self, entity_type: str, entity_id: str) -> Any | None:
        return self.items.get((entity_type, entity_id))

    def list(self, entity_type: str) -> list[Any]:
        return [
            value
            for (stored_type, _), value in self.items.items()
            if stored_type == entity_type
        ]


def audit() -> main.AnalysisAudit:
    return main.AnalysisAudit(
        ai_provider="mock",
        model_id="deterministic-mock-v1",
        prompt_version="ax-sentinel-diagnosis-v2",
        prompt_hash="hash",
        rag_provider="local",
        document_versions={},
        guardrail_action="not_configured",
        created_at=datetime.now(UTC),
    )


def test_high_risk_analysis_creates_auditable_expert_review(monkeypatch) -> None:
    repository = MemoryRepository()

    async def generated(_request, _authorization=None):
        return (
            {
                "risk_level": "high",
                "confidence": 0.55,
                "causes": [
                    {
                        "cause": "베어링 마모",
                        "confidence": 0.55,
                        "evidence": ["temperature"],
                    }
                ],
                "recommended_actions": [
                    {
                        "sequence": 1,
                        "instruction": "안전 정지 후 점검",
                        "hazardous": True,
                        "requires_shutdown": True,
                    }
                ],
            },
            [],
            [],
            audit(),
        )

    monkeypatch.setattr(main, "get_repository", lambda: repository)
    monkeypatch.setattr(main, "_generate", generated)
    response = TestClient(main.app).post(
        "/api/v1/analyses",
        json={
            "incident_id": "incident-1",
            "equipment_id": "PRESS-001",
            "sensor_summary": "bearing temperature 112C",
            "log_summary": "E-BRG-017",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["audit"]["prompt_version"] == "ax-sentinel-diagnosis-v2"
    assert result["expert_review_required"] is True
    reviews = repository.list("expert_review")
    assert len(reviews) == 1
    assert reviews[0].analysis_id == result["id"]


def test_completed_expert_review_requires_resolution_note(monkeypatch) -> None:
    repository = MemoryRepository()
    review = main.ExpertReviewCase(
        id="review-1",
        analysis_id="analysis-1",
        incident_id="incident-1",
        status="pending",
        reasons=["낮은 분석 신뢰도"],
        risk_level="high",
        confidence=0.55,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    repository.put("expert_review", review.id, review)
    monkeypatch.setattr(main, "get_repository", lambda: repository)

    response = TestClient(main.app).patch(
        "/api/v1/expert-reviews/review-1",
        json={"status": "completed"},
    )

    assert response.status_code == 422


def test_cause_match_is_case_insensitive_and_partial() -> None:
    score = main._cause_match(
        ["Bearing Wear", "윤활 불량"],
        [{"cause": "Severe bearing wear"}, {"cause": "윤활 불량 가능성"}],
    )

    assert score == 1.0


def test_document_hit_rate_accepts_versioned_s3_location() -> None:
    chunks = [
        main.RetrievedChunk(
            content="bearing procedure",
            score=0.9,
            document_id="generated-id",
            location="s3://bucket/documents/generated-id/bearing-maintenance.md",
        )
    ]

    assert main._document_hit_rate(["bearing-maintenance.md"], chunks) == 1.0
