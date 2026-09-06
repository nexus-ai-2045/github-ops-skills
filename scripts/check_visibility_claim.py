from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.output import configure_utf8_stdout
from github_ops.visibility_claim import evaluate_visibility_claim


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PUBLIC_READYのvisibility宣言と未ログインHTTP観測を照合します。networkは呼びません。"
    )
    parser.add_argument(
        "--public-ready",
        required=True,
        type=Path,
        help=(
            "visibility宣言 (状態: 行) を含むfile。PREFLIGHT.mdか旧PUBLIC_READY.md"
        ),
    )
    parser.add_argument("--status-code", required=True, type=int)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    text = args.public_ready.read_text(encoding="utf-8")
    outcome = evaluate_visibility_claim(text, args.status_code)
    if args.json:
        configure_utf8_stdout()
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{outcome.status.value}: {outcome.cause}")
    return 0 if outcome.status.value == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
