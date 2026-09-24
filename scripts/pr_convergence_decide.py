#!/usr/bin/env python3
"""PR収束snapshotから、安全な次の1手だけを判定するread-only CLI。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.pr_convergence import (
    ConvergenceSnapshot,
    checks_state_from_jobs,
    decide_next_step,
)
from github_ops.output import configure_utf8_stdout


def _resolve_ci(payload: dict) -> dict:
    """``ci_jobs`` (Actions Jobs API の job 一覧) から checks_state を導く。

    jobs を渡す場合は ``workflow_files_changed`` (bool) が必須で、
    ``checks_state`` との併用は曖昧なので拒否する。
    """
    if "ci_jobs" not in payload:
        return payload
    payload = dict(payload)
    jobs = payload.pop("ci_jobs")
    changed = payload.pop("workflow_files_changed", None)
    if "checks_state" in payload:
        raise ValueError("ci_jobsとchecks_stateは併用できません")
    if not isinstance(jobs, list) or not all(isinstance(j, dict) for j in jobs):
        raise ValueError("ci_jobsはobjectの配列である必要があります")
    if not isinstance(changed, bool):
        raise ValueError("ci_jobsにはworkflow_files_changed(bool)が必要です")
    payload["checks_state"] = checks_state_from_jobs(
        jobs, workflow_files_changed=changed
    )
    return payload


def main() -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", nargs="?", help="JSON file。省略時はstdin")
    args = parser.parse_args()
    try:
        raw = Path(args.snapshot).read_text(encoding="utf-8") if args.snapshot else sys.stdin.read()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("snapshotはJSON objectである必要があります")
        outcome = decide_next_step(ConvergenceSnapshot(**_resolve_ci(payload)))
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
