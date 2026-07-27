from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

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
        dirty = runner.run(
            ["git", "status", "--porcelain=v1"],
            cwd=args.repo,
        )
        worktree_paths = tuple(
            line[3:].strip() for line in dirty.stdout.splitlines() if len(line) >= 4
        )
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
            )
        ).to_dict()
    except (AccountMapError, json.JSONDecodeError) as exc:
        return _blocked("preflight_input_invalid", str(exc))


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
