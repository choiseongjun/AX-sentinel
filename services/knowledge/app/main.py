import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from shared.api import create_app
from shared.auth import Principal, Role, require_roles
from shared.dynamodb import get_repository
from shared.events import get_event_publisher
from shared.object_store import get_document_store
from shared.rag import RetrievedChunk, get_retriever, start_ingestion_job

app = create_app("knowledge-service")


class DocumentType(StrEnum):
    MANUAL = "manual"
    INCIDENT_CASE = "incident_case"
    PROCEDURE = "procedure"


class Document(BaseModel):
    id: str
    filename: str
    document_type: DocumentType
    indexing_status: str
    s3_key: str
    version: str
    uploaded_at: datetime


@app.post(
    "/api/v1/documents",
    response_model=Document,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["documents"],
)
async def upload_document(
    file: UploadFile,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
    document_type: DocumentType = DocumentType.MANUAL,
) -> Document:
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Document exceeds the 20 MiB limit")

    document_id = str(uuid4())
    safe_name = PurePosixPath(file.filename or "unnamed").name
    s3_key = f"documents/{document_id}/{safe_name}"
    document = Document(
        id=document_id,
        filename=safe_name,
        document_type=document_type,
        indexing_status="queued",
        s3_key=s3_key,
        version=f"sha256:{hashlib.sha256(content).hexdigest()}",
        uploaded_at=datetime.now(UTC),
    )
    await run_in_threadpool(
        get_document_store().put,
        key=s3_key,
        body=content,
        content_type=file.content_type or "application/octet-stream",
    )
    searchable_suffixes = {".txt", ".md", ".csv", ".json", ".log"}
    search_text = (
        content.decode("utf-8", errors="replace")
        if PurePosixPath(safe_name).suffix.casefold() in searchable_suffixes
        else ""
    )
    record = document.model_dump(mode="json") | {"search_text": search_text}
    await run_in_threadpool(get_repository().put, "document", document.id, record)
    await run_in_threadpool(
        get_event_publisher().publish,
        "document.registered",
        document.model_dump(mode="json"),
        key=document.id,
        actor_id=principal.subject,
    )
    return document


@app.get("/api/v1/documents/by-id/{document_id}", response_model=Document, tags=["documents"])
async def get_document(document_id: str) -> Document:
    value = await run_in_threadpool(get_repository().get, "document", document_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return Document.model_validate(value)


@app.get(
    "/api/v1/documents/search",
    response_model=list[RetrievedChunk],
    tags=["documents"],
)
async def search_documents(q: str, limit: int = 5) -> list[RetrievedChunk]:
    return await run_in_threadpool(get_retriever().retrieve, q, min(max(limit, 1), 20))


class IngestionJobAccepted(BaseModel):
    ingestion_job_id: str
    status: str


@app.post(
    "/api/v1/documents/sync",
    response_model=IngestionJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["documents"],
)
async def sync_documents(
    _: Annotated[
        Principal,
        Depends(require_roles(Role.OPERATOR_MANAGER, Role.SYSTEM_ADMIN)),
    ],
) -> IngestionJobAccepted:
    try:
        job = await run_in_threadpool(start_ingestion_job)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return IngestionJobAccepted(
        ingestion_job_id=job["ingestionJobId"],
        status=job["status"],
    )
