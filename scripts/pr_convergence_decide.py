#!/usr/bin/env python3
"""PR収束snapshotから、安全な次の1手だけを判定するread-only CLI。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from github_ops.pr_convergence import ConvergenceSnapshot, decide_next_step


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", nargs="?", help="JSON file。省略時はstdin")
    args = parser.parse_args()
    try:
        raw = Path(args.snapshot).read_text(encoding="utf-8") if args.snapshot else sys.stdin.read()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("snapshotはJSON objectである必要があります")
        outcome = decide_next_step(ConvergenceSnapshot(**payload))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(json.dumps({
            "status": "UNKNOWN",
            "code": "invalid_snapshot",
            "cause": f"snapshotを安全に解釈できません: {type(exc).__name__}",
            "impact": "mergeは実行しません",
            "recovery": "schemaに沿ったUTF-8 JSONを渡してください",
            "evidence": {"schema": "github-ops/pr-convergence/v1"},
        }, ensure_ascii=False))
        return 1
    print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    return 0 if outcome.status.value == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
