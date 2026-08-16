#!/usr/bin/env python3
"""Compose local work location + identity before a GitHub write.

Read-only. Does not push, create PR, switch accounts, or delete worktrees.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.output import configure_utf8_stdout
from github_ops.result import Status
from github_ops.write_preflight import evaluate_write_preflight


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--expected-owner")
    parser.add_argument("--expected-login")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow dirty worktree when scope is intentionally included.",
    )
    parser.add_argument(
        "--approved-path",
        action="append",
        default=[],
        help="Dirty path allowed for this write (repeatable).",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        outcome = evaluate_write_preflight(
            args.repo,
            expected_owner=args.expected_owner,
            expected_login=args.expected_login,
            token=token,
            allow_dirty=args.allow_dirty,
            approved_paths=tuple(args.approved_path),
        )
    except (OSError, subprocess.TimeoutExpired):
        from github_ops.result import Outcome

        outcome = Outcome(
            status=Status.BLOCKED,
            code="preflight_command_failed",
            cause="gitまたはghの実行に失敗しました",
            impact="identityとdirty scopeを確認できないため書き込みを止めています",
            recovery="git/ghの利用可否と応答を確認して再実行してください",
            evidence={"repo": str(args.repo.resolve())},
        )
    configure_utf8_stdout()
    if args.json:
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{outcome.status.value}: {outcome.cause}")
        print(f"影響: {outcome.impact}")
        print(f"復旧: {outcome.recovery}")
        if outcome.evidence.get("location"):
            loc = outcome.evidence["location"]
            print(
                "場所: branch={branch} linked_worktree={linked} dirty={dirty}".format(
                    branch=loc.get("branch"),
                    linked=loc.get("is_linked_worktree"),
                    dirty=len(loc.get("dirty_paths") or []),
                )
            )
    return 0 if outcome.status is Status.READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
