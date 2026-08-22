#!/usr/bin/env python3
"""Fail-closed PR review-thread resolve gated by the existing audit judge.

Uses `github_ops.review_threads` only. Does not invent a close protocol.
Unresolved or unjudgeable threads stay open and are surfaced as materials.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.output import configure_utf8_stdout
from github_ops.review_thread_resolve import run_resolve


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Repository in owner/name format.")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number.")
    parser.add_argument(
        "--thread-id",
        action="append",
        default=None,
        dest="thread_ids",
        help="Optional proposed thread ID (repeatable). Unresolved IDs stay open.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply only IDs authorized by the existing audit judge.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    args = parse_args(argv)
    proposed = tuple(args.thread_ids) if args.thread_ids else None
    result = run_resolve(
        args.repo,
        args.pr,
        proposed_thread_ids=proposed,
        apply=args.apply,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "decision={decision} applied={applied} materials={count}".format(
                decision=result["decision"],
                applied=result["applied"],
                count=len(result["materials"]),
            )
        )
        for item in result["materials"]:
            state = item.get("state") or item.get("kind") or "material"
            title = item.get("title") or item.get("message") or item.get("id") or ""
            print(f"{state}: {title}")
    if result["decision"] == "ready":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
