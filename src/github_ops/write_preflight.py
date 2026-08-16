"""Thin compose gate: local work location + dirty scope + identity.

This is not a full orchestrator. It reuses IdentityProbe and local git facts,
and only points to sibling systems (worktree-lifecycle-control, hygiene skills)
for lifecycle cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .command import CommandRunner
from .identity import IdentityProbe
from .result import Outcome, Status


@dataclass(frozen=True)
class LocationFacts:
    repo_root: str
    branch: str | None
    is_linked_worktree: bool
    common_dir: str | None
    dirty_paths: tuple[str, ...]
    worktree_count: int | None


def _run_text(
    runner: CommandRunner,
    argv: list[str],
    *,
    cwd: Path,
) -> tuple[str | None, str | None]:
    result = runner.run(argv, cwd=cwd)
    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip() or "command failed"
    # Do not strip leading spaces: git status --porcelain uses a leading space
    # in the XY status field (e.g. " M path"). Full-string strip corrupts paths.
    return result.stdout.rstrip("\r\n"), None


def collect_location_facts(
    repo: Path,
    *,
    runner: CommandRunner | None = None,
) -> tuple[LocationFacts | None, Outcome | None]:
    command = runner or CommandRunner()
    root = repo.resolve()
    top, err = _run_text(command, ["git", "rev-parse", "--show-toplevel"], cwd=root)
    if err or not top:
        return None, Outcome(
            status=Status.UNKNOWN,
            code="git_root_unverified",
            cause="git repository root を確認できません",
            impact="作業場所を確定できないため GitHub 書き込みは進めません",
            recovery="git repo 内で実行するか、--repo を正しい checkout に向けてください",
            evidence={"repo": str(root)},
        )
    root_path = Path(top)
    branch, _ = _run_text(command, ["git", "branch", "--show-current"], cwd=root_path)
    git_dir, _ = _run_text(command, ["git", "rev-parse", "--git-dir"], cwd=root_path)
    common_dir, _ = _run_text(
        command, ["git", "rev-parse", "--git-common-dir"], cwd=root_path
    )
    is_linked = False
    if git_dir and common_dir:
        try:
            is_linked = Path(git_dir).resolve() != Path(common_dir).resolve()
        except OSError:
            is_linked = git_dir != common_dir

    porcelain, dirty_err = _run_text(
        command,
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root_path,
    )
    if dirty_err is not None and porcelain is None:
        return None, Outcome(
            status=Status.UNKNOWN,
            code="worktree_status_unverified",
            cause="git status を確認できません",
            impact="dirty scope を確定できないため書き込みは進めません",
            recovery="git status が通る checkout で再実行してください",
            evidence={"repo_root": str(root_path)},
        )
    dirty_paths: list[str] = []
    records = (porcelain or "").split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        # porcelain v1 -z: XY<space>path\0. Rename/copy records add the
        # original path as a second NUL field; the first path is the target.
        status = record[:2]
        path = record[3:] if len(record) >= 4 else record.strip()
        dirty_paths.append(path.replace("\\", "/"))
        if any(marker in status for marker in ("R", "C")) and index < len(records):
            index += 1

    worktree_count: int | None = None
    wt_out, _ = _run_text(
        command, ["git", "worktree", "list", "--porcelain"], cwd=root_path
    )
    if wt_out is not None:
        worktree_count = sum(
            1 for line in wt_out.splitlines() if line.startswith("worktree ")
        )

    return (
        LocationFacts(
            repo_root=str(root_path),
            branch=branch or None,
            is_linked_worktree=is_linked,
            common_dir=common_dir,
            dirty_paths=tuple(dirty_paths),
            worktree_count=worktree_count,
        ),
        None,
    )


def evaluate_write_preflight(
    repo: Path,
    *,
    expected_owner: str | None = None,
    expected_login: str | None = None,
    token: str | None = None,
    allow_dirty: bool = False,
    approved_paths: tuple[str, ...] = (),
    runner: CommandRunner | None = None,
    identity_probe: IdentityProbe | None = None,
) -> Outcome:
    command = runner or CommandRunner()
    location, location_error = collect_location_facts(repo, runner=command)
    if location_error is not None:
        return location_error
    assert location is not None

    if not expected_login:
        return Outcome(
            status=Status.BLOCKED,
            code="expected_login_required",
            cause="書き込みに使用するGitHub loginが未指定です",
            impact="別の認証済みaccountで書き込む事故を止めています",
            recovery="--expected-loginまたはaccount overlayで想定loginを明示してください",
            evidence={
                "repo_root": location.repo_root,
                "token_env_present": bool(token),
            },
        )

    if location.dirty_paths and not allow_dirty:
        approved = {path.replace("\\", "/") for path in approved_paths}
        unapproved = sorted(set(location.dirty_paths) - approved)
        if unapproved:
            return Outcome(
                status=Status.BLOCKED,
                code="dirty_scope_unapproved",
                cause="承認されていない dirty path があります",
                impact="意図しない変更を commit/push する事故を止めています",
                recovery=(
                    "対象 path だけ stage するか、--approved-path で範囲を明示するか、"
                    "別 worktree へ分離してください。"
                    "掃除判断は worktree-lifecycle-control / repo-hygiene-cleanup を使う"
                ),
                evidence={
                    "repo_root": location.repo_root,
                    "branch": location.branch,
                    "is_linked_worktree": location.is_linked_worktree,
                    "dirty_paths": list(location.dirty_paths),
                    "unapproved_paths": unapproved,
                    "worktree_count": location.worktree_count,
                    "compose": {
                        "identity": "github-ops-skills",
                        "worktree_lifecycle": "worktree-lifecycle-control (sibling)",
                        "worktree_create": "using-git-worktrees / git-sync-worktree-gate",
                        "hygiene": "repo-hygiene-cleanup",
                    },
                },
            )

    probe = identity_probe or IdentityProbe(command)
    identity = probe.probe(
        Path(location.repo_root),
        expected_owner=expected_owner,
        expected_login=expected_login,
        token=token,
    )
    evidence = {
        "location": {
            "repo_root": location.repo_root,
            "branch": location.branch,
            "is_linked_worktree": location.is_linked_worktree,
            "common_dir": location.common_dir,
            "dirty_paths": list(location.dirty_paths),
            "worktree_count": location.worktree_count,
            "allow_dirty": allow_dirty,
        },
        "identity": identity.to_dict(),
        "compose": {
            "identity": "github-ops-skills",
            "worktree_lifecycle": "worktree-lifecycle-control (sibling, not executed here)",
            "worktree_create": "using-git-worktrees / git-sync-worktree-gate",
            "hygiene": "repo-hygiene-cleanup",
            "public_readiness": "public-repo-readiness skill",
        },
        "stoplines": [
            "GitHub Settings 変更はしない",
            "worktree/branch 削除はしない",
            "push/PR/merge/public は現在会話の明示承認が必要",
        ],
    }
    if identity.status is Status.READY:
        return Outcome(
            status=Status.READY,
            code="write_preflight_ready",
            cause="作業場所と GitHub identity を確認しました",
            impact="人間承認済みの限定 write へ進めます",
            recovery="none",
            evidence=evidence,
        )
    return Outcome(
        status=identity.status,
        code=identity.code,
        cause=identity.cause,
        impact=identity.impact,
        recovery=identity.recovery,
        evidence=evidence,
    )
