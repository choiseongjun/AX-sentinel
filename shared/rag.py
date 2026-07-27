from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlencode

import boto3
import httpx
from pydantic import BaseModel, Field

from shared.config import get_settings
from shared.dynamodb import get_repository


class RetrievedChunk(BaseModel):
    content: str
    score: float = Field(ge=0, le=1)
    location: str
    document_id: str
    document_version: str | None = None


class Retriever(Protocol):
    def retrieve(
        self,
        query: str,
        limit: int = 5,
        authorization: str | None = None,
    ) -> list[RetrievedChunk]: ...


class LocalRetriever:
    def retrieve(
        self,
        query: str,
        limit: int = 5,
        authorization: str | None = None,
    ) -> list[RetrievedChunk]:
        settings = get_settings()
        if settings.knowledge_service_url:
            headers = {"Authorization": authorization} if authorization else {}
            response = httpx.get(
                f"{settings.knowledge_service_url}/api/v1/documents/search?"
                f"{urlencode({'q': query, 'limit': limit})}",
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            return [RetrievedChunk.model_validate(item) for item in response.json()]
        terms = {term.casefold() for term in query.split() if len(term) >= 2}
        ranked: list[tuple[int, dict[str, Any]]] = []
        for document in get_repository().list("document"):
            haystack = (
                f"{document.get('filename', '')} {document.get('search_text', '')}".casefold()
            )
            matches = sum(term in haystack for term in terms)
            if matches:
                ranked.append((matches, document))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            RetrievedChunk(
                content=document.get("search_text") or document["filename"],
                score=min(1.0, matches / max(len(terms), 1)),
                location=f"s3://local/{document['s3_key']}",
                document_id=document["id"],
                document_version=document.get("version"),
            )
            for matches, document in ranked[:limit]
        ]


class BedrockKnowledgeBaseRetriever:
    def __init__(self, *, region: str, knowledge_base_id: str) -> None:
        self._knowledge_base_id = knowledge_base_id
        self._client = boto3.client("bedrock-agent-runtime", region_name=region)

    def retrieve(
        self,
        query: str,
        limit: int = 5,
        authorization: str | None = None,
    ) -> list[RetrievedChunk]:
        response = self._client.retrieve(
            knowledgeBaseId=self._knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": limit,
                    "overrideSearchType": "HYBRID",
                }
            },
        )
        chunks: list[RetrievedChunk] = []
        for result in response.get("retrievalResults", []):
            location = result.get("location", {})
            s3_uri = location.get("s3Location", {}).get("uri", "unknown")
            chunks.append(
                RetrievedChunk(
                    content=result["content"].get("text", ""),
                    score=result.get("score", 0),
                    location=s3_uri,
                    document_id=s3_uri.rsplit("/", 1)[-1],
                    document_version=result.get("metadata", {}).get("documentVersion"),
                )
            )
        return chunks


@lru_cache
def get_retriever() -> Retriever:
    settings = get_settings()
    if settings.rag_provider == "local":
        return LocalRetriever()
    if settings.rag_provider == "bedrock":
        if not settings.bedrock_knowledge_base_id:
            raise RuntimeError("BEDROCK_KNOWLEDGE_BASE_ID is required")
        return BedrockKnowledgeBaseRetriever(
            region=settings.aws_region,
            knowledge_base_id=settings.bedrock_knowledge_base_id,
        )
    raise RuntimeError(f"Unsupported RAG provider: {settings.rag_provider}")


def start_ingestion_job() -> dict[str, Any]:
    settings = get_settings()
    if not settings.bedrock_knowledge_base_id or not settings.bedrock_data_source_id:
        raise RuntimeError("Bedrock knowledge base and data source IDs are required")
    client = boto3.client("bedrock-agent", region_name=settings.aws_region)
    return client.start_ingestion_job(
        knowledgeBaseId=settings.bedrock_knowledge_base_id,
        dataSourceId=settings.bedrock_data_source_id,
        description="AX Sentinel document synchronization",
    )["ingestionJob"]
