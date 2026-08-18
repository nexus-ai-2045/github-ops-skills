from github_ops.pr_convergence import ConvergenceSnapshot, decide_next_step


HEAD = "a" * 40


def snapshot(**overrides) -> ConvergenceSnapshot:
    values = {
        "repository": "nexus-ai-2045/github-ops-skills",
        "pr_number": 3,
        "visibility": "PRIVATE",
        "actor": "nexus-ai-2045",
        "base_ref": "main",
        "base_sha": "b" * 40,
        "head_ref": "codex/ops-hardening-drift-absorb",
        "head_sha": HEAD,
        "default_branch": "main",
        "checks_state": "success",
        "checks_head_sha": HEAD,
        "unresolved_threads": 0,
        "latest_review_head_sha": HEAD,
        "latest_review_outcome": "clean",
    }
    values.update(overrides)
    return ConvergenceSnapshot(**values)


def test_ready_stops_at_human_merge_decision() -> None:
    result = decide_next_step(snapshot())
    assert result.status.value == "READY"
    assert result.code == "ready_for_human_decision"
    assert result.evidence["phase"] == "READY_FOR_HUMAN_DECISION"
    assert result.impact == "mergeは実行しません"


def test_non_private_repository_is_blocked() -> None:
    result = decide_next_step(snapshot(visibility="PUBLIC"))
    assert result.code == "private_boundary_failed"
    assert result.status.value == "BLOCKED"


def test_default_branch_head_is_blocked() -> None:
    result = decide_next_step(snapshot(head_ref="main"))
    assert result.code == "default_branch_write_forbidden"


def test_pending_ci_is_bounded_unknown() -> None:
    result = decide_next_step(snapshot(checks_state="pending"))
    assert result.status.value == "UNKNOWN"
    assert result.evidence["phase"] == "CI_WAIT"


def test_unresolved_review_requires_verified_repair() -> None:
    result = decide_next_step(snapshot(unresolved_threads=1))
    assert result.code == "review_threads_unresolved"
    assert result.evidence["phase"] == "NEEDS_REPAIR"


def test_review_must_match_exact_head() -> None:
    result = decide_next_step(snapshot(latest_review_head_sha="c" * 40))
    assert result.status.value == "UNKNOWN"
    assert result.code == "latest_head_review_pending"


def test_checks_must_match_exact_head() -> None:
    result = decide_next_step(snapshot(checks_head_sha="d" * 40))
    assert result.status.value == "UNKNOWN"
    assert result.code == "checks_head_mismatch"


def test_repeated_failure_exhausts_repair_budget() -> None:
    result = decide_next_step(snapshot(same_failure_count=2))
    assert result.code == "repair_budget_exhausted"
    assert result.status.value == "BLOCKED"


def test_review_blocking_finding_prevents_false_ready() -> None:
    result = decide_next_step(snapshot(latest_review_outcome="blocking"))
    assert result.code == "latest_review_blocking"
    assert result.evidence["phase"] == "NEEDS_REPAIR"


def test_missing_review_outcome_is_unknown() -> None:
    result = decide_next_step(snapshot(latest_review_outcome=None))
    assert result.code == "latest_review_outcome_unknown"


def test_invalid_pr_number_and_short_sha_are_rejected() -> None:
    assert decide_next_step(snapshot(pr_number=0)).code == "snapshot_invalid"
    assert decide_next_step(snapshot(head_sha="abc", checks_head_sha="abc", latest_review_head_sha="abc")).code == "snapshot_invalid"


def test_invalid_repository_shape_is_rejected() -> None:
    assert decide_next_step(snapshot(repository="missing-owner-separator")).code == "snapshot_invalid"
