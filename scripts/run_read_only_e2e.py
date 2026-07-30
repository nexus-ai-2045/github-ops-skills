from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.account_map import AccountMapError, load_account_map
from github_ops.command import CommandRunner
from github_ops.identity import IdentityProbe
from github_ops.output import configure_utf8_stdout
from github_ops.result import Outcome, Status

REQUIRED = (
    "GITHUB_OPS_LIVE_REPO",
    "GITHUB_OPS_EXPECTED_OWNER",
    "GITHUB_OPS_ACCOUNT_MAP",
)


def required_inputs(env: Mapping[str, str]) -> Outcome:
    missing = [name for name in REQUIRED if not env.get(name)]
    if missing:
        return Outcome(Status.BLOCKED, "live_input_missing",
                       "live read-only E2Eの入力が不足しています",
                       "L3実行保証は確認できません",
                       "不足環境変数を設定して再実行してください",
                       {"missing": missing})
    return Outcome(Status.READY, "live_input_ready", "入力を確認しました",
                   "read-only照会へ進めます", "none", {"required": list(REQUIRED)})


def run_live(env: Mapping[str, str], runner: CommandRunner | None = None) -> Outcome:
    gate = required_inputs(env)
    if gate.status is not Status.READY:
        return gate
    command = runner or CommandRunner()
    repo = env["GITHUB_OPS_LIVE_REPO"]
    try:
        resolved = load_account_map(Path(env["GITHUB_OPS_ACCOUNT_MAP"])).resolve(repo)
    except AccountMapError as exc:
        return Outcome(Status.BLOCKED, "account_map_invalid", str(exc),
                       "L3実行保証は確認できません",
                       "overlayを修正してください", {})
    if resolved.expected_owner != env["GITHUB_OPS_EXPECTED_OWNER"]:
        return Outcome(Status.BLOCKED, "expected_owner_mismatch",
                       "環境変数とoverlayのownerが一致しません",
                       "GitHub照会を実行しません", "入力を修正してください", {})
    before, before_error = IdentityProbe(command).active_login()
    result = command.run([
        "gh", "repo", "view", repo,
        "--json", "nameWithOwner,visibility,viewerPermission,defaultBranchRef",
    ])
    prs = command.run(["gh", "pr", "list", "--repo", repo, "--limit", "1", "--json", "number"])
    after, after_error = IdentityProbe(command).active_login()
    if result.returncode or prs.returncode or before_error or after_error:
        return Outcome(Status.UNKNOWN, "live_read_failed",
                       "GitHub read-only照会を完了できませんでした",
                       "L3実行保証は確認できません",
                       "認証・network・対象repositoryを確認してください",
                       {"repo_returncode": result.returncode,
                        "pr_returncode": prs.returncode})
    payload = json.loads(result.stdout)
    if (
        payload.get("nameWithOwner") != repo
        or before != after
        or before != resolved.expected_login
    ):
        return Outcome(Status.BLOCKED, "live_invariant_mismatch",
                       "対象repositoryまたはactive accountの不変条件に失敗しました",
                       "L3保証を停止します", "identity設定を確認してください",
                       {"nameWithOwner": payload.get("nameWithOwner"),
                        "active_login_unchanged": before == after,
                        "expected_login": resolved.expected_login,
                        "observed_login": before})
    return Outcome(Status.READY, "live_read_only_verified",
                   "GitHub read-only照会とaccount不変を確認しました",
                   "L3 read-only実行保証を記録できます", "none",
                   {"repository": repo, "visibility": payload.get("visibility"),
                    "viewerPermission": payload.get("viewerPermission"),
                    "defaultBranch": (payload.get("defaultBranchRef") or {}).get("name"),
                    "active_login": before})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.parse_args()
    configure_utf8_stdout()
    outcome = run_live(os.environ)
    print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    return 0 if outcome.status is Status.READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
