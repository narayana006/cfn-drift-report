"""Command-line interface for cfn-drift-report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from . import __version__
from .analyze import IgnoreRule, analyze, load_ignore_file
from .loader import InputError, load_path, merge_stacks
from .render import render_json, render_markdown, render_text

EXIT_OK, EXIT_DRIFT, EXIT_ERROR = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cfn-drift-report",
        description=(
            "Readable report from CloudFormation describe-stack-resource-drifts output. "
            "Exit status: 0 no drift, 1 drift found, 2 error."
        ),
    )
    p.add_argument("paths", nargs="*", metavar="PATH",
                   help="JSON file, directory of *.json files, or '-' for stdin")
    p.add_argument("-f", "--format", choices=["text", "markdown", "json"], default="text")
    p.add_argument("-o", "--output", metavar="FILE", help="write the report to FILE instead of stdout")
    p.add_argument("--all", action="store_true", dest="show_all",
                   help="also list IN_SYNC, NOT_CHECKED and fully ignored resources")
    p.add_argument("--ignore", action="append", default=[], metavar="RULE",
                   help="ignore differences: 'PATH_GLOB' or 'RESOURCE_TYPE PATH_GLOB' (repeatable)")
    p.add_argument("--ignore-file", metavar="FILE", help="file with one ignore rule per line")
    p.add_argument("--max-value", type=int, default=100, metavar="N",
                   help="truncate property values longer than N characters (default 100)")
    p.add_argument("--no-fail", action="store_true", help="exit 0 even when drift is found")

    live = p.add_argument_group("live mode (calls AWS)")
    live.add_argument("--detect", nargs="+", metavar="STACK",
                      help="run DetectStackDrift on these stacks, wait, then report")
    live.add_argument("--region")
    live.add_argument("--profile")
    live.add_argument("--timeout", type=float, default=600, help="seconds to wait per stack (default 600)")
    live.add_argument("--interval", type=float, default=5, help="poll interval in seconds (default 5)")
    live.add_argument("--save-dir", metavar="DIR",
                      help="save the fetched drift records as JSON for offline re-use")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None, client_factory: Callable | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.paths and not args.detect:
        parser.error("give at least one PATH, or --detect STACK")

    def log(msg: str) -> None:
        print(msg, file=sys.stderr)

    try:
        rules = [IgnoreRule.parse(r) for r in args.ignore]
        if args.ignore_file:
            rules += load_ignore_file(args.ignore_file)
        stacks = []
        for path in args.paths:
            stacks.extend(load_path(path))
        if args.detect:
            from . import live

            factory = client_factory or live.make_client
            client = factory(region=args.region, profile=args.profile)
            fetched = []
            for name in args.detect:
                found, _status = live.detect(client, name, timeout=args.timeout,
                                             interval=args.interval, log=log)
                fetched.extend(found)
            if args.save_dir:
                for path in live.save_records(fetched, args.save_dir):
                    log(f"saved {path}")
            stacks.extend(fetched)
    except (InputError, ValueError) as exc:
        log(f"cfn-drift-report: {exc}")
        return EXIT_ERROR
    except Exception as exc:  # live-mode API and credential errors
        if type(exc).__module__.startswith(("botocore", "boto3", "cfn_drift_report.live")):
            log(f"cfn-drift-report: {exc}")
            return EXIT_ERROR
        raise

    results = analyze(merge_stacks(stacks), rules)
    if args.format == "json":
        report = render_json(results)
    elif args.format == "markdown":
        report = render_markdown(results, show_all=args.show_all, limit=args.max_value)
    else:
        report = render_text(results, show_all=args.show_all, limit=args.max_value)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    drifted = any(r.drifted for r in results)
    return EXIT_DRIFT if drifted and not args.no_fail else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
