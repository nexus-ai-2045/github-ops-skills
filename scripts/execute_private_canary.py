from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.command import CommandResult, CommandRunner
from github_ops.identity import parse_github_remote
from github_ops.output import configure_utf8_stdout


JST = timezone(timedelta(hours=9), name="JST")
MARKER_PATH = Path(".github/private-canary/github-ops-skills.json")
TOKEN_ENV_NAMES = {"GH_TOKEN", "GITHUB_TOKEN"}
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
BRANCH_PATTERN = re.compile(r"canary/[A-Za-z0-9._/-]+")


@dataclass(frozen=True)
class ExecutionRequest:
    target_repo: str
    repo_path: Path
    branch: str
    draft_pr_title: str
    expected_account: str
    approval_ref: str | None
    confirm_private_canary: bool
    execute: bool

    @property
    def expected_approval_ref(self) -> str:
        return f"L4-CANARY:{self.target_repo}:{self.branch}"


class CanaryExecutionError(RuntimeError):
    def __init__(self, code: str, cause: str, *, step: str, changed: bool = False) -> None:
        super().__init__(cause)
        self.code = code
        self.cause = cause
        self.step = step
        self.changed = changed


def validate_execution_request(request: ExecutionRequest) -> list[str]:
    errors: list[str] = []
    if not request.execute:
        errors.append("execute_missing")
    if not request.confirm_private_canary:
        errors.append("confirmation_missing")
    if request.approval_ref != request.expected_approval_ref:
        errors.append("approval_ref_mismatch")
    if not request.expected_account:
        errors.append("expected_account_missing")
    if not BRANCH_PATTERN.fullmatch(request.branch):
        errors.append("canary_branch_required")
    if ".." in request.branch or request.branch.endswith("/"):
        errors.append("canary_branch_invalid")
    if request.branch in {"main", "master"}:
        errors.append("protected_branch_rejected")
    if not REPOSITORY_PATTERN.fullmatch(request.target_repo):
        errors.append("target_repo_invalid")
    return errors


def _run_ok(
    runner: CommandRunner,
    argv: list[str],
    *,
    cwd: Path,
    step: str,
    changed: bool = False,
) -> CommandResult:
    result = runner.run(
        argv,
        cwd=cwd,
        timeout=60,
        unset_env=TOKEN_ENV_NAMES if argv[0] == "gh" else None,
    )
    if result.returncode != 0:
        raise CanaryExecutionError(
            "command_failed",
            result.stderr.strip() or f"command failed: {argv[0]}",
            step=step,
            changed=changed,
        )
    return result


def _parse_json(result: CommandResult, *, step: str, changed: bool = False) -> dict:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CanaryExecutionError(
            "invalid_json_evidence",
            f"{step}のJSON証跡を解析できません: {exc.msg}",
            step=step,
            changed=changed,
        ) from exc
    if not isinstance(payload, dict):
        raise CanaryExecutionError(
            "invalid_json_evidence",
            f"{step}のJSON証跡がobjectではありません",
            step=step,
            changed=changed,
        )
    return payload


def execute_private_canary(
    request: ExecutionRequest,
    *,
    runner: CommandRunner | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    validation_errors = validate_execution_request(request)
    if validation_errors:
        raise CanaryExecutionError(
            "execution_gate_blocked",
            ", ".join(validation_errors),
            step="approval-gate",
        )

    command_runner = runner or CommandRunner()
    repo_path = request.repo_path.resolve()
    recorded_at = (now or datetime.now(JST)).astimezone(JST).isoformat()
    status = _run_ok(
        command_runner,
        ["git", "status", "--porcelain=v1"],
        cwd=repo_path,
        step="clean-worktree",
    )
    if status.stdout.strip():
        raise CanaryExecutionError(
            "dirty_worktree",
            "worktreeに未保存差分があります",
            step="clean-worktree",
        )

    remote = _run_ok(
        command_runner,
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path,
        step="remote-check",
    )
    owner, name = parse_github_remote(remote.stdout.strip())
    if f"{owner}/{name}" != request.target_repo:
        raise CanaryExecutionError(
            "remote_mismatch",
            "originとtarget repositoryが一致しません",
            step="remote-check",
        )

    login = _run_ok(
        command_runner,
        ["gh", "api", "user", "--jq", ".login"],
        cwd=repo_path,
        step="identity-before",
    ).stdout.strip()
    if login != request.expected_account:
        raise CanaryExecutionError(
            "account_mismatch",
            "active accountとexpected accountが一致しません",
            step="identity-before",
        )

    repo_info = _parse_json(
        _run_ok(
            command_runner,
            [
                "gh",
                "repo",
                "view",
                request.target_repo,
                "--json",
                "nameWithOwner,visibility,viewerPermission,defaultBranchRef",
            ],
            cwd=repo_path,
            step="repo-preflight",
        ),
        step="repo-preflight",
    )
    if repo_info.get("nameWithOwner") != request.target_repo:
        raise CanaryExecutionError("repo_mismatch", "GitHub repoが一致しません", step="repo-preflight")
    if repo_info.get("visibility") != "PRIVATE":
        raise CanaryExecutionError("repo_not_private", "対象repoがPRIVATEではありません", step="repo-preflight")
    if repo_info.get("viewerPermission") not in {"WRITE", "MAINTAIN", "ADMIN"}:
        raise CanaryExecutionError("permission_insufficient", "write権限を確認できません", step="repo-preflight")
    if (repo_info.get("defaultBranchRef") or {}).get("name") != "main":
        raise CanaryExecutionError("base_branch_mismatch", "default branchがmainではありません", step="repo-preflight")

    branch_probe = command_runner.run(
        [
            "gh",
            "api",
            f"repos/{request.target_repo}/branches/{quote(request.branch, safe='')}",
        ],
        cwd=repo_path,
        unset_env=TOKEN_ENV_NAMES,
    )
    if branch_probe.returncode == 0:
        raise CanaryExecutionError("branch_already_exists", "canary branchが既に存在します", step="branch-preflight")
    branch_error = f"{branch_probe.stdout}\n{branch_probe.stderr}".lower()
    if "404" not in branch_error and "not found" not in branch_error:
        raise CanaryExecutionError(
            "branch_absence_unverified",
            "canary branchの不存在を確認できません",
            step="branch-preflight",
        )

    _run_ok(command_runner, ["git", "fetch", "origin", "main"], cwd=repo_path, step="fetch")
    _run_ok(
        command_runner,
        ["git", "switch", "--create", request.branch, "origin/main"],
        cwd=repo_path,
        step="local-branch",
    )
    marker = {
        "schema_version": "github-ops/private-canary-marker/v1",
        "recorded_at": recorded_at,
        "recorded_by": "github-ops private canary runner",
        "target_repo": request.target_repo,
        "branch": request.branch,
        "purpose": "private GitHub branch, push, Draft PR, and read-back canary",
    }
    marker_file = repo_path / MARKER_PATH
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    marker_file.write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _run_ok(command_runner, ["git", "add", "--", MARKER_PATH.as_posix()], cwd=repo_path, step="stage", changed=True)
    _run_ok(
        command_runner,
        ["git", "commit", "-m", "test: add private L4 canary marker"],
        cwd=repo_path,
        step="commit",
        changed=True,
    )
    _run_ok(
        command_runner,
        ["git", "push", "origin", f"HEAD:refs/heads/{request.branch}"],
        cwd=repo_path,
        step="push",
        changed=True,
    )

    body_file = repo_path / ".git" / "private-canary-pr-body.md"
    body_file.parent.mkdir(parents=True, exist_ok=True)
    body_file.write_text(
        "L4 private mutation canaryです。\n\n"
        "- visibility変更なし\n- main mergeなし\n- cleanupは別承認\n",
        encoding="utf-8",
    )
    pr_url = _run_ok(
        command_runner,
        [
            "gh",
            "pr",
            "create",
            "--repo",
            request.target_repo,
            "--base",
            "main",
            "--head",
            request.branch,
            "--draft",
            "--title",
            request.draft_pr_title,
            "--body-file",
            str(body_file),
        ],
        cwd=repo_path,
        step="draft-pr",
        changed=True,
    ).stdout.strip()
    read_back = _parse_json(
        _run_ok(
            command_runner,
            [
                "gh",
                "pr",
                "view",
                request.branch,
                "--repo",
                request.target_repo,
                "--json",
                "number,isDraft,state,url,headRefName,baseRefName",
            ],
            cwd=repo_path,
            step="read-back",
            changed=True,
        ),
        step="read-back",
        changed=True,
    )
    if not (
        read_back.get("isDraft") is True
        and read_back.get("state") == "OPEN"
        and read_back.get("headRefName") == request.branch
        and read_back.get("baseRefName") == "main"
    ):
        raise CanaryExecutionError(
            "read_back_mismatch",
            "Draft PR read-backが期待値と一致しません",
            step="read-back",
            changed=True,
        )
    login_after = _run_ok(
        command_runner,
        ["gh", "api", "user", "--jq", ".login"],
        cwd=repo_path,
        step="identity-after",
        changed=True,
    ).stdout.strip()
    if login_after != login:
        raise CanaryExecutionError(
            "active_account_changed",
            "active accountが実行中に変化しました",
            step="identity-after",
            changed=True,
        )
    return {
        "status": "READY",
        "code": "private_canary_verified",
        "recorded_at": recorded_at,
        "request": asdict(request) | {"repo_path": str(repo_path)},
        "changed": True,
        "verified": True,
        "pr_url": read_back.get("url") or pr_url,
        "read_back": read_back,
        "active_account_before": login,
        "active_account_after": login_after,
        "automatic_cleanup": False,
        "next_action": "人間レビュー後、Draft PR closeとremote branch削除を別々に判断",
    }


def main() -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="L4 private mutation canary executor")
    parser.add_argument("--repo", dest="repo_path", type=Path, default=Path.cwd())
    parser.add_argument("--target-repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--draft-pr-title", required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--approval-ref")
    parser.add_argument("--confirm-private-canary", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report-path", type=Path, required=True)
    args = parser.parse_args()
    request = ExecutionRequest(
        target_repo=args.target_repo,
        repo_path=args.repo_path,
        branch=args.branch,
        draft_pr_title=args.draft_pr_title,
        expected_account=args.expected_account,
        approval_ref=args.approval_ref,
        confirm_private_canary=args.confirm_private_canary,
        execute=args.execute,
    )
    try:
        payload = execute_private_canary(request)
        returncode = 0
    except CanaryExecutionError as exc:
        payload = {
            "status": "BLOCKED",
            "code": exc.code,
            "cause": exc.cause,
            "step": exc.step,
            "changed": exc.changed,
            "verified": False,
            "request": asdict(request) | {"repo_path": str(request.repo_path)},
            "next_action": (
                "外部変更が残る可能性があります。自動cleanupせず人間レビューしてください"
                if exc.changed
                else "入力と承認境界を確認してください"
            ),
        }
        returncode = 1
    payload.setdefault("schema_version", "github-ops/private-canary-execution/v1")
    payload.setdefault("recorded_at", datetime.now(JST).isoformat())
    payload.setdefault("recorded_by", "codex")
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
