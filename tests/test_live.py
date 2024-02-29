import datetime as dt
import json

import boto3
import pytest
from botocore.stub import Stubber

from cfn_drift_report import cli, live

STACK_ID = "arn:aws:cloudformation:us-east-1:123456789012:stack/web-prod/5b1f0c40"
TS = dt.datetime(2025, 11, 9, 14, 2, 11, tzinfo=dt.timezone.utc)


def _client():
    # Unroutable endpoint: if a stub were ever missing, the call fails instead of reaching AWS.
    return boto3.client("cloudformation", region_name="us-east-1", endpoint_url="http://127.0.0.1:9",
                        aws_access_key_id="testing", aws_secret_access_key="testing")


def _drift(lid, status="MODIFIED", diffs=None):
    d = {"StackId": STACK_ID, "LogicalResourceId": lid, "PhysicalResourceId": f"p-{lid}",
         "ResourceType": "AWS::SQS::Queue", "StackResourceDriftStatus": status, "Timestamp": TS}
    if diffs:
        d["PropertyDifferences"] = diffs
    return d


def _status(state, drift="DRIFTED", **extra):
    resp = {"StackId": STACK_ID, "StackDriftDetectionId": "det-1", "DetectionStatus": state,
            "StackDriftStatus": drift, "Timestamp": TS}
    resp.update(extra)
    return resp


def _stub_happy_path(stub, final="DETECTION_COMPLETE"):
    stub.add_response("detect_stack_drift", {"StackDriftDetectionId": "det-1"}, {"StackName": "web-prod"})
    stub.add_response("describe_stack_drift_detection_status", _status("DETECTION_IN_PROGRESS"),
                      {"StackDriftDetectionId": "det-1"})
    stub.add_response("describe_stack_drift_detection_status",
                      _status(final, DriftedStackResourceCount=1, DetectionStatusReason="1 resource failed"),
                      {"StackDriftDetectionId": "det-1"})
    diff = [{"PropertyPath": "/DelaySeconds", "ExpectedValue": "20", "ActualValue": "120",
             "DifferenceType": "NOT_EQUAL"}]
    stub.add_response("describe_stack_resource_drifts",
                      {"StackResourceDrifts": [_drift("JobsQueue", diffs=diff)], "NextToken": "page2"},
                      {"StackName": "web-prod"})
    stub.add_response("describe_stack_resource_drifts",
                      {"StackResourceDrifts": [_drift("Role", status="IN_SYNC")]},
                      {"StackName": "web-prod", "NextToken": "page2"})


def test_detect_polls_and_paginates():
    client = _client()
    sleeps = []
    with Stubber(client) as stub:
        _stub_happy_path(stub)
        stacks, status = live.detect(client, "web-prod", interval=2, sleep=sleeps.append)
        stub.assert_no_pending_responses()
    assert sleeps == [2]
    assert status["DetectionStatus"] == "DETECTION_COMPLETE"
    assert stacks[0].name == "web-prod"
    assert [r["LogicalResourceId"] for r in stacks[0].resources] == ["JobsQueue", "Role"]


def test_detection_failed_still_returns_results():
    client = _client()
    logs = []
    with Stubber(client) as stub:
        _stub_happy_path(stub, final="DETECTION_FAILED")
        stacks, status = live.detect(client, "web-prod", sleep=lambda s: None, log=logs.append)
    assert status["DetectionStatus"] == "DETECTION_FAILED"
    assert any("1 resource failed" in m for m in logs)
    assert len(stacks[0].resources) == 2


def test_wait_times_out():
    client = _client()
    now = [0.0]

    def sleep(s):
        now[0] += s

    with Stubber(client) as stub:
        for _ in range(3):
            stub.add_response("describe_stack_drift_detection_status", _status("DETECTION_IN_PROGRESS"))
        with pytest.raises(live.DetectionError, match="still in progress"):
            live.wait_for_detection(client, "det-1", timeout=10, interval=5, sleep=sleep, clock=lambda: now[0])


def test_cli_detect_with_injected_client(tmp_path, capsys):
    client = _client()
    with Stubber(client) as stub:
        _stub_happy_path(stub)
        code = cli.main(["--detect", "web-prod", "--interval", "0", "--save-dir", str(tmp_path), "-f", "json"],
                        client_factory=lambda region, profile: client)
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["resources_drifted"] == 1
    saved = json.loads((tmp_path / "web-prod.json").read_text())
    assert len(saved["StackResourceDrifts"]) == 2
    # the saved file can be re-read offline and gives the same result
    assert cli.main([str(tmp_path), "-f", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["resources_drifted"] == 1


def test_cli_api_error_exits_2(capsys):
    client = _client()
    with Stubber(client) as stub:
        stub.add_client_error("detect_stack_drift", "ValidationError", "Stack with id nope does not exist")
        code = cli.main(["--detect", "nope"], client_factory=lambda region, profile: client)
    assert code == 2
    assert "does not exist" in capsys.readouterr().err
