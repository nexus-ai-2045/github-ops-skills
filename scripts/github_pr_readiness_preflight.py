from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.account_map import AccountMapError, load_account_map
from github_ops.command import CommandRunner
from github_ops.identity import IdentityProbe, parse_github_remote
from github_ops.output import configure_utf8_stdout
from github_ops.preflight import PreflightInput, run_preflight


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GitHub書き込みpreflight")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--operation",
        choices=("push", "draft-pr", "pr", "merge", "visibility"),
        required=True,
    )
    parser.add_argument("--map-file", type=Path)
    parser.add_argument("--approval-ref")
    parser.add_argument("--expected-head-sha")
    parser.add_argument("--approved-path", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = _run(args)
    if args.json:
        configure_utf8_stdout()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{payload['status']}: {payload['cause']}")
    return 0 if payload["status"] == "READY" else 1


def _run(args: argparse.Namespace) -> dict:
    if not args.map_file:
        return _blocked("account_map_missing", "account mapが指定されていません")
    try:
        account_map = load_account_map(args.map_file)
        runner = CommandRunner()
        remote = runner.run(["git", "remote", "get-url", "origin"], cwd=args.repo)
        owner, name = parse_github_remote(remote.stdout.strip())
        if remote.returncode != 0 or not owner or not name:
            return _blocked("remote_unavailable", "originを解決できません")
        repository = f"{owner}/{name}"
        resolution = account_map.resolve(repository)
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        identity = IdentityProbe(runner).probe(
            args.repo,
            expected_owner=resolution.expected_owner,
            expected_login=resolution.expected_login,
            token=token,
        )
        if identity.status.value != "READY":
            return identity.to_dict()
        view = runner.run(
            [
                "gh",
                "repo",
                "view",
                repository,
                "--json",
                "nameWithOwner,viewerPermission,visibility",
            ],
            cwd=args.repo,
            scoped_env={"GH_TOKEN": token} if token else None,
        )
        if view.returncode != 0:
            return _unknown("repo_view_unverified", "GitHub repository情報を確認できません")
        repo_info = json.loads(view.stdout)
        default_view = runner.run(
            ["gh", "repo", "view", repository, "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
            cwd=args.repo,
            scoped_env={"GH_TOKEN": token} if token else None,
        )
        if default_view.returncode != 0 or not default_view.stdout.strip():
            return _unknown("default_branch_unverified", "GitHub default branchを確認できません")
        branch = runner.run(["git", "branch", "--show-current"], cwd=args.repo)
        if branch.returncode != 0 or not branch.stdout.strip():
            return _unknown("local_branch_unverified", "local branchを確認できません")
        branch_name = branch.stdout.strip()
        local_head = runner.run(["git", "rev-parse", "HEAD"], cwd=args.repo)
        if local_head.returncode != 0 or not local_head.stdout.strip():
            return _unknown("local_head_unverified", "local HEADを確認できません")
        remote_ref = f"refs/heads/{branch_name}"
        remote = runner.run(["git", "ls-remote", "--heads", "origin", remote_ref], cwd=args.repo)
        if remote.returncode != 0:
            return _unknown("remote_head_unverified", "remote branchを確認できません")
        remote_head = remote.stdout.split("\t", 1)[0] if remote.stdout else None
        fast_forward_verified = remote_head is None
        if remote_head:
            fetch = runner.run(
                ["git", "fetch", "origin", f"+{remote_ref}:refs/remotes/origin/{branch_name}"],
                cwd=args.repo,
            )
            if fetch.returncode != 0:
                return _unknown("remote_fetch_failed", "remote branchをfetchできません")
            ancestor = runner.run(
                ["git", "merge-base", "--is-ancestor", remote_head, local_head.stdout.strip()],
                cwd=args.repo,
            )
            fast_forward_verified = ancestor.returncode == 0
        dirty = runner.run(
            ["git", "status", "--porcelain=v1", "-z"],
            cwd=args.repo,
        )
        worktree_paths = _porcelain_paths(dirty.stdout)
        return run_preflight(
            PreflightInput(
                expected_repo=repository,
                expected_owner=resolution.expected_owner,
                expected_login=resolution.expected_login,
                remote_repo=repo_info.get("nameWithOwner"),
                token_login=identity.evidence.get("login"),
                permission=repo_info.get("viewerPermission"),
                visibility=repo_info.get("visibility"),
                worktree_paths=worktree_paths,
                approved_paths=tuple(args.approved_path),
                approval_ref=args.approval_ref,
                operation=args.operation,
                expected_visibility="PRIVATE",
                branch=branch_name,
                default_branch=default_view.stdout.strip(),
                expected_head_sha=args.expected_head_sha,
                local_head_sha=local_head.stdout.strip(),
                remote_head_sha=remote_head,
                fast_forward_verified=fast_forward_verified,
            )
        ).to_dict()
    except (AccountMapError, json.JSONDecodeError) as exc:
        return _blocked("preflight_input_invalid", str(exc))


def _porcelain_paths(output: str) -> tuple[str, ...]:
    records = output.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        if not record:
            index += 1
            continue
        if len(record) < 4 or record[2] != " ":
            raise ValueError("git status porcelain record is invalid")
        paths.append(record[3:])
        if ("R" in record[:2] or "C" in record[:2]) and index + 1 < len(records):
            index += 1
            if records[index]:
                paths.append(records[index])
        index += 1
    return tuple(paths)


def _blocked(code: str, cause: str) -> dict:
    return {
        "status": "BLOCKED",
        "code": code,
        "cause": cause,
        "impact": "GitHub書き込みは実行しません",
        "recovery": "入力と一次証拠を確認してください",
        "evidence": {},
    }


def _unknown(code: str, cause: str) -> dict:
    payload = _blocked(code, cause)
    payload["status"] = "UNKNOWN"
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
