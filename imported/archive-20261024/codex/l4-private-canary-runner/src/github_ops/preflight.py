from __future__ import annotations

from dataclasses import dataclass

from .result import Outcome, Status


WRITE_PERMISSIONS = {"WRITE", "MAINTAIN", "ADMIN"}


@dataclass(frozen=True)
class PreflightInput:
    expected_repo: str
    expected_owner: str
    expected_login: str
    remote_repo: str | None
    token_login: str | None
    permission: str | None
    visibility: str | None
    worktree_paths: tuple[str, ...]
    approved_paths: tuple[str, ...]
    approval_ref: str | None


def run_preflight(data: PreflightInput) -> Outcome:
    evidence = {
        "expected_repo": data.expected_repo,
        "expected_owner": data.expected_owner,
        "expected_login": data.expected_login,
        "remote_repo": data.remote_repo,
        "token_login": data.token_login,
        "permission": data.permission,
        "visibility": data.visibility,
        "worktree_paths": list(data.worktree_paths),
        "approved_paths": list(data.approved_paths),
        "approval_present": bool(data.approval_ref),
    }
    if not data.approval_ref:
        return _blocked(
            "approval_missing",
            "現在会話の承認参照がありません",
            "GitHub書き込みは実行しません",
            "対象操作の承認を取得し、approval referenceを渡してください",
            evidence,
        )
    unknown_fields = [
        name
        for name, value in (
            ("remote_repo", data.remote_repo),
            ("token_login", data.token_login),
            ("permission", data.permission),
            ("visibility", data.visibility),
        )
        if not value
    ]
    if unknown_fields:
        return Outcome(
            status=Status.UNKNOWN,
            code="required_evidence_unknown",
            cause=f"必須証拠を確認できません: {', '.join(unknown_fields)}",
            impact="GitHub書き込みは実行しません",
            recovery="GitHub APIとidentity probeを再実行してください",
            evidence=evidence,
        )
    if data.remote_repo != data.expected_repo:
        return _blocked(
            "repository_mismatch",
            "GitHub APIのrepositoryが期待値と一致しません",
            "GitHub書き込みは実行しません",
            "remoteとaccount mapを確認してください",
            evidence,
        )
    remote_owner = data.remote_repo.split("/", 1)[0]
    if remote_owner != data.expected_owner:
        return _blocked(
            "owner_mismatch",
            "repository ownerが期待値と一致しません",
            "GitHub書き込みは実行しません",
            "account mapを確認してください",
            evidence,
        )
    if data.token_login != data.expected_login:
        return _blocked(
            "login_mismatch",
            "GitHub loginが期待値と一致しません",
            "GitHub書き込みは実行しません",
            "validated-token modeを再確認してください",
            evidence,
        )
    if data.permission not in WRITE_PERMISSIONS:
        return _blocked(
            "permission_insufficient",
            "repositoryへの書き込み権限を確認できません",
            "GitHub書き込みは実行しません",
            "viewerPermissionを確認してください",
            evidence,
        )
    unapproved = sorted(set(data.worktree_paths) - set(data.approved_paths))
    if unapproved:
        evidence["unapproved_paths"] = unapproved
        return _blocked(
            "worktree_scope_mismatch",
            "承認範囲外のworktree変更があります",
            "stage、commit、pushは実行しません",
            "対象pathを分離するか、承認範囲を明示してください",
            evidence,
        )
    return Outcome(
        status=Status.READY,
        code="write_preflight_ready",
        cause="identity、repository、権限、visibility、worktree、承認を確認しました",
        impact="指定されたGitHub操作へ進めます",
        recovery="none",
        evidence=evidence,
    )


def _blocked(
    code: str,
    cause: str,
    impact: str,
    recovery: str,
    evidence: dict,
) -> Outcome:
    return Outcome(
        status=Status.BLOCKED,
        code=code,
        cause=cause,
        impact=impact,
        recovery=recovery,
        evidence=evidence,
    )
