import os
from pathlib import Path

import pytest

# Fail closed: never let a test reach real AWS.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ["AWS_CONFIG_FILE"] = os.devnull
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def examples():
    return EXAMPLES


def record(lid="Res", status="MODIFIED", rtype="AWS::SQS::Queue", diffs=(), stack="web-prod"):
    rec = {
        "StackId": f"arn:aws:cloudformation:us-east-1:123456789012:stack/{stack}/abc",
        "LogicalResourceId": lid,
        "PhysicalResourceId": f"phys-{lid}",
        "ResourceType": rtype,
        "StackResourceDriftStatus": status,
        "Timestamp": "2025-11-09T14:02:11+00:00",
    }
    if diffs:
        rec["PropertyDifferences"] = [
            {"PropertyPath": p, "ExpectedValue": e, "ActualValue": a, "DifferenceType": t}
            for p, e, a, t in diffs
        ]
    return rec
