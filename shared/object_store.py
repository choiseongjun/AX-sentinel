from functools import lru_cache

import boto3

from shared.config import get_settings


class DocumentObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
        )

    def put(self, *, key: str, body: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )


@lru_cache
def get_document_store() -> DocumentObjectStore:
    settings = get_settings()
    return DocumentObjectStore(
        bucket=settings.documents_bucket,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )
