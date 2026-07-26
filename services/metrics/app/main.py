from typing import Annotated
from uuid import uuid4

from fastapi import Depends
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.dynamodb import get_repository

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
    _: Annotated[
        Principal,
        Depends(require_roles(Role.FIELD_WORKER, Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> FeedbackAccepted:
    await run_in_threadpool(get_repository().put, "feedback", str(uuid4()), feedback)
    return FeedbackAccepted(accepted=True)


@app.get("/api/v1/metrics/summary", tags=["ai-operations"])
async def metrics_summary() -> dict[str, float | int]:
    feedback_items = await run_in_threadpool(get_repository().list, "feedback")
    if not feedback_items:
        return {
            "analysis_count": 0,
            "expert_review_rate": 0.0,
            "cause_accuracy_average": 0.0,
            "action_usefulness_average": 0.0,
        }

    count = len(feedback_items)
    return {
        "analysis_count": count,
        "expert_review_rate": 0.0,
        "cause_accuracy_average": sum(item["cause_accuracy"] for item in feedback_items) / count,
        "action_usefulness_average": (
            sum(item["action_usefulness"] for item in feedback_items) / count
        ),
    }
