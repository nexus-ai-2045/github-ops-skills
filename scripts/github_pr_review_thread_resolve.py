#!/usr/bin/env python3
"""Fail-closed PR review-thread resolve gated by the existing audit judge.

Uses `github_ops.review_threads` only. Does not invent a close protocol.
Unresolved or unjudgeable threads stay open and are surfaced as materials.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.identity import IdentityProbe
from github_ops.output import configure_utf8_stdout
from github_ops.result import Status
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
        help="Confirm only IDs authorized by the existing audit judge.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="現在の会話で書き込み承認を得た場合だけ --apply と併用します",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="IdentityProbe 用の local checkout（--apply 時必須）",
    )
    parser.add_argument(
        "--expected-owner",
        help="IdentityProbe の expected owner（--apply 時必須）",
    )
    parser.add_argument(
        "--expected-login",
        help="IdentityProbe の expected login（--apply 時必須）",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    return parser.parse_args(argv)


def _apply_preflight_blocked(message: str, *, code: str) -> dict:
    return {
        "decision": "error",
        "applied": False,
        "resolved": [],
        "materials": [{"kind": code, "message": message}],
        "errors": [code],
        "audit": {},
    }


def _require_write_preflight(args: argparse.Namespace) -> dict | None:
    """Reuse existing create_pr / IdentityProbe write gates before --apply."""
    if not args.apply:
        return None
    if not args.confirm:
        return _apply_preflight_blocked(
            "--apply requires current-turn --confirm",
            code="approval_missing",
        )
    gh_host = os.environ.get("GH_HOST")
    if gh_host and gh_host.casefold() != "github.com":
        return _apply_preflight_blocked(
            "GH_HOST is not github.com",
            code="github_host_mismatch",
        )
    if not args.repo_root or not args.expected_owner or not args.expected_login:
        return _apply_preflight_blocked(
            "--apply requires --repo-root, --expected-owner, and --expected-login",
            code="write_preflight_inputs_missing",
        )
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    outcome = IdentityProbe().probe(
        args.repo_root,
        expected_owner=args.expected_owner,
        expected_login=args.expected_login,
        token=token,
        expected_host="github.com",
    )
    if outcome.status is not Status.READY:
        return {
            "decision": "error",
            "applied": False,
            "resolved": [],
            "materials": [
                {
                    "kind": "identity_preflight",
                    "message": outcome.cause,
                    "code": outcome.code,
                    "status": outcome.status.value,
                }
            ],
            "errors": [outcome.code],
            "audit": {},
            "identity": outcome.to_dict(),
        }
    evidence_repo = outcome.evidence.get("repository")
    if evidence_repo != args.repo:
        return _apply_preflight_blocked(
            "identity repository does not match --repo",
            code="remote_repository_mismatch",
        )
    return None


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    args = parse_args(argv)
    blocked = _require_write_preflight(args)
    if blocked is not None:
        result = blocked
    else:
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
        for message in result.get("errors") or []:
            print(f"error: {message}")
        for item in result["materials"]:
            state = item.get("state") or item.get("kind") or "material"
            title = item.get("title") or item.get("message") or item.get("id") or ""
            print(f"{state}: {title}")
    if result["decision"] == "ready":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
