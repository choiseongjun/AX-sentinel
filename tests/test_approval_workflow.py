from typing import Any

from fastapi.testclient import TestClient

from services.work_order.app import main


class MemoryRepository:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, Any]] = []

    def put(self, entity_type: str, entity_id: str, value: Any) -> None:
        self.items.append((entity_type, entity_id, value))


def approval_payload(decision: str, checklist: list[str] | None = None) -> dict[str, Any]:
    return {
        "analysis_id": "analysis-1",
        "incident_id": "incident-1",
        "decision": decision,
        "reviewer_id": "manager-1",
        "comment": "검토 의견입니다.",
        "checklist": checklist or [],
    }


def test_rejection_records_decision_without_creating_work_order(monkeypatch) -> None:
    repository = MemoryRepository()
    monkeypatch.setattr(main, "get_repository", lambda: repository)

    response = TestClient(main.app).post(
        "/api/v1/approvals",
        json=approval_payload("reject"),
    )

    assert response.status_code == 201
    assert response.json()["decision"] == "reject"
    assert [item[0] for item in repository.items] == ["approval"]


def test_modified_approval_requires_checklist(monkeypatch) -> None:
    repository = MemoryRepository()
    monkeypatch.setattr(main, "get_repository", lambda: repository)

    response = TestClient(main.app).post(
        "/api/v1/approvals",
        json=approval_payload("approve_with_changes"),
    )

    assert response.status_code == 422
