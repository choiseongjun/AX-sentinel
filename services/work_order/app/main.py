from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.concurrency import run_broker, run_database, run_storage
from shared.config import get_settings
from shared.dynamodb import get_repository
from shared.events import get_event_publisher
from shared.object_store import get_document_store
from shared.realtime import get_realtime_bus

app = create_app("work-order-service")


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    APPROVE_WITH_CHANGES = "approve_with_changes"
    REJECT = "reject"


class ApprovalRequest(BaseModel):
    analysis_id: str
    incident_id: str
    decision: ApprovalDecision
    reviewer_id: str
    comment: str = Field(min_length=3, max_length=2000)
    checklist: list[str] = Field(default_factory=list)


class WorkOrder(BaseModel):
    id: str
    incident_id: str
    analysis_id: str
    status: str
    assignee_id: str | None = None
    checklist: list[str]
    completed_items: list[str] = Field(default_factory=list)
    photo_keys: list[str] = Field(default_factory=list)
    field_note: str | None = None
    actual_cause: str | None = None
    recovery_confirmed: bool = False


class ApprovalRecord(ApprovalRequest):
    id: str


@app.post(
    "/api/v1/approvals",
    response_model=WorkOrder | ApprovalRecord,
    status_code=status.HTTP_201_CREATED,
    tags=["approval"],
)
async def decide_action_plan(
    request: ApprovalRequest,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> WorkOrder | ApprovalRecord:
    approval = ApprovalRecord(id=str(uuid4()), **request.model_dump())
    await run_database(get_repository().put, "approval", approval.id, approval)
    await run_broker(
        get_event_publisher().publish,
        "approval.decided",
        approval.model_dump(mode="json"),
        key=approval.incident_id,
        actor_id=principal.subject,
    )

    if request.decision == ApprovalDecision.REJECT:
        return approval
    if request.decision == ApprovalDecision.APPROVE_WITH_CHANGES and not request.checklist:
        raise HTTPException(
            status_code=422,
            detail="A modified approval requires an updated checklist",
        )
    work_order = WorkOrder(
        id=str(uuid4()),
        incident_id=request.incident_id,
        analysis_id=request.analysis_id,
        status="open",
        checklist=request.checklist
        or [
            "작업 전 설비 에너지 차단 상태 확인",
            "권장 점검 항목 수행",
            "사진과 작업 메모 등록",
            "시험 가동 후 정상 복구 확인",
        ],
    )
    await run_database(get_repository().put, "work_order", work_order.id, work_order)
    await run_broker(
        get_event_publisher().publish,
        "work_order.created",
        work_order.model_dump(mode="json"),
        key=work_order.incident_id,
        actor_id=principal.subject,
    )
    return work_order


@app.get(
    "/api/v1/work-orders/{work_order_id}",
    response_model=WorkOrder,
    tags=["work-orders"],
)
async def get_work_order(work_order_id: str) -> WorkOrder:
    value = await run_database(get_repository().get, "work_order", work_order_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Work order not found")
    return WorkOrder.model_validate(value)


@app.get("/api/v1/work-orders", response_model=list[WorkOrder], tags=["work-orders"])
async def list_work_orders() -> list[WorkOrder]:
    values = await run_database(get_repository().list, "work_order")
    return [WorkOrder.model_validate(value) for value in values]


@app.get("/api/v1/approvals", response_model=list[ApprovalRecord], tags=["approval"])
async def list_approvals() -> list[ApprovalRecord]:
    values = await run_database(get_repository().list, "approval")
    return [ApprovalRecord.model_validate(value) for value in values]


class WorkOrderCompletion(BaseModel):
    completed_items: list[str]
    photo_keys: list[str] = Field(min_length=1)
    field_note: str = Field(min_length=3, max_length=4000)
    actual_cause: str = Field(min_length=3, max_length=2000)
    recovery_confirmed: bool


class WorkEvidence(BaseModel):
    key: str
    filename: str
    content_type: str


@app.post(
    "/api/v1/work-orders/{work_order_id}/evidence",
    response_model=WorkEvidence,
    status_code=status.HTTP_201_CREATED,
    tags=["work-orders"],
)
async def upload_work_evidence(
    work_order_id: str,
    file: UploadFile,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.FIELD_WORKER, Role.SYSTEM_ADMIN)),
    ],
) -> WorkEvidence:
    value = await run_database(get_repository().get, "work_order", work_order_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Work order not found")

    content_type = file.content_type or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image evidence is accepted")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Evidence image exceeds 10 MiB")

    safe_name = PurePosixPath(file.filename or "evidence.jpg").name
    key = f"work-evidence/{work_order_id}/{uuid4()}-{safe_name}"
    await run_storage(
        get_document_store().put,
        key=key,
        body=content,
        content_type=content_type,
    )
    return WorkEvidence(key=key, filename=safe_name, content_type=content_type)


@app.post(
    "/api/v1/work-orders/{work_order_id}/complete",
    response_model=WorkOrder,
    tags=["work-orders"],
)
async def complete_work_order(
    work_order_id: str,
    completion: WorkOrderCompletion,
    http_request: Request,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.FIELD_WORKER, Role.SYSTEM_ADMIN)),
    ],
) -> WorkOrder:
    value = await run_database(get_repository().get, "work_order", work_order_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Work order not found")
    if not completion.recovery_confirmed:
        raise HTTPException(status_code=409, detail="Recovery must be confirmed")
    work_order = WorkOrder.model_validate(value)
    missing_items = set(work_order.checklist) - set(completion.completed_items)
    if missing_items:
        raise HTTPException(
            status_code=409,
            detail={"message": "Checklist is incomplete", "missing": sorted(missing_items)},
        )

    work_order.status = "resolved"
    work_order.completed_items = completion.completed_items
    work_order.photo_keys = completion.photo_keys
    work_order.field_note = completion.field_note
    work_order.actual_cause = completion.actual_cause
    work_order.recovery_confirmed = True
    repository = get_repository()
    await run_database(repository.put, "work_order", work_order.id, work_order)
    settings = get_settings()
    if settings.incident_service_url:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.patch(
                f"{settings.incident_service_url}/api/v1/incidents/"
                f"{work_order.incident_id}/status",
                headers={"Authorization": http_request.headers.get("Authorization", "")},
                json={"status": "resolved"},
            )
        response.raise_for_status()
    else:
        incident = await run_database(repository.get, "incident", work_order.incident_id)
        if incident is not None:
            incident["status"] = "resolved"
            await run_database(
                repository.put,
                "incident",
                work_order.incident_id,
                incident,
            )
            if settings.websocket_broker == "redis":
                await get_realtime_bus().publish("ax-sentinel.incidents", incident)
    await run_broker(
        get_event_publisher().publish,
        "work_order.completed",
        work_order.model_dump(mode="json"),
        key=work_order.incident_id,
        actor_id=principal.subject,
    )
    return work_order
