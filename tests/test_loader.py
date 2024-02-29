import json

import pytest

from cfn_drift_report.loader import InputError, load_path, load_text, merge_stacks, stack_name_from_id
from conftest import record


def test_stack_name_from_arn():
    arn = "arn:aws:cloudformation:us-east-1:123456789012:stack/web-prod/5b1f0c40"
    assert stack_name_from_id(arn) == "web-prod"
    assert stack_name_from_id("plain") == "plain"


def test_load_api_response_shape():
    text = json.dumps({"StackResourceDrifts": [record("A"), record("B")], "NextToken": None})
    stacks = load_text(text, "f.json", "f")
    assert len(stacks) == 1
    assert stacks[0].name == "web-prod"
    assert [r["LogicalResourceId"] for r in stacks[0].resources] == ["A", "B"]


def test_bare_list_and_list_of_pages():
    pages = [{"StackResourceDrifts": [record("A")]}, {"StackResourceDrifts": [record("B")]}]
    assert len(load_text(json.dumps(pages), "p", "p")[0].resources) == 2
    assert len(load_text(json.dumps([record("A")]), "l", "l")[0].resources) == 1


def test_one_file_with_two_stacks_is_split():
    recs = [record("A", stack="one"), record("B", stack="two")]
    names = sorted(s.name for s in load_text(json.dumps(recs), "x", "x"))
    assert names == ["one", "two"]


def test_missing_stack_id_falls_back_to_file_stem():
    rec = record("A")
    del rec["StackId"]
    assert load_text(json.dumps([rec]), "f", "my-stack")[0].name == "my-stack"


def test_empty_result_keeps_stack():
    stacks = load_text('{"StackResourceDrifts": []}', "f", "empty-stack")
    assert stacks[0].name == "empty-stack" and stacks[0].resources == []


@pytest.mark.parametrize("text", ["not json", '{"Stacks": []}', "42", '[{"Foo": 1}]'])
def test_bad_input(text):
    with pytest.raises(InputError):
        load_text(text, "bad", "bad")


def test_load_directory(examples):
    stacks = merge_stacks(load_path(str(examples / "drifts")))
    assert [s.name for s in stacks] == ["data-prod", "web-prod"]


def test_missing_path(tmp_path):
    with pytest.raises(InputError):
        load_path(str(tmp_path / "nope.json"))
    with pytest.raises(InputError):
        load_path(str(tmp_path))  # empty directory


def test_merge_pages_saved_as_separate_files(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"StackResourceDrifts": [record("A")]}))
    (tmp_path / "b.json").write_text(json.dumps({"StackResourceDrifts": [record("B")]}))
    stacks = merge_stacks(load_path(str(tmp_path)))
    assert len(stacks) == 1 and len(stacks[0].resources) == 2
