from services.ai_analysis.app.engine import MockAnalysisEngine


def test_mock_engine_reduces_confidence_without_documents() -> None:
    result = MockAnalysisEngine().analyze(
        {
            "sensor_summary": "temperature high",
            "log_summary": "bearing warning",
            "related_document_ids": [],
        }
    )

    assert result["confidence"] < 0.7
    assert result["risk_level"] == "high"
    assert result["recommended_actions"][0]["hazardous"] is True
