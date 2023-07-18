"""Turn raw StackResourceDrift records into analysed, filterable results."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .loader import InputError, StackDrift

DRIFTED = ("MODIFIED", "DELETED")
# Effective status for a MODIFIED resource whose every difference is on the ignore list.
IGNORED = "IGNORED"


@dataclass(frozen=True)
class IgnoreRule:
    """Ignore property differences whose path matches ``path_glob`` on ``type_glob`` resources."""

    type_glob: str
    path_glob: str

    @classmethod
    def parse(cls, text: str) -> "IgnoreRule":
        parts = text.split()
        if len(parts) == 1:
            return cls("*", parts[0])
        if len(parts) == 2:
            return cls(parts[0], parts[1])
        raise ValueError(f"bad ignore rule {text!r}: use 'PATH_GLOB' or 'RESOURCE_TYPE PATH_GLOB'")

    def matches(self, resource_type: str, path: str) -> bool:
        return fnmatchcase(resource_type, self.type_glob) and fnmatchcase(path, self.path_glob)


def load_ignore_file(path: str) -> list[IgnoreRule]:
    rules = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InputError(f"{path}: {exc}") from exc
    for n, line in enumerate(lines, 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            rules.append(IgnoreRule.parse(line))
        except ValueError as exc:
            raise InputError(f"{path}:{n}: {exc}") from exc
    return rules


def parse_value(raw: Any) -> Any:
    """PropertyDifference values are strings that usually hold JSON; decode when possible."""
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


@dataclass
class PropertyChange:
    path: str
    kind: str  # ADD | REMOVE | NOT_EQUAL
    expected: Any
    actual: Any
    ignored: bool = False

    @property
    def numeric_delta(self) -> tuple[float, float | None] | None:
        """(absolute change, percent change or None) when both sides are numbers."""
        e, a = self.expected, self.actual
        if isinstance(e, bool) or isinstance(a, bool):
            return None
        if isinstance(e, (int, float)) and isinstance(a, (int, float)):
            delta = a - e
            pct = (delta / e * 100) if e else None
            return delta, pct
        return None


@dataclass
class ResourceResult:
    logical_id: str
    resource_type: str
    physical_id: str
    status: str  # raw StackResourceDriftStatus
    effective_status: str  # status after ignore rules
    changes: list[PropertyChange] = field(default_factory=list)
    reason: str = ""
    timestamp: str = ""

    @property
    def drifted(self) -> bool:
        return self.effective_status in DRIFTED


@dataclass
class StackResult:
    name: str
    stack_id: str
    resources: list[ResourceResult]

    @property
    def counts(self) -> Counter:
        return Counter(r.effective_status for r in self.resources)

    @property
    def drifted_resources(self) -> list[ResourceResult]:
        return [r for r in self.resources if r.drifted]

    @property
    def drifted(self) -> bool:
        return bool(self.drifted_resources)


def analyze_resource(rec: dict[str, Any], rules: list[IgnoreRule]) -> ResourceResult:
    rtype = rec.get("ResourceType", "")
    status = rec.get("StackResourceDriftStatus", "UNKNOWN")
    changes = []
    for diff in rec.get("PropertyDifferences") or []:
        path = diff.get("PropertyPath", "")
        changes.append(
            PropertyChange(
                path=path,
                kind=diff.get("DifferenceType", "NOT_EQUAL"),
                expected=parse_value(diff.get("ExpectedValue")),
                actual=parse_value(diff.get("ActualValue")),
                ignored=any(rule.matches(rtype, path) for rule in rules),
            )
        )
    effective = status
    if status == "MODIFIED" and changes and all(c.ignored for c in changes):
        effective = IGNORED
    ts = rec.get("Timestamp", "")
    return ResourceResult(
        logical_id=rec["LogicalResourceId"],
        resource_type=rtype,
        physical_id=rec.get("PhysicalResourceId", ""),
        status=status,
        effective_status=effective,
        changes=changes,
        reason=rec.get("DriftStatusReason", ""),
        timestamp=str(ts) if ts else "",
    )


def analyze(stacks: list[StackDrift], rules: list[IgnoreRule] | None = None) -> list[StackResult]:
    rules = rules or []
    results = []
    for s in stacks:
        resources = [analyze_resource(r, rules) for r in s.resources]
        resources.sort(key=lambda r: (not r.drifted, r.logical_id))
        results.append(StackResult(name=s.name, stack_id=s.stack_id, resources=resources))
    return results
