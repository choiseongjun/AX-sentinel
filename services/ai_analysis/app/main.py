from enum import StrEnum
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.dynamodb import get_repository
from shared.rag import get_retriever

from .engine import get_analysis_engine
from .policy import evaluate_review_policy

app = create_app("ai-analysis-service")


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnalysisRequest(BaseModel):
    incident_id: str
    equipment_id: str
    sensor_summary: str
    log_summary: str
    related_document_ids: list[str] = Field(default_factory=list)


class CauseCandidate(BaseModel):
    cause: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]


class ActionStep(BaseModel):
    sequence: int
    instruction: str
    hazardous: bool
    requires_shutdown: bool


class AnalysisResult(BaseModel):
    id: str
    incident_id: str
    risk_level: RiskLevel
    confidence: float
    causes: list[CauseCandidate]
    related_document_ids: list[str]
    recommended_actions: list[ActionStep]
    expert_review_required: bool
    manager_approval_required: bool
    review_reasons: list[str]
    executable: bool = False


@app.post("/api/v1/analyses", response_model=AnalysisResult, tags=["analysis"])
async def analyze_incident(
    request: AnalysisRequest,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> AnalysisResult:
    retrieval_query = f"{request.sensor_summary}\n{request.log_summary}"
    retrieved_chunks = await run_in_threadpool(
        get_retriever().retrieve,
        retrieval_query,
        5,
    )
    related_document_ids = list(
        dict.fromkeys(
            request.related_document_ids
            + [chunk.document_id for chunk in retrieved_chunks]
        )
    )
    has_documents = bool(related_document_ids)
    evidence = request.model_dump(mode="json") | {
        "related_document_ids": related_document_ids,
        "retrieved_context": [chunk.model_dump(mode="json") for chunk in retrieved_chunks],
    }
    generated = await run_in_threadpool(
        get_analysis_engine().analyze,
        evidence,
    )
    confidence = generated["confidence"]
    risk_level = RiskLevel(generated["risk_level"])
    decision = evaluate_review_policy(
        confidence=confidence,
        has_related_documents=has_documents,
        risk_level=risk_level,
    )

    result = AnalysisResult(
        id=str(uuid4()),
        incident_id=request.incident_id,
        risk_level=risk_level,
        confidence=confidence,
        causes=[CauseCandidate.model_validate(cause) for cause in generated["causes"]],
        related_document_ids=related_document_ids,
        recommended_actions=[
            ActionStep.model_validate(action)
            for action in generated["recommended_actions"]
        ],
        expert_review_required=decision.expert_review_required,
        manager_approval_required=decision.manager_approval_required,
        review_reasons=list(decision.reasons),
    )
    await run_in_threadpool(get_repository().put, "analysis", result.id, result)
    return result


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResult, tags=["analysis"])
async def get_analysis(analysis_id: str) -> AnalysisResult:
    value = await run_in_threadpool(get_repository().get, "analysis", analysis_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return AnalysisResult.model_validate(value)
