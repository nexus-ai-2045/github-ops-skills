from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.canary_approval import ApprovalError, consume_approval, validate_approval
from github_ops.command import CommandResult, CommandRunner
from github_ops.identity import IdentityProbe, parse_github_remote
from github_ops.output import configure_utf8_stdout
from github_ops.redaction import redact


JST = timezone(timedelta(hours=9), name="JST")
MARKER_PATH = Path(".github/private-canary/github-ops-skills.json")
TOKEN_ENV_NAMES = {
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_HOST",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
}
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
    approval_file: Path | None
    thread_id: str
    confirm_private_canary: bool
    execute: bool

    @property
    def expected_approval_ref(self) -> str:
        return f"L4-CANARY:{self.target_repo}:{self.branch}"


class CanaryExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        cause: str,
        *,
        step: str,
        changed: bool = False,
        external_changed: bool = False,
    ) -> None:
        super().__init__(cause)
        self.code = code
        self.cause = cause
        self.step = step
        self.changed = changed
        self.external_changed = external_changed


class MutationJournal:
    def __init__(self, path: Path | None, request: ExecutionRequest) -> None:
        self.path = path.resolve() if path else None
        self.payload: dict[str, object] = {
            "schema_version": "github-ops/private-canary-execution/v2",
            "recorded_at": datetime.now(JST).isoformat(),
            "recorded_by": "codex",
            "status": "RUNNING",
            "request": asdict(request) | {
                "repo_path": str(request.repo_path),
                "approval_file": str(request.approval_file or ""),
            },
            "completed_steps": [],
            "changed": False,
            "external_changed": False,
            "observed": {},
            "automatic_cleanup": False,
        }

    def update(self, step: str | None = None, **values: object) -> None:
        if step:
            steps = self.payload["completed_steps"]
            assert isinstance(steps, list)
            steps.append(step)
        self.payload.update(values)
        self._write()

    def _write(self) -> None:
        if self.path is None:
            return
        text = json.dumps(self.payload, ensure_ascii=False, indent=2) + "\n"
        if redact(text) != text:
            raise CanaryExecutionError(
                "credential_material_detected",
                "execution journalにcredential形式を検出しました",
                step="journal-write",
                changed=bool(self.payload.get("changed")),
                external_changed=bool(self.payload.get("external_changed")),
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, self.path)

    def recovery_candidates(self) -> list[str]:
        candidates = [
            f"gh api repos/{self.payload['request']['target_repo']}/git/ref/heads/"
            f"{self.payload['request']['branch']}"
        ]
        observed = self.payload.get("observed")
        if isinstance(observed, dict) and observed.get("pr_number"):
            candidates.append(
                f"gh pr view {observed['pr_number']} --repo "
                f"{self.payload['request']['target_repo']}"
            )
        candidates.append("cleanup候補のclose/deleteは別承認。自動実行しない")
        return candidates


def validate_execution_request(request: ExecutionRequest) -> list[str]:
    errors: list[str] = []
    if not request.execute:
        errors.append("execute_missing")
    if not request.confirm_private_canary:
        errors.append("confirmation_missing")
    if request.approval_ref != request.expected_approval_ref:
        errors.append("approval_ref_mismatch")
    if request.approval_file is None:
        errors.append("approval_file_missing")
    if not request.thread_id:
        errors.append("thread_id_missing")
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
    external_changed: bool = False,
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
            external_changed=external_changed,
        )
    return result


def _parse_json(
    result: CommandResult,
    *,
    step: str,
    changed: bool = False,
    external_changed: bool = False,
) -> dict:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CanaryExecutionError(
            "invalid_json_evidence",
            f"{step}のJSON証跡を解析できません: {exc.msg}",
            step=step,
            changed=changed,
            external_changed=external_changed,
        ) from exc
    if not isinstance(payload, dict):
        raise CanaryExecutionError(
            "invalid_json_evidence",
            f"{step}のJSON証跡がobjectではありません",
            step=step,
            changed=changed,
            external_changed=external_changed,
        )
    return payload


def _parse_remote_sha(result: CommandResult) -> str:
    fields = result.stdout.split()
    if not fields:
        raise CanaryExecutionError(
            "remote_sha_missing",
            "remote branch SHAを取得できません",
            step="remote-sha",
            changed=True,
            external_changed=True,
        )
    return fields[0]


def _github_com_login(runner: CommandRunner, *, cwd: Path, step: str) -> str:
    return _run_ok(
        runner,
        ["gh", "api", "--hostname", "github.com", "user", "--jq", ".login"],
        cwd=cwd,
        step=step,
    ).stdout.strip()


def execute_private_canary(
    request: ExecutionRequest,
    *,
    runner: CommandRunner | None = None,
    now: datetime | None = None,
    journal: MutationJournal | None = None,
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
    current_time = (now or datetime.now(JST)).astimezone(JST)
    recorded_at = current_time.isoformat()
    execution_journal = journal or MutationJournal(None, request)
    if execution_journal.path is not None:
        try:
            execution_journal.path.relative_to(repo_path)
        except ValueError:
            pass
        else:
            raise CanaryExecutionError(
                "report_path_inside_repo",
                "execution reportはrepository外へ保存してください",
                step="journal-preflight",
            )
    executor_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    executor_commit = _run_ok(
        command_runner,
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        step="executor-commit",
    ).stdout.strip()
    approval_key = os.environ.get("GITHUB_OPS_CANARY_APPROVAL_KEY", "")
    try:
        approval = validate_approval(
            request.approval_file or Path("<missing>"),
            key=approval_key,
            now=current_time,
            expected={
                "target_repo": request.target_repo,
                "branch": request.branch,
                "operation": "push_and_create_draft_pr",
                "executor_sha256": executor_sha256,
                "executor_commit": executor_commit,
                "expected_account": request.expected_account,
                "draft_pr_title": request.draft_pr_title,
                "thread_id": request.thread_id,
            },
        )
    except ApprovalError as exc:
        raise CanaryExecutionError(
            "approval_artifact_invalid", str(exc), step="approval-artifact"
        ) from exc
    execution_journal.update(
        "approval-validated",
        executor_sha256=executor_sha256,
        executor_commit=executor_commit,
        approval_nonce=approval["nonce"],
    )
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
    execution_journal.update("clean-worktree")

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

    identity = IdentityProbe(command_runner).probe(
        repo_path,
        expected_owner=owner,
        expected_login=request.expected_account,
    )
    if identity.status.value != "READY":
        raise CanaryExecutionError(
            "identity_probe_blocked",
            identity.cause,
            step="identity-before",
        )
    login = str(identity.evidence["login"])
    github_com_login = _github_com_login(
        command_runner, cwd=repo_path, step="github-com-identity-before"
    )
    if github_com_login != request.expected_account:
        raise CanaryExecutionError(
            "github_com_account_mismatch",
            "github.com loginがexpected accountと一致しません",
            step="github-com-identity-before",
        )
    author_name = _run_ok(
        command_runner,
        ["git", "config", "--get", "user.name"],
        cwd=repo_path,
        step="git-author",
    ).stdout.strip()
    author_email = _run_ok(
        command_runner,
        ["git", "config", "--get", "user.email"],
        cwd=repo_path,
        step="git-author",
    ).stdout.strip()
    if not author_name or not author_email:
        raise CanaryExecutionError(
            "git_author_missing", "Git authorを確認できません", step="git-author"
        )
    credential = command_runner.run(
        ["git", "config", "--get", "credential.https://github.com.username"],
        cwd=repo_path,
    )
    credential_username = credential.stdout.strip() if credential.returncode == 0 else ""
    if credential_username != request.expected_account:
        raise CanaryExecutionError(
            "credential_username_unverified",
            "repo-local GitHub credential usernameがexpected accountと一致しません",
            step="credential-username",
        )
    execution_journal.update(
        "identity-before",
        observed={
            "remote_repo": request.target_repo,
            "active_login": login,
            "github_com_login": github_com_login,
            "git_author_name": author_name,
            "git_author_email": author_email,
            "credential_username": credential_username,
        },
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
    execution_journal.update("repo-preflight", repo_info=repo_info)

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
    execution_journal.update("branch-absent-before")

    _run_ok(command_runner, ["git", "fetch", "origin", "main"], cwd=repo_path, step="fetch")
    base_sha = _run_ok(
        command_runner,
        ["git", "rev-parse", "origin/main"],
        cwd=repo_path,
        step="base-sha",
    ).stdout.strip()
    marker_probe = _run_ok(
        command_runner,
        ["git", "ls-tree", "-r", "--name-only", "origin/main", "--", MARKER_PATH.as_posix()],
        cwd=repo_path,
        step="marker-preflight",
    )
    if marker_probe.stdout.strip():
        raise CanaryExecutionError(
            "marker_already_exists",
            "origin/mainにcanary markerが既に存在します",
            step="marker-preflight",
        )
    execution_journal.update("fetch-and-marker-absent", base_sha=base_sha)
    _run_ok(
        command_runner,
        ["git", "switch", "--create", request.branch, "origin/main"],
        cwd=repo_path,
        step="local-branch",
    )
    execution_journal.update("local-branch", changed=True)
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
    execution_journal.update("marker-written", changed=True)
    _run_ok(command_runner, ["git", "add", "--", MARKER_PATH.as_posix()], cwd=repo_path, step="stage", changed=True)
    _run_ok(
        command_runner,
        ["git", "commit", "-m", "test: add private L4 canary marker"],
        cwd=repo_path,
        step="commit",
        changed=True,
    )
    local_sha = _run_ok(
        command_runner,
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        step="commit-sha",
        changed=True,
    ).stdout.strip()
    execution_journal.update("commit", changed=True, local_commit_sha=local_sha)
    identity_before_push = IdentityProbe(command_runner).probe(
        repo_path,
        expected_owner=owner,
        expected_login=request.expected_account,
    )
    if identity_before_push.status.value != "READY":
        raise CanaryExecutionError(
            "identity_drift_before_push",
            identity_before_push.cause,
            step="identity-before-push",
            changed=True,
        )
    github_com_login_before_push = _github_com_login(
        command_runner, cwd=repo_path, step="github-com-identity-before-push"
    )
    if github_com_login_before_push != request.expected_account:
        raise CanaryExecutionError(
            "github_com_identity_drift_before_push",
            "github.com loginがpush直前に変化しました",
            step="github-com-identity-before-push",
            changed=True,
        )
    push_remote = _run_ok(
        command_runner,
        ["git", "remote", "get-url", "--push", "origin"],
        cwd=repo_path,
        step="push-remote-before-push",
        changed=True,
    )
    push_owner, push_name = parse_github_remote(push_remote.stdout.strip())
    if f"{push_owner}/{push_name}" != request.target_repo:
        raise CanaryExecutionError(
            "push_remote_mismatch",
            "originのpush URLとtarget repositoryが一致しません",
            step="push-remote-before-push",
            changed=True,
        )
    execution_journal.update(
        "push-remote-before-push",
        changed=True,
        observed={"push_remote_repo": request.target_repo},
    )
    consumed_approval = consume_approval(
        request.approval_file or Path("<missing>"), approval, now=current_time
    )
    execution_journal.update(
        "approval-consumed",
        changed=True,
        approval_consumed_path=str(consumed_approval),
    )
    _run_ok(
        command_runner,
        [
            "git",
            "push",
            f"--force-with-lease=refs/heads/{request.branch}:",
            "origin",
            f"HEAD:refs/heads/{request.branch}",
        ],
        cwd=repo_path,
        step="push",
        changed=True,
        external_changed=True,
    )
    execution_journal.update(
        "push-command-succeeded",
        changed=True,
        external_changed=True,
    )
    remote_result = _run_ok(
        command_runner,
        ["git", "ls-remote", "--heads", "origin", f"refs/heads/{request.branch}"],
        cwd=repo_path,
        step="remote-sha",
        changed=True,
        external_changed=True,
    )
    remote_sha = _parse_remote_sha(remote_result)
    if remote_sha != local_sha:
        raise CanaryExecutionError(
            "remote_sha_mismatch",
            "remote branch SHAがlocal commitと一致しません",
            step="remote-sha",
            changed=True,
            external_changed=True,
        )
    execution_journal.update(
        "push-verified",
        changed=True,
        external_changed=True,
        remote_branch_sha=remote_sha,
    )

    body_file = repo_path / ".git" / "private-canary-pr-body.md"
    body_file.parent.mkdir(parents=True, exist_ok=True)
    pr_body = (
        "L4 private mutation canaryです。\n\n"
        "- visibility変更なし\n- main mergeなし\n- cleanupは別承認\n"
    )
    body_file.write_text(
        pr_body,
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
        external_changed=True,
    ).stdout.strip()
    execution_journal.update(
        "draft-pr-created",
        changed=True,
        external_changed=True,
        pr_create_url=pr_url,
    )
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
                "number,isDraft,state,url,title,body,headRefName,baseRefName,headRefOid,baseRefOid,files",
            ],
            cwd=repo_path,
            step="read-back",
            changed=True,
            external_changed=True,
        ),
        step="read-back",
        changed=True,
        external_changed=True,
    )
    if not (
        read_back.get("isDraft") is True
        and read_back.get("state") == "OPEN"
        and read_back.get("headRefName") == request.branch
        and read_back.get("baseRefName") == "main"
        and read_back.get("headRefOid") == local_sha
        and read_back.get("baseRefOid") == base_sha
        and read_back.get("title") == request.draft_pr_title
        and read_back.get("body") == pr_body
        and [item.get("path") for item in read_back.get("files", [])]
        == [MARKER_PATH.as_posix()]
        and urlparse(str(read_back.get("url", ""))).hostname == "github.com"
    ):
        raise CanaryExecutionError(
            "read_back_mismatch",
            "Draft PR read-backが期待値と一致しません",
            step="read-back",
            changed=True,
            external_changed=True,
        )
    login_after = _run_ok(
        command_runner,
        ["gh", "api", "user", "--jq", ".login"],
        cwd=repo_path,
        step="identity-after",
        changed=True,
        external_changed=True,
    ).stdout.strip()
    if login_after != login:
        raise CanaryExecutionError(
            "active_account_changed",
            "active accountが実行中に変化しました",
            step="identity-after",
            changed=True,
            external_changed=True,
        )
    execution_journal.update(
        "read-back-verified",
        status="READY",
        changed=True,
        external_changed=True,
        verified=True,
        read_back=read_back,
    )
    return {
        "status": "READY",
        "code": "private_canary_verified",
        "recorded_at": recorded_at,
        "request": asdict(request)
        | {
            "repo_path": str(repo_path),
            "approval_file": str(request.approval_file or ""),
        },
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
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--thread-id", required=True)
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
        approval_file=args.approval_file,
        thread_id=args.thread_id,
        confirm_private_canary=args.confirm_private_canary,
        execute=args.execute,
    )
    journal = MutationJournal(args.report_path, request)
    try:
        journal.update()
        result = execute_private_canary(request, journal=journal)
        payload = dict(journal.payload) | result
        returncode = 0
    except CanaryExecutionError as exc:
        payload = dict(journal.payload) | {
            "status": "BLOCKED",
            "code": exc.code,
            "cause": exc.cause,
            "step": exc.step,
            "changed": exc.changed or bool(journal.payload.get("changed")),
            "external_changed": exc.external_changed
            or bool(journal.payload.get("external_changed")),
            "verified": False,
            "next_action": (
                "外部変更が残る可能性があります。自動cleanupせず人間レビューしてください"
                if exc.external_changed
                else "入力と承認境界を確認してください"
            ),
            "recovery_candidates": journal.recovery_candidates(),
        }
        returncode = 1
    except Exception as exc:
        payload = dict(journal.payload) | {
            "status": "BLOCKED",
            "code": "unexpected_failure",
            "cause": type(exc).__name__,
            "step": "unexpected",
            "verified": False,
            "next_action": "journalのcompleted_stepsとobserved stateを人間レビューしてください",
            "recovery_candidates": journal.recovery_candidates(),
        }
        returncode = 1
    try:
        journal.payload = payload
        journal.update()
    except Exception as journal_exc:
        payload["journal_write_error"] = type(journal_exc).__name__
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
