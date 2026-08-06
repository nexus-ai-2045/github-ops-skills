#!/usr/bin/env python3
"""Compare this repository's skills/ SSOT against optional local runtime roots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.output import configure_utf8_stdout
from github_ops.result import Status
from github_ops.skill_drift import compare_skill_roots, drift_outcome


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--local-root",
        action="append",
        default=[],
        help="Local skills root to compare (repeatable). Example: ~/.agents/skills",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    ssot_root = (args.repo / "skills").resolve()
    reports = []
    overall = Status.READY
    if not args.local_root:
        payload = {
            "status": "UNKNOWN",
            "code": "local_root_missing",
            "cause": "--local-root が未指定です",
            "impact": "drift判定を実行しませんでした",
            "recovery": "比較したい runtime skills の path を渡してください",
            "evidence": {"ssot_skills_root": str(ssot_root)},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    for raw in args.local_root:
        local_root = Path(raw).expanduser().resolve()
        rows = compare_skill_roots(
            ssot_skills_root=ssot_root,
            local_skills_root=local_root,
        )
        outcome = drift_outcome(rows, local_root=str(local_root))
        reports.append(outcome.to_dict())
        if outcome.status is Status.BLOCKED:
            overall = Status.BLOCKED
        elif outcome.status is Status.UNKNOWN and overall is Status.READY:
            overall = Status.UNKNOWN

    payload = {
        "status": overall.value,
        "reports": reports,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if overall is Status.READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
