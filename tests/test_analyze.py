import pytest

from cfn_drift_report.analyze import IGNORED, IgnoreRule, analyze, analyze_resource, load_ignore_file, parse_value
from cfn_drift_report.loader import InputError, StackDrift
from conftest import record


def test_parse_value_decodes_json_strings():
    assert parse_value("20") == 20
    assert parse_value('{"a":1}') == {"a": 1}
    assert parse_value("null") is None
    assert parse_value("Enabled") == "Enabled"
    assert parse_value(None) is None


def test_numeric_delta():
    res = analyze_resource(record(diffs=[("/DelaySeconds", "20", "120", "NOT_EQUAL")]), [])
    assert res.changes[0].numeric_delta == (100, 500.0)


def test_numeric_delta_from_zero_and_non_numeric():
    res = analyze_resource(record(diffs=[("/X", "0", "5", "NOT_EQUAL"), ("/Y", "true", "false", "NOT_EQUAL"),
                                         ("/Z", "a", "b", "NOT_EQUAL")]), [])
    assert res.changes[0].numeric_delta == (5, None)
    assert res.changes[1].numeric_delta is None
    assert res.changes[2].numeric_delta is None


def test_ignore_rule_parsing():
    assert IgnoreRule.parse("/Tags/*") == IgnoreRule("*", "/Tags/*")
    assert IgnoreRule.parse("AWS::S3::Bucket /Tags*") == IgnoreRule("AWS::S3::Bucket", "/Tags*")
    with pytest.raises(ValueError):
        IgnoreRule.parse("a b c")


def test_all_differences_ignored_means_ignored_status():
    rec = record(rtype="AWS::Lambda::Function", diffs=[("/Tags/1", "null", '{"Key":"k"}', "ADD")])
    res = analyze_resource(rec, [IgnoreRule("AWS::Lambda::Function", "/Tags/*")])
    assert res.effective_status == IGNORED and not res.drifted


def test_partial_ignore_still_drifted():
    rec = record(diffs=[("/Tags/1", "null", "{}", "ADD"), ("/DelaySeconds", "1", "2", "NOT_EQUAL")])
    res = analyze_resource(rec, [IgnoreRule.parse("/Tags/*")])
    assert res.drifted
    assert [c.ignored for c in res.changes] == [True, False]


def test_rule_type_mismatch_does_not_ignore():
    rec = record(rtype="AWS::SQS::Queue", diffs=[("/Tags/1", "null", "{}", "ADD")])
    assert analyze_resource(rec, [IgnoreRule("AWS::S3::*", "/Tags/*")]).drifted


def test_deleted_and_unknown():
    deleted = analyze_resource(record(status="DELETED"), [])
    unknown = analyze_resource(record(status="UNKNOWN"), [])
    assert deleted.drifted and not unknown.drifted


def test_modified_without_differences_stays_modified():
    assert analyze_resource(record(), [IgnoreRule.parse("*")]).effective_status == "MODIFIED"


def test_analyze_sorts_drifted_first_and_counts():
    stack = StackDrift("s", resources=[record("A", status="IN_SYNC"), record("B", status="DELETED")])
    result = analyze([stack])[0]
    assert [r.logical_id for r in result.resources] == ["B", "A"]
    assert result.counts == {"DELETED": 1, "IN_SYNC": 1}
    assert result.drifted


def test_ignore_file(tmp_path, examples):
    rules = load_ignore_file(str(examples / "ignore.txt"))
    assert rules == [IgnoreRule("AWS::Lambda::Function", "/Tags/*")]
    bad = tmp_path / "bad.txt"
    bad.write_text("one two three\n")
    with pytest.raises(InputError, match="bad.txt:1"):
        load_ignore_file(str(bad))
