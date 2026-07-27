from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.output import configure_utf8_stdout
from github_ops.pr_language import check_pr_metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PR title/bodyの日本語境界を確認します")
    parser.add_argument("--title", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--body")
    source.add_argument("--body-file", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    body = args.body if args.body is not None else args.body_file.read_text(encoding="utf-8")
    outcome = check_pr_metadata(args.title, body)
    if args.json:
        configure_utf8_stdout()
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{outcome.status.value}: {outcome.cause}")
    return 0 if outcome.status.value == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
