"""Live mode: run CloudFormation drift detection and fetch the results.

Drift detection does not modify stacks or resources, but DetectStackDrift does start
a detection operation, and it needs read permission on every resource type in the
stack. The client is injectable so this module is tested with botocore's Stubber.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .loader import StackDrift, group_records


class DetectionError(Exception):
    pass


def make_client(region: str | None = None, profile: str | None = None):  # pragma: no cover - thin wrapper
    try:
        import boto3
    except ImportError as exc:
        raise DetectionError("live mode needs boto3: pip install 'cfn-drift-report[aws]'") from exc
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("cloudformation")


def wait_for_detection(
    client,
    detection_id: str,
    timeout: float = 600,
    interval: float = 5,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll DescribeStackDriftDetectionStatus until the operation leaves DETECTION_IN_PROGRESS."""
    deadline = clock() + timeout
    while True:
        status = client.describe_stack_drift_detection_status(StackDriftDetectionId=detection_id)
        if status.get("DetectionStatus") != "DETECTION_IN_PROGRESS":
            return status
        if clock() >= deadline:
            raise DetectionError(f"drift detection {detection_id} still in progress after {timeout:g}s")
        sleep(interval)


def fetch_resource_drifts(client, stack_name: str) -> list[dict[str, Any]]:
    """Read every page of DescribeStackResourceDrifts for a stack."""
    records: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"StackName": stack_name}
    while True:
        page = client.describe_stack_resource_drifts(**kwargs)
        records.extend(page.get("StackResourceDrifts", []))
        token = page.get("NextToken")
        if not token:
            return records
        kwargs["NextToken"] = token


def detect(
    client,
    stack_name: str,
    timeout: float = 600,
    interval: float = 5,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda msg: None,
) -> tuple[list[StackDrift], dict[str, Any]]:
    """Start drift detection for one stack, wait for it, and return the resource drifts."""
    detection_id = client.detect_stack_drift(StackName=stack_name)["StackDriftDetectionId"]
    log(f"{stack_name}: drift detection started ({detection_id})")
    status = wait_for_detection(client, detection_id, timeout=timeout, interval=interval, sleep=sleep)
    state = status.get("DetectionStatus")
    if state == "DETECTION_FAILED":
        # Results are still available for the resources that were checked.
        log(f"{stack_name}: DETECTION_FAILED: {status.get('DetectionStatusReason', 'no reason given')}")
    else:
        log(f"{stack_name}: {state}, stack drift status {status.get('StackDriftStatus')}")
    records = fetch_resource_drifts(client, stack_name)
    return group_records(records, f"live:{stack_name}", stack_name), status


def save_records(stacks: list[StackDrift], directory: str) -> list[Path]:
    """Write records in describe-stack-resource-drifts shape so they can be re-read offline."""
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for s in stacks:
        path = out / f"{s.name}.json"
        path.write_text(
            json.dumps({"StackResourceDrifts": s.resources}, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
