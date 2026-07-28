from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, Field

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.concurrency import run_database
from shared.dynamodb import get_repository

app = create_app("asset-service")


class Equipment(BaseModel):
    id: str
    name: str
    line: str
    model: str
    status: str
    last_seen_at: datetime


class MaintenanceRecordRequest(BaseModel):
    performed_at: datetime
    action: str = Field(min_length=3, max_length=2000)
    actual_cause: str | None = Field(default=None, max_length=2000)
    technician: str = Field(min_length=2, max_length=200)
    parts_replaced: list[str] = Field(default_factory=list)
    outcome: str = Field(min_length=2, max_length=1000)


class MaintenanceRecord(MaintenanceRecordRequest):
    id: str
    equipment_id: str


@app.get("/api/v1/equipment", response_model=list[Equipment], tags=["equipment"])
async def list_equipment() -> list[Equipment]:
    values = await run_database(get_repository().list, "equipment")
    if not values:
        seed = Equipment(
            id="PRESS-001",
            name="1호 프레스",
            line="프레스 A라인",
            model="AXP-500",
            status="warning",
            last_seen_at=datetime.now(UTC),
        )
        await run_database(get_repository().put, "equipment", seed.id, seed)
        return [seed]
    return [Equipment.model_validate(value) for value in values]


@app.get("/api/v1/equipment/{equipment_id}", response_model=Equipment, tags=["equipment"])
async def get_equipment(equipment_id: str) -> Equipment:
    value = await run_database(get_repository().get, "equipment", equipment_id)
    if value is None and equipment_id == "PRESS-001":
        await list_equipment()
        value = await run_database(get_repository().get, "equipment", equipment_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return Equipment.model_validate(value)


@app.post(
    "/api/v1/equipment/{equipment_id}/maintenance",
    response_model=MaintenanceRecord,
    status_code=status.HTTP_201_CREATED,
    tags=["maintenance"],
)
async def create_maintenance_record(
    equipment_id: str,
    request: MaintenanceRecordRequest,
    _: Annotated[
        Principal,
        Depends(require_roles(Role.FIELD_WORKER, Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> MaintenanceRecord:
    await get_equipment(equipment_id)
    record = MaintenanceRecord(
        id=str(uuid4()),
        equipment_id=equipment_id,
        **request.model_dump(),
    )
    await run_database(get_repository().put, "maintenance", record.id, record)
    return record


@app.get(
    "/api/v1/equipment/{equipment_id}/maintenance",
    response_model=list[MaintenanceRecord],
    tags=["maintenance"],
)
async def list_maintenance_records(equipment_id: str) -> list[MaintenanceRecord]:
    values = await run_database(get_repository().list, "maintenance")
    records = [
        MaintenanceRecord.model_validate(value)
        for value in values
        if value.get("equipment_id") == equipment_id
    ]
    return sorted(records, key=lambda item: item.performed_at, reverse=True)
