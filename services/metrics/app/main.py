import asyncio
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import Depends, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.config import get_settings
from shared.dynamodb import get_repository
from shared.events import get_event_publisher

app = create_app("metrics-service")


class AnalysisFeedback(BaseModel):
    incident_id: str
    analysis_id: str
    cause_accuracy: int = Field(ge=1, le=5)
    action_usefulness: int = Field(ge=1, le=5)
    actual_cause: str
    comment: str | None = None


class FeedbackAccepted(BaseModel):
    accepted: bool


@app.post("/api/v1/feedback", response_model=FeedbackAccepted, tags=["ai-operations"])
async def record_feedback(
    feedback: AnalysisFeedback,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.FIELD_WORKER, Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> FeedbackAccepted:
    feedback_id = str(uuid4())
    await run_in_threadpool(get_repository().put, "feedback", feedback_id, feedback)
    await run_in_threadpool(
        get_event_publisher().publish,
        "feedback.submitted",
        {"id": feedback_id, **feedback.model_dump(mode="json")},
        key=feedback.analysis_id,
        actor_id=principal.subject,
    )
    return FeedbackAccepted(accepted=True)


@app.get("/api/v1/metrics/summary", tags=["ai-operations"])
async def metrics_summary(http_request: Request) -> dict[str, float | int]:
    repository = get_repository()
    feedback_items = await run_in_threadpool(repository.list, "feedback")
    settings = get_settings()
    if settings.analysis_service_url and settings.work_order_service_url:
        headers = {"Authorization": http_request.headers.get("Authorization", "")}
        async with httpx.AsyncClient(timeout=15) as client:
            analyses_response, approvals_response, evaluations_response = await asyncio.gather(
                client.get(
                    f"{settings.analysis_service_url}/api/v1/analyses",
                    headers=headers,
                ),
                client.get(
                    f"{settings.work_order_service_url}/api/v1/approvals",
                    headers=headers,
                ),
                client.get(
                    f"{settings.analysis_service_url}/api/v1/evaluations/runs",
                    headers=headers,
                ),
            )
        for response in (analyses_response, approvals_response, evaluations_response):
            response.raise_for_status()
        analyses = analyses_response.json()
        approvals = approvals_response.json()
        evaluation_runs = evaluations_response.json()
    else:
        analyses = await run_in_threadpool(repository.list, "analysis")
        approvals = await run_in_threadpool(repository.list, "approval")
        evaluation_runs = await run_in_threadpool(repository.list, "evaluation_run")
    feedback_count = len(feedback_items)
    approved_count = sum(
        item.get("decision") in {"approve", "approve_with_changes"}
        for item in approvals
    )
    latest_evaluation = max(
        evaluation_runs,
        key=lambda item: str(item.get("created_at", "")),
        default={},
    )
    return {
        "analysis_count": len(analyses),
        "expert_review_rate": (
            sum(bool(item.get("expert_review_required")) for item in analyses)
            / len(analyses)
            if analyses
            else 0.0
        ),
        "cause_accuracy_average": (
            sum(item["cause_accuracy"] for item in feedback_items) / feedback_count
            if feedback_items
            else 0.0
        ),
        "action_usefulness_average": (
            sum(item["action_usefulness"] for item in feedback_items) / feedback_count
            if feedback_items
            else 0.0
        ),
        "approval_rate": approved_count / len(approvals) if approvals else 0.0,
        "cause_candidate_accuracy": latest_evaluation.get(
            "cause_candidate_accuracy", 0.0
        ),
        "document_hit_rate": latest_evaluation.get("document_hit_rate", 0.0),
        "resolution_time_reduction": latest_evaluation.get(
            "resolution_time_reduction", 0.0
        ),
        "evaluation_case_count": latest_evaluation.get("case_count", 0),
    }
