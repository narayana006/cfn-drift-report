import json

from cfn_drift_report.analyze import IgnoreRule, analyze
from cfn_drift_report.loader import StackDrift
from cfn_drift_report.render import fmt_value, render_json, render_markdown, render_text
from conftest import record


def _results(rules=()):
    recs = [
        record("Queue", diffs=[("/DelaySeconds", "20", "120", "NOT_EQUAL")]),
        record("Bucket", rtype="AWS::S3::Bucket", diffs=[("/Tags/1", "null", '{"Key":"a|b"}', "ADD"),
                                                         ("/Logging", '{"Prefix":"x"}', "null", "REMOVE")]),
        record("Topic", status="DELETED", rtype="AWS::SNS::Topic"),
        record("Role", status="IN_SYNC", rtype="AWS::IAM::Role"),
    ]
    return analyze([StackDrift("web-prod", "arn:...:stack/web-prod/x", recs)], list(rules))


def test_text_report():
    out = render_text(_results())
    assert "web-prod: DRIFTED (2 modified, 1 deleted, 1 in sync)" in out
    assert '~ /DelaySeconds  20 -> 120  (+100, +500%)' in out
    assert '+ /Tags/1  added {"Key":"a|b"}' in out
    assert '- /Logging  removed (expected {"Prefix":"x"})' in out
    assert "x Topic  AWS::SNS::Topic" in out
    assert "Role" not in out
    assert out.rstrip().endswith("1 stack checked, 1 drifted, 3 drifted resources")


def test_text_all_shows_in_sync_and_hidden_count():
    out = render_text(_results([IgnoreRule.parse("/Tags/*")]), show_all=True)
    assert "= Role  AWS::IAM::Role" in out
    assert "(1 ignored difference hidden)" in out


def test_value_truncation():
    assert fmt_value("x" * 200, limit=20).endswith("...")
    assert len(fmt_value("x" * 200, limit=20)) == 20


def test_markdown_escapes_pipes():
    md = render_markdown(_results())
    assert md.startswith("# CloudFormation drift report")
    assert "| web-prod | **DRIFTED** |" in md
    assert "a\\|b" in md
    assert "## web-prod" in md


def test_json_report():
    data = json.loads(render_json(_results()))
    assert data["stacks_drifted"] == 1 and data["resources_drifted"] == 3
    queue = next(r for r in data["stacks"][0]["resources"] if r["logical_id"] == "Queue")
    assert queue["differences"][0] == {"path": "/DelaySeconds", "type": "NOT_EQUAL", "expected": 20,
                                       "actual": 120, "ignored": False, "delta": 100}


def test_in_sync_stack_text():
    res = analyze([StackDrift("ok", resources=[record(status="IN_SYNC")])])
    out = render_text(res)
    assert out.startswith("ok: IN_SYNC (1 in sync)")
    assert "0 drifted" in out
