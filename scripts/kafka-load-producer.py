#!/usr/bin/env python3
"""Continuously publish valid AX Sentinel telemetry envelopes through kubectl."""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, BinaryIO
from uuid import uuid4

SENSORS = (
    {
        "equipment_id": "PRESS-LOAD-001",
        "sensor_type": "bearing_temperature",
        "unit": "C",
        "threshold": 90.0,
        "baseline": 72.0,
    },
    {
        "equipment_id": "PRESS-LOAD-001",
        "sensor_type": "vibration_rms",
        "unit": "mm/s",
        "threshold": 10.0,
        "baseline": 6.2,
    },
    {
        "equipment_id": "MOTOR-LOAD-002",
        "sensor_type": "motor_current",
        "unit": "A",
        "threshold": 42.0,
        "baseline": 31.0,
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Publish valid AX Sentinel telemetry events to Kafka until Ctrl+C."
        )
    )
    parser.add_argument("--rate", type=int, default=2000, help="Target events/second")
    parser.add_argument(
        "--topic",
        default="ax.telemetry.events.v1",
        help="Existing Kafka topic",
    )
    parser.add_argument("--namespace", default="ax-sentinel")
    parser.add_argument("--pod", default="kafka-0")
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=0,
        help="0 runs until Ctrl+C",
    )
    parser.add_argument(
        "--anomaly-percent",
        type=float,
        default=5.0,
        help="Percentage of generated readings above the threshold",
    )
    args = parser.parse_args()
    if args.rate < 1:
        parser.error("--rate must be at least 1")
    if args.duration_seconds < 0:
        parser.error("--duration-seconds cannot be negative")
    if not 0 <= args.anomaly_percent <= 100:
        parser.error("--anomaly-percent must be between 0 and 100")
    return args


def kubectl_command(*args: str) -> list[str]:
    executable = shutil.which("kubectl")
    if executable is None:
        raise RuntimeError("kubectl was not found in PATH")
    return [executable, *args]


def ensure_ready(namespace: str, pod: str, topic: str) -> None:
    readiness = subprocess.run(
        kubectl_command(
            "wait",
            "--namespace",
            namespace,
            f"pod/{pod}",
            "--for=condition=Ready",
            "--timeout=30s",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    if readiness.returncode != 0:
        detail = readiness.stderr.strip().splitlines()
        reason = detail[-1] if detail else "Kubernetes API is unavailable"
        raise RuntimeError(
            f"Kafka Pod is not ready ({reason}). Start Docker Desktop and "
            "deploy LocalStack EKS with scripts/local-eks.ps1 first."
        )
    result = subprocess.run(
        kubectl_command(
            "exec",
            "--namespace",
            namespace,
            pod,
            "--",
            "/opt/kafka/bin/kafka-topics.sh",
            "--bootstrap-server",
            "kafka:9092",
            "--describe",
            "--topic",
            topic,
        ),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Kafka topic does not exist: {topic}")


def start_console_producer(
    namespace: str,
    pod: str,
    topic: str,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        kubectl_command(
            "exec",
            "-i",
            "--namespace",
            namespace,
            pod,
            "--",
            "/opt/kafka/bin/kafka-console-producer.sh",
            "--bootstrap-server",
            "kafka:9092",
            "--topic",
            topic,
            "--producer-property",
            "acks=1",
            "--producer-property",
            "batch.size=131072",
            "--producer-property",
            "linger.ms=10",
            "--producer-property",
            "compression.type=lz4",
            "--producer-property",
            "client.id=ax-sentinel-load-producer",
        ),
        stdin=subprocess.PIPE,
    )


def create_event(rng: random.Random, anomaly_percent: float) -> dict[str, Any]:
    sensor = rng.choice(SENSORS)
    is_anomaly = rng.random() < anomaly_percent / 100
    if is_anomaly:
        measured_value = sensor["threshold"] * rng.uniform(1.01, 1.35)
    else:
        measured_value = sensor["baseline"] * rng.uniform(0.94, 1.06)
    measured_value = round(measured_value, 2)
    status = (
        "critical"
        if measured_value >= sensor["threshold"] * 1.2
        else "warning"
        if measured_value >= sensor["threshold"]
        else "normal"
    )
    occurred_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    telemetry_id = str(uuid4())
    return {
        "event_id": str(uuid4()),
        "event_type": "telemetry.received",
        "event_version": 1,
        "occurred_at": occurred_at,
        "producer": "kafka-load-producer",
        "correlation_id": telemetry_id,
        "causation_id": None,
        "actor_id": "load-test",
        "payload": {
            "id": telemetry_id,
            "equipment_id": sensor["equipment_id"],
            "sensor_type": sensor["sensor_type"],
            "measured_value": measured_value,
            "unit": sensor["unit"],
            "threshold": sensor["threshold"],
            "status": status,
            "received_at": occurred_at,
            "log_excerpt": (
                f"{sensor['sensor_type']} load-test "
                f"{'threshold exceeded' if is_anomaly else 'sample received'}"
            ),
        },
    }


def write_batch(
    stream: BinaryIO,
    count: int,
    rng: random.Random,
    anomaly_percent: float,
) -> None:
    payload = "".join(
        json.dumps(
            create_event(rng, anomaly_percent),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
        for _ in range(count)
    )
    stream.write(payload.encode("utf-8"))
    stream.flush()


def run(args: argparse.Namespace) -> int:
    ensure_ready(args.namespace, args.pod, args.topic)
    producer = start_console_producer(args.namespace, args.pod, args.topic)
    if producer.stdin is None:
        raise RuntimeError("Could not open the Kafka producer input stream")

    rng = random.Random()
    started_at = time.perf_counter()
    last_report_at = started_at
    last_report_count = 0
    sent_count = 0
    max_batch = max(1, args.rate // 10)
    interrupted = False

    print(
        f"Publishing to {args.topic} at {args.rate:,} events/sec. "
        "Press Ctrl+C to stop.",
        flush=True,
    )
    try:
        while True:
            now = time.perf_counter()
            elapsed = now - started_at
            if args.duration_seconds and elapsed >= args.duration_seconds:
                break

            expected_count = int(elapsed * args.rate)
            pending = min(max_batch, expected_count - sent_count)
            if pending > 0:
                write_batch(producer.stdin, pending, rng, args.anomaly_percent)
                sent_count += pending
            else:
                time.sleep(0.002)

            now = time.perf_counter()
            if now - last_report_at >= 1:
                interval = now - last_report_at
                interval_count = sent_count - last_report_count
                actual_rate = interval_count / interval
                print(
                    f"rate={actual_rate:,.0f}/s total={sent_count:,} "
                    f"elapsed={now - started_at:,.1f}s",
                    flush=True,
                )
                last_report_at = now
                last_report_count = sent_count
    except KeyboardInterrupt:
        interrupted = True
        print("\nStop requested. Flushing the producer...", flush=True)
    except BrokenPipeError as exc:
        raise RuntimeError(
            "Kafka console producer stopped before the load test completed"
        ) from exc
    finally:
        with suppress(BrokenPipeError):
            producer.stdin.close()
        try:
            return_code = producer.wait(timeout=15)
        except subprocess.TimeoutExpired:
            producer.terminate()
            return_code = producer.wait(timeout=5)

    elapsed = max(time.perf_counter() - started_at, 0.001)
    print(
        f"Finished: total={sent_count:,}, average={sent_count / elapsed:,.0f}/s, "
        f"elapsed={elapsed:,.1f}s",
        flush=True,
    )
    return 0 if interrupted else return_code


def main() -> int:
    args = parse_args()
    try:
        return run(args)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Load producer failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
