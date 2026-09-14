"""マージ済みリモートbranchの削除候補をread-onlyで監査する。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.command import CommandRunner
from github_ops.identity import IdentityProbe
from github_ops.output import configure_utf8_stdout
from github_ops.result import Outcome, Status


def _unknown(code: str, cause: str, evidence: dict[str, Any] | None = None) -> Outcome:
    return Outcome(
        status=Status.UNKNOWN,
        code=code,
        cause=cause,
        impact="branch削除へ進めません",
        recovery="GitHub API応答とidentityを再確認してください",
        evidence=evidence or {},
    )


def _json_command(runner: CommandRunner, argv: list[str], repo_root: Path) -> Any | None:
    result = runner.run(
        argv,
        cwd=repo_root,
        scoped_env={"GH_HOST": "github.com"},
        redact_stdout=False,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _flatten_pages(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    rows: list[dict[str, Any]] = []
    for page in value:
        if isinstance(page, list):
            if not all(isinstance(item, dict) for item in page):
                return None
            rows.extend(page)
        elif isinstance(page, dict):
            rows.append(page)
        else:
            return None
    return rows


def audit_remote_branches(
    runner: CommandRunner,
    repo_root: Path,
    repository: str,
    *,
    expected_owner: str,
    expected_login: str,
) -> Outcome:
    identity = IdentityProbe(runner).probe(
        repo_root,
        expected_owner=expected_owner,
        expected_login=expected_login,
        token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"),
    )
    if identity.status is not Status.READY:
        return identity

    repo_info = _json_command(
        runner,
        ["gh", "repo", "view", repository, "--json", "nameWithOwner,defaultBranchRef"],
        repo_root,
    )
    if not isinstance(repo_info, dict) or repo_info.get("nameWithOwner") != repository:
        return _unknown("repository_unverified", "対象repositoryを確認できません")
    default_ref = repo_info.get("defaultBranchRef")
    default_branch = default_ref.get("name") if isinstance(default_ref, dict) else None
    if not isinstance(default_branch, str) or not default_branch:
        return _unknown("default_branch_unverified", "default branchを確認できません")

    branches_raw = _json_command(
        runner,
        ["gh", "api", "--paginate", "--slurp", f"repos/{repository}/branches?per_page=100"],
        repo_root,
    )
    branches = _flatten_pages(branches_raw)
    if branches is None:
        return _unknown("branches_unverified", "remote branch一覧を確認できません")
    prs = _json_command(
        runner,
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repository,
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "number,state,headRefName,headRefOid,mergedAt",
        ],
        repo_root,
    )
    if not isinstance(prs, list) or not all(isinstance(pr, dict) for pr in prs):
        return _unknown("pull_requests_unverified", "PR一覧を確認できません")

    by_head: dict[str, list[dict[str, Any]]] = {}
    for pr in prs:
        name = pr.get("headRefName")
        if isinstance(name, str):
            by_head.setdefault(name, []).append(pr)

    rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for branch in branches:
        name = branch.get("name")
        sha = (branch.get("commit") or {}).get("sha")
        if not isinstance(name, str) or not isinstance(sha, str):
            return _unknown("branch_shape_invalid", "remote branchの応答形式を確認できません")
        if name == default_branch:
            classification = "default_branch"
        elif branch.get("protected"):
            classification = "protected_branch"
        else:
            matches = by_head.get(name, [])
            merged = [pr for pr in matches if pr.get("state") == "MERGED"]
            exact = [pr for pr in merged if pr.get("headRefOid") == sha]
            if exact:
                classification = "merged_head_exact"
                candidate = {"branch": name, "sha": sha, "pr": exact[0].get("number")}
                candidates.append(candidate)
            elif merged:
                classification = "merged_head_changed"
            elif matches:
                classification = "pr_not_merged"
            else:
                classification = "no_pr_evidence"
        rows.append({"branch": name, "sha": sha, "classification": classification})

    return Outcome(
        status=Status.READY,
        code="remote_branch_audit_ready",
        cause="remote branchの削除候補をread-onlyで分類しました",
        impact="候補は人間確認後に別の削除操作へ渡せます",
        recovery="候補の対象・SHA・PRを確認し、削除承認を取得してください",
        evidence={
            "repository": repository,
            "default_branch": default_branch,
            "candidates": candidates,
            "branches": rows,
            "mutation_performed": False,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-owner", required=True)
    parser.add_argument("--expected-login", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    outcome = audit_remote_branches(
        CommandRunner(),
        args.repo_root,
        args.repo,
        expected_owner=args.expected_owner,
        expected_login=args.expected_login,
    )
    if args.json:
        configure_utf8_stdout()
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{outcome.status.value}: {outcome.cause}")
    return 0 if outcome.status is Status.READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
