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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GitHub identityをread-onlyで観測します。"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--expected-owner")
    parser.add_argument("--expected-login")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    probe = IdentityProbe()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    outcome = probe.probe(
        args.repo,
        expected_owner=args.expected_owner,
        expected_login=args.expected_login,
        token=token,
    )
    if args.json:
        configure_utf8_stdout()
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{outcome.status.value}: {outcome.cause}")
        print(f"影響: {outcome.impact}")
        print(f"復旧: {outcome.recovery}")
    return 0 if outcome.status.value == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
