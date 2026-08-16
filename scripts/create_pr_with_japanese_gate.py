from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.output import configure_utf8_stdout
from github_ops.pr_create import create_pr_with_japanese_gate


def build_parser() -> argparse.ArgumentParser:
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
        help="確認済みの期待visibility。既定はPRIVATEです",
    )
    title_source = parser.add_mutually_exclusive_group(required=True)
    title_source.add_argument("--title")
    title_source.add_argument("--title-file", type=Path)
    parser.add_argument("--body-file", required=True, type=Path)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="現在の会話でPR作成承認を得た場合だけ指定します",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    title = (
        args.title
        if args.title is not None
        else args.title_file.read_text(encoding="utf-8").rstrip("\r\n")
    )
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


if __name__ == "__main__":
    raise SystemExit(main())
