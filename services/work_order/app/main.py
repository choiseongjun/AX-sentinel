from enum import StrEnum
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.dynamodb import get_repository

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
    response_model=WorkOrder,
    status_code=status.HTTP_201_CREATED,
    tags=["approval"],
)
async def decide_action_plan(
    request: ApprovalRequest,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> WorkOrder:
    approval = ApprovalRecord(id=str(uuid4()), **request.model_dump())
    await run_in_threadpool(get_repository().put, "approval", approval.id, approval)

    if request.decision == ApprovalDecision.REJECT:
        raise HTTPException(
            status_code=409,
            detail="Rejected action plans cannot create a work order",
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
    await run_in_threadpool(get_repository().put, "work_order", work_order.id, work_order)
    return work_order


@app.get(
    "/api/v1/work-orders/{work_order_id}",
    response_model=WorkOrder,
    tags=["work-orders"],
)
async def get_work_order(work_order_id: str) -> WorkOrder:
    value = await run_in_threadpool(get_repository().get, "work_order", work_order_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Work order not found")
    return WorkOrder.model_validate(value)


@app.get("/api/v1/work-orders", response_model=list[WorkOrder], tags=["work-orders"])
async def list_work_orders() -> list[WorkOrder]:
    values = await run_in_threadpool(get_repository().list, "work_order")
    return [WorkOrder.model_validate(value) for value in values]


class WorkOrderCompletion(BaseModel):
    completed_items: list[str]
    photo_keys: list[str] = Field(min_length=1)
    field_note: str = Field(min_length=3, max_length=4000)
    actual_cause: str = Field(min_length=3, max_length=2000)
    recovery_confirmed: bool


@app.post(
    "/api/v1/work-orders/{work_order_id}/complete",
    response_model=WorkOrder,
    tags=["work-orders"],
)
async def complete_work_order(
    work_order_id: str,
    completion: WorkOrderCompletion,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.FIELD_WORKER, Role.SYSTEM_ADMIN)),
    ],
) -> WorkOrder:
    value = await run_in_threadpool(get_repository().get, "work_order", work_order_id)
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
    await run_in_threadpool(get_repository().put, "work_order", work_order.id, work_order)
    return work_order
