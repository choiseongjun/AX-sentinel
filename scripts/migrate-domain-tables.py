"""Idempotently copy prototype single-table records into service-owned tables."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterator
from typing import Any

import boto3

ENTITY_TABLES = {
    "equipment": "axsentinel-asset",
    "maintenance": "axsentinel-asset",
    "telemetry": "axsentinel-incident",
    "incident": "axsentinel-incident",
    "analysis": "axsentinel-analysis",
    "expert_review": "axsentinel-analysis",
    "evaluation_case": "axsentinel-analysis",
    "evaluation_run": "axsentinel-analysis",
    "document": "axsentinel-knowledge",
    "approval": "axsentinel-work-order",
    "work_order": "axsentinel-work-order",
    "feedback": "axsentinel-metrics",
    "processed_event": "axsentinel-events",
}


def scan_all(table: Any) -> Iterator[dict[str, Any]]:
    request: dict[str, Any] = {}
    while True:
        response = table.scan(**request)
        yield from response.get("Items", [])
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return
        request["ExclusiveStartKey"] = last_key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="axsentinel-domain")
    parser.add_argument("--region", default="ap-northeast-2")
    parser.add_argument("--endpoint-url", default="http://localhost:4566")
    args = parser.parse_args()

    resource = boto3.resource(
        "dynamodb",
        region_name=args.region,
        endpoint_url=args.endpoint_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    source = resource.Table(args.source)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = 0
    try:
        items = scan_all(source)
        for item in items:
            target_name = ENTITY_TABLES.get(str(item.get("entity_type", "")))
            if target_name is None:
                skipped += 1
                continue
            item.setdefault("version", 1)
            grouped[target_name].append(item)
    except resource.meta.client.exceptions.ResourceNotFoundException:
        print(f"Source table {args.source!r} does not exist; nothing to migrate.")
        return
    copied = 0
    for target_name, target_items in grouped.items():
        with resource.Table(target_name).batch_writer(
            overwrite_by_pkeys=["pk", "sk"]
        ) as batch:
            for item in target_items:
                batch.put_item(Item=item)
                copied += 1
    print(f"Copied {copied} records; skipped {skipped} unknown records.")


if __name__ == "__main__":
    main()
