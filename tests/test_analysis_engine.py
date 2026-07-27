import json

import httpx

from services.ai_analysis.app.engine import MockAnalysisEngine, OllamaAnalysisEngine


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


def test_ollama_engine_requests_structured_output_and_records_audit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3:4b"
        assert payload["stream"] is False
        assert payload["think"] is False
        assert payload["format"]["required"] == [
            "risk_level",
            "confidence",
            "causes",
            "recommended_actions",
        ]
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "risk_level": "high",
                            "confidence": 0.81,
                            "causes": [
                                {
                                    "cause": "유압 제어 밸브 응답 지연",
                                    "confidence": 0.81,
                                    "evidence": ["pressure spike"],
                                }
                            ],
                            "recommended_actions": [
                                {
                                    "sequence": 1,
                                    "instruction": "설비를 안전 정지하고 밸브를 점검한다.",
                                    "hazardous": True,
                                    "requires_shutdown": True,
                                },
                                {
                                    "sequence": 2,
                                    "instruction": "설비를 안전 정지하고 밸브를 점검한다.",
                                    "hazardous": True,
                                    "requires_shutdown": True,
                                },
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
                "prompt_eval_count": 120,
                "eval_count": 80,
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    )
    result = OllamaAnalysisEngine(
        base_url="http://ollama.test",
        model="qwen3:4b",
        client=client,
    ).analyze(
        {
            "sensor_summary": "hydraulic pressure high",
            "log_summary": "valve delay",
            "related_document_ids": [],
        }
    )

    assert result["causes"][0]["cause"] == "유압 제어 밸브 응답 지연"
    assert result["_audit"]["ai_provider"] == "ollama"
    assert result["_audit"]["model_id"] == "qwen3:4b"
    assert result["_audit"]["input_tokens"] == 120
    assert len(result["recommended_actions"]) == 1
    assert result["recommended_actions"][0]["sequence"] == 1
