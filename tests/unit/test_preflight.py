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
