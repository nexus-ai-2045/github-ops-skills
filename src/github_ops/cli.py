"""Installed CLI entry points for GitHub operation gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .output import configure_utf8_stdout
from .pr_create import create_pr_with_japanese_gate
from .pr_language import check_pr_metadata


def build_check_pr_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PR title/bodyの日本語境界を確認します")
    title_source = parser.add_mutually_exclusive_group(required=True)
    title_source.add_argument("--title")
    title_source.add_argument("--title-file", type=Path)
    body_source = parser.add_mutually_exclusive_group(required=True)
    body_source.add_argument("--body")
    body_source.add_argument("--body-file", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def check_pr_japanese_main(argv: list[str] | None = None) -> int:
    args = build_check_pr_parser().parse_args(argv)
    title = args.title if args.title is not None else args.title_file.read_text(
        encoding="utf-8"
    ).rstrip("\r\n")
    body = args.body if args.body is not None else args.body_file.read_text(
        encoding="utf-8"
    )
    outcome = check_pr_metadata(title, body)
    if args.json:
        configure_utf8_stdout()
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{outcome.status.value}: {outcome.cause}")
    return 0 if outcome.status.value == "READY" else 1

def build_create_pr_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="日本語gate通過後だけPRを作成し、表示面をread-backします"
    )
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--account-map", required=True, type=Path)
    parser.add_argument("--expected-base-sha", required=True)
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument(
        "--expected-visibility",
        choices=("PRIVATE", "PUBLIC", "INTERNAL"),
        default="PRIVATE",
    )
    title_source = parser.add_mutually_exclusive_group(required=True)
    title_source.add_argument("--title")
    title_source.add_argument("--title-file", type=Path)
    parser.add_argument("--body-file", required=True, type=Path)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def create_pr_main(argv: list[str] | None = None) -> int:
    args = build_create_pr_parser().parse_args(argv)
    title = args.title if args.title is not None else args.title_file.read_text(
        encoding="utf-8"
    ).rstrip("\r\n")
    outcome = create_pr_with_japanese_gate(
        repo=args.repo,
        base=args.base,
        head=args.head,
        title=title,
        body_file=args.body_file,
        repo_root=args.repo_root,
        account_map_file=args.account_map,
        expected_base_sha=args.expected_base_sha,
        expected_head_sha=args.expected_head_sha,
        expected_visibility=args.expected_visibility,
        confirmed=args.confirm,
        draft=args.draft,
    )
    if args.json:
        configure_utf8_stdout()
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{outcome.status.value}: {outcome.cause}")
        if url := outcome.evidence.get("url"):
            print(f"PR: {url}")
    return 0 if outcome.status.value == "READY" else 1
