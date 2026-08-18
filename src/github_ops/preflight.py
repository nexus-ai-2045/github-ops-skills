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
    operation: str = "push"
    expected_visibility: str = "PRIVATE"
    branch: str | None = None
    default_branch: str | None = None
    expected_head_sha: str | None = None
    local_head_sha: str | None = None
    remote_head_sha: str | None = None
    fast_forward_verified: bool | None = None


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
        "operation": data.operation,
        "expected_visibility": data.expected_visibility,
        "branch": data.branch,
        "default_branch": data.default_branch,
        "expected_head_sha": data.expected_head_sha,
        "local_head_sha": data.local_head_sha,
        "remote_head_sha": data.remote_head_sha,
        "fast_forward_verified": data.fast_forward_verified,
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
    if data.visibility != data.expected_visibility:
        return _blocked(
            "visibility_mismatch",
            "repository visibilityが期待値と一致しません",
            "GitHub書き込みは実行しません",
            "visibilityを変更せず、対象repositoryと操作承認を確認してください",
            evidence,
        )
    if data.operation in {"merge", "visibility"}:
        return _blocked(
            "operation_requires_dedicated_gate",
            "この操作は汎用write preflightの対象外です",
            "GitHub書き込みは実行しません",
            "exact PR headに束縛した専用の人間承認gateを使用してください",
            evidence,
        )
    if data.operation not in {"push", "draft-pr", "pr"}:
        return _blocked(
            "operation_unsupported", "未対応のGitHub操作です",
            "GitHub書き込みは実行しません", "対応する専用gateを使用してください", evidence,
        )
    if data.operation in {"push", "draft-pr", "pr"}:
        if not data.branch or not data.default_branch:
            return Outcome(
                status=Status.UNKNOWN,
                code="branch_evidence_unknown",
                cause="branchまたはdefault branchを確認できません",
                impact="GitHub書き込みは実行しません",
                recovery="local branchとGitHub default branchを再取得してください",
                evidence=evidence,
            )
        if data.branch == data.default_branch:
            return _blocked(
                "default_branch_write_forbidden",
                "対象branchがdefault branchです",
                "GitHub書き込みは実行しません",
                "専用branchを使用してください",
                evidence,
            )
        if not data.expected_head_sha or data.local_head_sha != data.expected_head_sha:
            return _blocked(
                "local_head_mismatch", "local HEADが期待SHAと一致しません",
                "GitHub書き込みは実行しません", "HEADと承認snapshotを再取得してください", evidence,
            )
    if data.operation == "push" and data.fast_forward_verified is not True:
        return _blocked(
            "fast_forward_unverified", "remote refからのfast-forwardを確認できません",
            "pushは実行しません", "fetch後にremote refとmerge-baseを再検証してください", evidence,
        )
    if data.operation in {"draft-pr", "pr"} and data.remote_head_sha != data.expected_head_sha:
        return _blocked(
            "remote_head_mismatch", "remote PR headが期待SHAと一致しません",
            "PR作成・更新は実行しません", "branchを安全にpushしremote SHAを再取得してください", evidence,
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
