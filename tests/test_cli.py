import json

import pytest

from cfn_drift_report.cli import main


def test_examples_drift_exit_1(examples, capsys):
    assert main([str(examples / "drifts"), "--ignore-file", str(examples / "ignore.txt")]) == 1
    out = capsys.readouterr().out
    assert "web-prod: DRIFTED (3 modified, 1 deleted, 1 ignored, 2 in sync)" in out
    assert "ThumbnailFunction" not in out


def test_no_fail(examples):
    assert main([str(examples / "drifts"), "--no-fail"]) == 0


def test_in_sync_exit_0(examples, capsys):
    assert main([str(examples / "drifts" / "data-prod.json")]) == 0
    assert "data-prod: IN_SYNC" in capsys.readouterr().out


def test_ignore_flag_and_markdown_output_file(examples, tmp_path):
    out = tmp_path / "report.md"
    code = main([str(examples / "drifts" / "web-prod.json"), "-f", "markdown", "-o", str(out),
                 "--ignore", "AWS::Lambda::Function /Tags/*"])
    assert code == 1
    text = out.read_text()
    assert "## web-prod" in text and "ThumbnailFunction" not in text


def test_stdin(monkeypatch, capsys, examples):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO((examples / "drifts" / "web-prod.json").read_text()))
    assert main(["-", "-f", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["stacks"][0]["stack"] == "web-prod"


def test_bad_input_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert main([str(bad)]) == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_bad_ignore_rule_exit_2(examples):
    assert main([str(examples / "drifts"), "--ignore", "a b c"]) == 2


def test_requires_input():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
