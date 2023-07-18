"""Text, Markdown and JSON renderers for analysed drift results."""

from __future__ import annotations

import json
from typing import Any

from .analyze import IGNORED, PropertyChange, ResourceResult, StackResult

STATUS_ORDER = ("MODIFIED", "DELETED", "UNKNOWN", IGNORED, "IN_SYNC", "NOT_CHECKED", "UNSUPPORTED")
RESOURCE_MARK = {"MODIFIED": "~", "DELETED": "x", "UNKNOWN": "?", IGNORED: "-", "IN_SYNC": "=", "NOT_CHECKED": "."}
CHANGE_MARK = {"ADD": "+", "REMOVE": "-", "NOT_EQUAL": "~"}


def fmt_value(value: Any, limit: int = 100) -> str:
    if isinstance(value, str):
        text = json.dumps(value)
    else:
        text = json.dumps(value, separators=(",", ":"), sort_keys=True)
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def fmt_delta(change: PropertyChange) -> str:
    nd = change.numeric_delta
    if nd is None:
        return ""
    delta, pct = nd
    d = f"{delta:+g}"
    return f"  ({d}, {pct:+.0f}%)" if pct is not None else f"  ({d})"


def fmt_change(change: PropertyChange, limit: int = 100) -> str:
    """One-line description of a property difference, without the marker."""
    if change.kind == "ADD":
        return f"{change.path}  added {fmt_value(change.actual, limit)}"
    if change.kind == "REMOVE":
        return f"{change.path}  removed (expected {fmt_value(change.expected, limit)})"
    return (
        f"{change.path}  {fmt_value(change.expected, limit)} -> {fmt_value(change.actual, limit)}"
        f"{fmt_delta(change)}"
    )


def summary_counts(stack: StackResult) -> str:
    counts = stack.counts
    parts = [f"{counts[s]} {s.lower().replace('_', ' ')}" for s in STATUS_ORDER if counts.get(s)]
    parts += [f"{n} {s.lower()}" for s, n in sorted(counts.items()) if s not in STATUS_ORDER]
    return ", ".join(parts) or "no resource records"


def _visible(stack: StackResult, show_all: bool) -> list[ResourceResult]:
    if show_all:
        return stack.resources
    return [r for r in stack.resources if r.drifted or r.effective_status == "UNKNOWN"]


def render_text(results: list[StackResult], show_all: bool = False, limit: int = 100) -> str:
    out: list[str] = []
    for stack in results:
        state = "DRIFTED" if stack.drifted else "IN_SYNC"
        out.append(f"{stack.name}: {state} ({summary_counts(stack)})")
        for res in _visible(stack, show_all):
            mark = RESOURCE_MARK.get(res.effective_status, "?")
            phys = f"  {res.physical_id}" if res.physical_id else ""
            out.append(f"  {mark} {res.logical_id}  {res.resource_type}{phys}  {res.effective_status}")
            if res.reason and res.effective_status not in ("IN_SYNC",):
                out.append(f"      reason: {res.reason}")
            hidden = 0
            for ch in res.changes:
                if ch.ignored:
                    hidden += 1
                    continue
                out.append(f"      {CHANGE_MARK.get(ch.kind, '~')} {fmt_change(ch, limit)}")
            if hidden:
                out.append(f"      ({hidden} ignored difference{'s' if hidden != 1 else ''} hidden)")
        out.append("")
    drifted = [s for s in results if s.drifted]
    n_res = sum(len(s.drifted_resources) for s in results)
    out.append(
        f"{len(results)} stack{'s' if len(results) != 1 else ''} checked, "
        f"{len(drifted)} drifted, {n_res} drifted resource{'s' if n_res != 1 else ''}"
    )
    return "\n".join(out) + "\n"


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(results: list[StackResult], show_all: bool = False, limit: int = 100) -> str:
    out = ["# CloudFormation drift report", ""]
    out.append("| Stack | Status | Resources |")
    out.append("|---|---|---|")
    for stack in results:
        state = "**DRIFTED**" if stack.drifted else "IN_SYNC"
        out.append(f"| {_md(stack.name)} | {state} | {_md(summary_counts(stack))} |")
    for stack in results:
        rows = _visible(stack, show_all)
        if not rows:
            continue
        out += ["", f"## {stack.name}", ""]
        out.append("| Resource | Type | Status | Difference |")
        out.append("|---|---|---|---|")
        for res in rows:
            changes = [c for c in res.changes if not c.ignored]
            first = f"`{_md(res.logical_id)}`"
            if res.physical_id:
                first += f" ({_md(res.physical_id)})"
            if not changes:
                detail = _md(res.reason) if res.reason else ""
                out.append(f"| {first} | {res.resource_type} | {res.effective_status} | {detail} |")
                continue
            for i, ch in enumerate(changes):
                cell = f"{ch.kind}: `{_md(fmt_change(ch, limit))}`"
                if i == 0:
                    out.append(f"| {first} | {res.resource_type} | {res.effective_status} | {cell} |")
                else:
                    out.append(f"| | | | {cell} |")
    return "\n".join(out) + "\n"


def to_dict(results: list[StackResult]) -> dict[str, Any]:
    stacks = []
    for stack in results:
        stacks.append(
            {
                "stack": stack.name,
                "stack_id": stack.stack_id,
                "drifted": stack.drifted,
                "counts": dict(sorted(stack.counts.items())),
                "resources": [
                    {
                        "logical_id": r.logical_id,
                        "resource_type": r.resource_type,
                        "physical_id": r.physical_id,
                        "status": r.status,
                        "effective_status": r.effective_status,
                        "reason": r.reason,
                        "differences": [
                            {
                                "path": c.path,
                                "type": c.kind,
                                "expected": c.expected,
                                "actual": c.actual,
                                "ignored": c.ignored,
                                **(
                                    {"delta": c.numeric_delta[0]}
                                    if c.numeric_delta is not None
                                    else {}
                                ),
                            }
                            for c in r.changes
                        ],
                    }
                    for r in stack.resources
                ],
            }
        )
    return {
        "stacks_checked": len(results),
        "stacks_drifted": sum(1 for s in results if s.drifted),
        "resources_drifted": sum(len(s.drifted_resources) for s in results),
        "stacks": stacks,
    }


def render_json(results: list[StackResult]) -> str:
    return json.dumps(to_dict(results), indent=2, default=str) + "\n"
