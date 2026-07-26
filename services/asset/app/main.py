from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from shared.api import create_app
from shared.dynamodb import get_repository

app = create_app("asset-service")


class Equipment(BaseModel):
    id: str
    name: str
    line: str
    model: str
    status: str
    last_seen_at: datetime


@app.get("/api/v1/equipment", response_model=list[Equipment], tags=["equipment"])
async def list_equipment() -> list[Equipment]:
    values = await run_in_threadpool(get_repository().list, "equipment")
    if not values:
        seed = Equipment(
            id="PRESS-001",
            name="1호 프레스",
            line="프레스 A라인",
            model="AXP-500",
            status="warning",
            last_seen_at=datetime.now(UTC),
        )
        await run_in_threadpool(get_repository().put, "equipment", seed.id, seed)
        return [seed]
    return [Equipment.model_validate(value) for value in values]


@app.get("/api/v1/equipment/{equipment_id}", response_model=Equipment, tags=["equipment"])
async def get_equipment(equipment_id: str) -> Equipment:
    value = await run_in_threadpool(get_repository().get, "equipment", equipment_id)
    if value is None and equipment_id == "PRESS-001":
        await list_equipment()
        value = await run_in_threadpool(get_repository().get, "equipment", equipment_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return Equipment.model_validate(value)
