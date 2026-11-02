from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.gitops import GitOpsConfigError, RepositoryStateProbe, load_desired_state
from github_ops.output import configure_utf8_stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Git内のdesired stateとGitHub repository設定のdriftをread-onlyで検査します。"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    configure_utf8_stdout()
    try:
        desired = load_desired_state(args.config)
    except GitOpsConfigError as exc:
        print(json.dumps({"status": "UNKNOWN", "code": "gitops_config_invalid", "cause": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    outcome = RepositoryStateProbe().reconcile(desired, args.repo)
    print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    return 0 if outcome.status.value == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
