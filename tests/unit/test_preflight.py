from github_ops.preflight import PreflightInput, run_preflight


def ready_input(**overrides):
    values = {
        "expected_repo": "example-org/tooling",
        "expected_owner": "example-org",
        "expected_login": "example-user",
        "remote_repo": "example-org/tooling",
        "token_login": "example-user",
        "permission": "ADMIN",
        "visibility": "PRIVATE",
        "worktree_paths": ("src/github_ops/preflight.py",),
        "approved_paths": ("src/github_ops/preflight.py",),
        "approval_ref": "current-conversation:approved",
        "operation": "push",
        "expected_visibility": "PRIVATE",
        "branch": "codex/safe-change",
        "default_branch": "main",
        "expected_head_sha": "a" * 40,
        "local_head_sha": "a" * 40,
        "remote_head_sha": "b" * 40,
        "fast_forward_verified": True,
    }
    values.update(overrides)
    return PreflightInput(**values)


def test_write_preflight_is_ready_only_when_all_proofs_match() -> None:
    result = run_preflight(ready_input())
    assert result.status.value == "READY"


def test_missing_current_approval_is_blocked() -> None:
    result = run_preflight(ready_input(approval_ref=None))
    assert result.code == "approval_missing"
    assert result.status.value == "BLOCKED"


def test_unknown_visibility_never_becomes_ready() -> None:
    result = run_preflight(ready_input(visibility=None))
    assert result.status.value == "UNKNOWN"


def test_unapproved_dirty_path_is_blocked() -> None:
    result = run_preflight(
        ready_input(worktree_paths=("src/ok.py", "unrelated.txt"), approved_paths=("src/ok.py",))
    )
    assert result.code == "worktree_scope_mismatch"


def test_org_owner_and_user_login_are_independent() -> None:
    result = run_preflight(ready_input())
    assert result.status.value == "READY"
    assert result.evidence["expected_owner"] == "example-org"
    assert result.evidence["expected_login"] == "example-user"


def test_public_visibility_is_blocked_for_private_write_contract() -> None:
    result = run_preflight(ready_input(visibility="PUBLIC"))
    assert result.code == "visibility_mismatch"
    assert result.status.value == "BLOCKED"


def test_default_branch_write_is_blocked() -> None:
    result = run_preflight(ready_input(branch="main"))
    assert result.code == "default_branch_write_forbidden"


def test_missing_branch_evidence_is_unknown() -> None:
    result = run_preflight(ready_input(branch=None))
    assert result.code == "branch_evidence_unknown"
    assert result.status.value == "UNKNOWN"


def test_push_requires_exact_local_head() -> None:
    result = run_preflight(ready_input(local_head_sha="c" * 40))
    assert result.code == "local_head_mismatch"


def test_push_requires_fast_forward_proof() -> None:
    result = run_preflight(ready_input(fast_forward_verified=False))
    assert result.code == "fast_forward_unverified"


def test_visibility_requires_dedicated_human_gate() -> None:
    result = run_preflight(ready_input(operation="visibility"))
    assert result.code == "operation_requires_dedicated_gate"


def test_pr_creation_requires_exact_remote_head() -> None:
    result = run_preflight(ready_input(operation="pr", remote_head_sha="c" * 40))
    assert result.code == "remote_head_mismatch"


def test_pr_creation_accepts_remote_head_equal_to_expected() -> None:
    result = run_preflight(
        ready_input(operation="pr", remote_head_sha="a" * 40, fast_forward_verified=None)
    )
    assert result.status.value == "READY"


def test_raw_dirty_path_is_compared_but_evidence_is_redacted() -> None:
    token_path = "ghp_" + ("A" * 24)
    result = run_preflight(
        ready_input(worktree_paths=(token_path,), approved_paths=(token_path,))
    )
    assert result.status.value == "READY"
    assert token_path not in str(result.evidence)
