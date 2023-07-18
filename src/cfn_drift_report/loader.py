"""Load describe-stack-resource-drifts output from files or directories.

Accepted shapes for each JSON file:

* the CLI / API response: ``{"StackResourceDrifts": [...], "NextToken": ...}``
* a bare list of StackResourceDrift objects
* a list of responses (for example several saved pages for one stack)
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


class InputError(Exception):
    """Raised when an input file cannot be read or has an unexpected shape."""


@dataclass
class StackDrift:
    """All resource drift records for one stack."""

    name: str
    stack_id: str = ""
    resources: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""


def stack_name_from_id(stack_id: str) -> str:
    """Extract the stack name from a stack ARN.

    ``arn:aws:cloudformation:us-east-1:123456789012:stack/web-prod/uuid`` -> ``web-prod``
    """
    if ":stack/" in stack_id:
        return stack_id.split(":stack/", 1)[1].split("/", 1)[0]
    return stack_id


def _records(data: Any, source: str) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        if "StackResourceDrifts" in data:
            records = data["StackResourceDrifts"]
        elif "LogicalResourceId" in data:
            records = [data]
        else:
            raise InputError(f"{source}: expected a 'StackResourceDrifts' key")
    elif isinstance(data, list):
        records = []
        for item in data:
            if isinstance(item, dict) and "StackResourceDrifts" in item:
                records.extend(item["StackResourceDrifts"])
            else:
                records.append(item)
    else:
        raise InputError(f"{source}: expected a JSON object or list")
    for rec in records:
        if not isinstance(rec, dict) or "LogicalResourceId" not in rec:
            raise InputError(f"{source}: every drift record needs a LogicalResourceId")
    return records


def group_records(records: Iterable[dict[str, Any]], source: str, fallback_name: str) -> list[StackDrift]:
    """Group drift records by StackId (one file may hold several stacks)."""
    stacks: dict[str, StackDrift] = {}
    for rec in records:
        stack_id = rec.get("StackId", "")
        key = stack_id or fallback_name
        if key not in stacks:
            name = stack_name_from_id(stack_id) if stack_id else fallback_name
            stacks[key] = StackDrift(name=name, stack_id=stack_id, source=source)
        stacks[key].resources.append(rec)
    if not stacks:
        # an empty result is still a stack worth listing as "no records"
        stacks[fallback_name] = StackDrift(name=fallback_name, source=source)
    return list(stacks.values())


def load_text(text: str, source: str, fallback_name: str) -> list[StackDrift]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"{source}: invalid JSON ({exc})") from exc
    return group_records(_records(data, source), source, fallback_name)


def load_path(path: str) -> list[StackDrift]:
    """Load one file, a directory of *.json files, or '-' for stdin."""
    if path == "-":
        return load_text(sys.stdin.read(), "<stdin>", "stdin")
    p = Path(path)
    if p.is_dir():
        files = sorted(p.glob("*.json"))
        if not files:
            raise InputError(f"{path}: no *.json files in directory")
    elif p.is_file():
        files = [p]
    else:
        raise InputError(f"{path}: no such file or directory")
    stacks: list[StackDrift] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError as exc:
            raise InputError(f"{f}: {exc}") from exc
        stacks.extend(load_text(text, str(f), f.stem))
    return stacks


def merge_stacks(stacks: list[StackDrift]) -> list[StackDrift]:
    """Merge entries for the same stack (e.g. paginated output saved as separate files)."""
    merged: dict[str, StackDrift] = {}
    for s in stacks:
        key = s.stack_id or s.name
        if key in merged:
            merged[key].resources.extend(s.resources)
        else:
            merged[key] = StackDrift(s.name, s.stack_id, list(s.resources), s.source)
    return sorted(merged.values(), key=lambda s: s.name)
