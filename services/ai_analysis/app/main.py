from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.config import get_settings
from shared.dynamodb import get_repository
from shared.rag import RetrievedChunk, get_retriever

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


class AnalysisAudit(BaseModel):
    ai_provider: str
    model_id: str | None = None
    prompt_version: str
    prompt_hash: str
    rag_provider: str
    document_versions: dict[str, str]
    guardrail_id: str | None = None
    guardrail_version: str | None = None
    guardrail_action: str
    request_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    created_at: datetime


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
    audit: AnalysisAudit | None = None
    executable: bool = False


class ReviewStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    DISMISSED = "dismissed"


class ExpertReviewCase(BaseModel):
    id: str
    analysis_id: str
    incident_id: str
    status: ReviewStatus
    reasons: list[str]
    risk_level: RiskLevel
    confidence: float
    assignee_id: str | None = None
    resolution_note: str | None = None
    created_at: datetime
    updated_at: datetime


class ExpertReviewUpdate(BaseModel):
    status: ReviewStatus | None = None
    assignee_id: str | None = Field(default=None, max_length=200)
    resolution_note: str | None = Field(default=None, max_length=4000)


class EvaluationCase(BaseModel):
    id: str
    name: str
    equipment_id: str
    sensor_summary: str
    log_summary: str
    expected_causes: list[str] = Field(min_length=1)
    expected_document_ids: list[str] = Field(default_factory=list)
    baseline_resolution_minutes: float = Field(gt=0)
    actual_resolution_minutes: float = Field(ge=0)


class EvaluationDataset(BaseModel):
    cases: list[EvaluationCase] = Field(min_length=1)


class EvaluationCaseResult(BaseModel):
    case_id: str
    cause_match: float
    document_hit_rate: float
    resolution_time_reduction: float


class EvaluationRun(BaseModel):
    id: str
    created_at: datetime
    ai_provider: str
    model_id: str | None = None
    prompt_version: str
    case_count: int
    cause_candidate_accuracy: float
    document_hit_rate: float
    resolution_time_reduction: float
    cases: list[EvaluationCaseResult]


async def _analysis_context(
    request: AnalysisRequest,
) -> tuple[dict[str, Any], list[RetrievedChunk], list[str], dict[str, str]]:
    retrieval_query = f"{request.sensor_summary}\n{request.log_summary}"
    retrieved_chunks = await run_in_threadpool(
        get_retriever().retrieve,
        retrieval_query,
        5,
    )
    repository = get_repository()
    equipment = await run_in_threadpool(repository.get, "equipment", request.equipment_id)
    maintenance_values = await run_in_threadpool(repository.list, "maintenance")
    maintenance_history = [
        value
        for value in maintenance_values
        if value.get("equipment_id") == request.equipment_id
    ]
    related_document_ids = list(
        dict.fromkeys(
            request.related_document_ids
            + [chunk.document_id for chunk in retrieved_chunks]
        )
    )
    document_versions = {
        chunk.document_id: chunk.document_version or "unknown"
        for chunk in retrieved_chunks
    }
    for document_id in related_document_ids:
        if document_id in document_versions:
            continue
        document = await run_in_threadpool(repository.get, "document", document_id)
        document_versions[document_id] = (
            str(document.get("version", "unknown")) if document else "unknown"
        )
    evidence = request.model_dump(mode="json") | {
        "equipment": equipment,
        "maintenance_history": maintenance_history,
        "related_document_ids": related_document_ids,
        "retrieved_context": [chunk.model_dump(mode="json") for chunk in retrieved_chunks],
    }
    return evidence, retrieved_chunks, related_document_ids, document_versions


async def _generate(
    request: AnalysisRequest,
) -> tuple[dict[str, Any], list[RetrievedChunk], list[str], AnalysisAudit]:
    evidence, chunks, related_document_ids, document_versions = await _analysis_context(request)
    generated = await run_in_threadpool(get_analysis_engine().analyze, evidence)
    engine_audit = generated.pop("_audit", {})
    settings = get_settings()
    audit = AnalysisAudit(
        ai_provider=str(engine_audit.get("ai_provider", settings.ai_provider)),
        model_id=engine_audit.get("model_id") or settings.bedrock_model_id,
        prompt_version=str(engine_audit.get("prompt_version", "unknown")),
        prompt_hash=str(engine_audit.get("prompt_hash", "unknown")),
        rag_provider=settings.rag_provider,
        document_versions=document_versions,
        guardrail_id=settings.bedrock_guardrail_id,
        guardrail_version=settings.bedrock_guardrail_version,
        guardrail_action=str(engine_audit.get("guardrail_action", "unknown")),
        request_id=engine_audit.get("request_id"),
        input_tokens=int(engine_audit.get("input_tokens", 0)),
        output_tokens=int(engine_audit.get("output_tokens", 0)),
        created_at=datetime.now(UTC),
    )
    return generated, chunks, related_document_ids, audit


@app.post("/api/v1/analyses", response_model=AnalysisResult, tags=["analysis"])
async def analyze_incident(
    request: AnalysisRequest,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> AnalysisResult:
    generated, _, related_document_ids, audit = await _generate(request)
    confidence = generated["confidence"]
    risk_level = RiskLevel(generated["risk_level"])
    decision = evaluate_review_policy(
        confidence=confidence,
        has_related_documents=bool(related_document_ids),
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
        audit=audit,
    )
    repository = get_repository()
    await run_in_threadpool(repository.put, "analysis", result.id, result)
    if result.expert_review_required:
        now = datetime.now(UTC)
        review = ExpertReviewCase(
            id=str(uuid4()),
            analysis_id=result.id,
            incident_id=result.incident_id,
            status=ReviewStatus.PENDING,
            reasons=result.review_reasons,
            risk_level=result.risk_level,
            confidence=result.confidence,
            created_at=now,
            updated_at=now,
        )
        await run_in_threadpool(repository.put, "expert_review", review.id, review)
    return result


@app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisResult, tags=["analysis"])
async def get_analysis(analysis_id: str) -> AnalysisResult:
    value = await run_in_threadpool(get_repository().get, "analysis", analysis_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return AnalysisResult.model_validate(value)


@app.get("/api/v1/expert-reviews", response_model=list[ExpertReviewCase], tags=["review"])
async def list_expert_reviews(
    review_status: Annotated[ReviewStatus | None, Query(alias="status")] = None,
) -> list[ExpertReviewCase]:
    values = await run_in_threadpool(get_repository().list, "expert_review")
    reviews = [ExpertReviewCase.model_validate(value) for value in values]
    if review_status is not None:
        reviews = [review for review in reviews if review.status == review_status]
    return sorted(reviews, key=lambda review: review.updated_at, reverse=True)


@app.patch(
    "/api/v1/expert-reviews/{review_id}",
    response_model=ExpertReviewCase,
    tags=["review"],
)
async def update_expert_review(
    review_id: str,
    update: ExpertReviewUpdate,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> ExpertReviewCase:
    repository = get_repository()
    value = await run_in_threadpool(repository.get, "expert_review", review_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Expert review not found")
    review = ExpertReviewCase.model_validate(value)
    if update.assignee_id is not None:
        review.assignee_id = update.assignee_id
        if update.status is None and review.status == ReviewStatus.PENDING:
            review.status = ReviewStatus.ASSIGNED
    if update.status is not None:
        review.status = update.status
    if update.resolution_note is not None:
        review.resolution_note = update.resolution_note
    if review.status == ReviewStatus.COMPLETED and not review.resolution_note:
        raise HTTPException(status_code=422, detail="Completed reviews require a note")
    review.updated_at = datetime.now(UTC)
    await run_in_threadpool(repository.put, "expert_review", review.id, review)
    return review


@app.post(
    "/api/v1/evaluations/dataset",
    response_model=list[EvaluationCase],
    status_code=status.HTTP_201_CREATED,
    tags=["evaluation"],
)
async def register_evaluation_dataset(
    dataset: EvaluationDataset,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> list[EvaluationCase]:
    repository = get_repository()
    for case in dataset.cases:
        await run_in_threadpool(repository.put, "evaluation_case", case.id, case)
    return dataset.cases


@app.get(
    "/api/v1/evaluations/dataset",
    response_model=list[EvaluationCase],
    tags=["evaluation"],
)
async def list_evaluation_dataset() -> list[EvaluationCase]:
    values = await run_in_threadpool(get_repository().list, "evaluation_case")
    return [EvaluationCase.model_validate(value) for value in values]


def _cause_match(expected: list[str], generated: list[dict[str, Any]]) -> float:
    candidates = [str(item["cause"]).casefold() for item in generated]
    matches = 0
    for expected_cause in expected:
        normalized = expected_cause.casefold()
        if any(normalized in candidate or candidate in normalized for candidate in candidates):
            matches += 1
    return matches / len(expected)


def _document_hit_rate(
    expected: list[str],
    retrieved: list[RetrievedChunk],
) -> float:
    if not expected:
        return 1.0
    matches = sum(
        any(
            reference == chunk.document_id or reference in chunk.location
            for chunk in retrieved
        )
        for reference in expected
    )
    return matches / len(expected)


@app.post("/api/v1/evaluations/run", response_model=EvaluationRun, tags=["evaluation"])
async def run_evaluation(
    _: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> EvaluationRun:
    repository = get_repository()
    values = await run_in_threadpool(repository.list, "evaluation_case")
    cases = [EvaluationCase.model_validate(value) for value in values]
    if not cases:
        raise HTTPException(status_code=409, detail="Evaluation dataset is empty")
    results: list[EvaluationCaseResult] = []
    run_audit: AnalysisAudit | None = None
    for case in cases:
        request = AnalysisRequest(
            incident_id=f"evaluation:{case.id}",
            equipment_id=case.equipment_id,
            sensor_summary=case.sensor_summary,
            log_summary=case.log_summary,
        )
        generated, chunks, _, audit = await _generate(request)
        run_audit = audit
        results.append(
            EvaluationCaseResult(
                case_id=case.id,
                cause_match=_cause_match(case.expected_causes, generated["causes"]),
                document_hit_rate=_document_hit_rate(
                    case.expected_document_ids,
                    chunks,
                ),
                resolution_time_reduction=(
                    case.baseline_resolution_minutes - case.actual_resolution_minutes
                )
                / case.baseline_resolution_minutes,
            )
        )
    count = len(results)
    run = EvaluationRun(
        id=str(uuid4()),
        created_at=datetime.now(UTC),
        ai_provider=run_audit.ai_provider if run_audit else "unknown",
        model_id=run_audit.model_id if run_audit else None,
        prompt_version=run_audit.prompt_version if run_audit else "unknown",
        case_count=count,
        cause_candidate_accuracy=sum(item.cause_match for item in results) / count,
        document_hit_rate=sum(item.document_hit_rate for item in results) / count,
        resolution_time_reduction=(
            sum(item.resolution_time_reduction for item in results) / count
        ),
        cases=results,
    )
    await run_in_threadpool(repository.put, "evaluation_run", run.id, run)
    return run


@app.get("/api/v1/evaluations/runs", response_model=list[EvaluationRun], tags=["evaluation"])
async def list_evaluation_runs() -> list[EvaluationRun]:
    values = await run_in_threadpool(get_repository().list, "evaluation_run")
    runs = [EvaluationRun.model_validate(value) for value in values]
    return sorted(runs, key=lambda run: run.created_at, reverse=True)
