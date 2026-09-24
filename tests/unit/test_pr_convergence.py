from github_ops.pr_convergence import ConvergenceSnapshot, decide_next_step


HEAD = "a" * 40


def snapshot(**overrides) -> ConvergenceSnapshot:
    values = {
        "repository": "nexus-ai-2045/github-ops-skills",
        "pr_number": 3,
        "visibility": "PRIVATE",
        "actor": "nexus-ai-2045",
        "expected_actor": "nexus-ai-2045",
        "base_ref": "main",
        "base_sha": "b" * 40,
        "head_ref": "codex/ops-hardening-drift-absorb",
        "head_sha": HEAD,
        "default_branch": "main",
        "pr_state": "OPEN",
        "checks_state": "success",
        "checks_head_sha": HEAD,
        "checks_base_sha": "b" * 40,
        "unresolved_threads": 0,
        "thread_audit_head_sha": HEAD,
        "thread_audit_base_sha": "b" * 40,
        "latest_review_head_sha": HEAD,
        "latest_review_base_sha": "b" * 40,
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


def test_non_integer_thread_count_is_rejected() -> None:
    assert decide_next_step(snapshot(unresolved_threads=False)).code == "thread_count_invalid"
    assert decide_next_step(snapshot(unresolved_threads=0.0)).code == "thread_count_invalid"


def test_thread_audit_must_match_exact_revision() -> None:
    result = decide_next_step(snapshot(thread_audit_head_sha="c" * 40))
    assert result.code == "thread_audit_revision_mismatch"
    assert result.status.value == "UNKNOWN"


def test_actor_must_match_expected_actor() -> None:
    result = decide_next_step(snapshot(actor="other-user"))
    assert result.code == "actor_mismatch"
    assert result.status.value == "BLOCKED"


def test_actor_fields_must_be_nonempty_strings() -> None:
    assert decide_next_step(snapshot(actor=True, expected_actor=True)).code == "snapshot_invalid"
    assert decide_next_step(snapshot(actor=" ")).code == "snapshot_invalid"


def test_ref_fields_must_be_nonempty_strings() -> None:
    assert decide_next_step(snapshot(base_ref=True)).code == "snapshot_invalid"
    assert decide_next_step(snapshot(head_ref=True)).code == "snapshot_invalid"
    assert decide_next_step(snapshot(default_branch=True)).code == "snapshot_invalid"


def test_only_open_pull_requests_can_converge() -> None:
    assert decide_next_step(snapshot(pr_state="CLOSED")).code == "pr_not_open"
    assert decide_next_step(snapshot(pr_state="MERGED")).code == "pr_not_open"


def test_review_must_match_exact_head() -> None:
    result = decide_next_step(snapshot(latest_review_head_sha="c" * 40))
    assert result.status.value == "UNKNOWN"
    assert result.code == "latest_head_review_pending"


def test_checks_must_match_exact_head() -> None:
    result = decide_next_step(snapshot(checks_head_sha="d" * 40))
    assert result.status.value == "UNKNOWN"
    assert result.code == "checks_head_mismatch"


def test_checks_must_match_exact_base() -> None:
    result = decide_next_step(snapshot(checks_base_sha="c" * 40))
    assert result.status.value == "UNKNOWN"
    assert result.code == "checks_base_mismatch"


def test_repeated_failure_exhausts_repair_budget() -> None:
    result = decide_next_step(snapshot(same_failure_count=2))
    assert result.code == "repair_budget_exhausted"
    assert result.status.value == "UNKNOWN"


def test_review_blocking_finding_prevents_false_ready() -> None:
    result = decide_next_step(snapshot(latest_review_outcome="blocking"))
    assert result.code == "latest_review_blocking"
    assert result.evidence["phase"] == "NEEDS_REPAIR"


def test_missing_review_outcome_is_unknown() -> None:
    result = decide_next_step(snapshot(latest_review_outcome=None))
    assert result.code == "latest_review_outcome_unknown"


def test_invalid_pr_number_and_short_sha_are_rejected() -> None:
    assert decide_next_step(snapshot(pr_number=0)).code == "snapshot_invalid"
    assert decide_next_step(snapshot(pr_number=True)).code == "snapshot_invalid"
    assert decide_next_step(snapshot(head_sha="abc", checks_head_sha="abc", latest_review_head_sha="abc")).code == "snapshot_invalid"


def test_invalid_repository_shape_is_rejected() -> None:
    assert decide_next_step(snapshot(repository="missing-owner-separator")).code == "snapshot_invalid"


def test_negative_or_boolean_counters_are_rejected() -> None:
    assert decide_next_step(snapshot(repair_cycles=-1)).code == "snapshot_invalid"
    assert decide_next_step(snapshot(same_failure_count=-1)).code == "snapshot_invalid"
    assert decide_next_step(snapshot(repair_cycles=True)).code == "snapshot_invalid"


def test_review_must_match_exact_base() -> None:
    result = decide_next_step(snapshot(latest_review_base_sha="c" * 40))
    assert result.code == "latest_review_base_mismatch"
    assert result.status.value == "UNKNOWN"


# --- CI が起動しなかった場合 (Actions 実行枠なし) --------------------------
# private repo の Actions は課金しない方針 (docs/operations.md
# 「Actions 実行枠」)。無料枠が尽きると job は runner に割り当てられず、
# steps なしで数秒後に failure になる。これはコードの失敗ではない。
# NEEDS_REPAIR (コードを直せ) に落とすと、存在しない不具合を探し回るか、
# 課金を人間に何度も問い直すことになる。


def test_not_executed_ci_is_local_verification_not_repair() -> None:
    result = decide_next_step(snapshot(checks_state="not_executed"))
    assert result.status.value == "BLOCKED"
    assert result.code == "ci_not_executed"
    assert result.evidence["phase"] == "LOCAL_VERIFICATION"
    assert "手元" in result.recovery
    assert "課金" in result.recovery


def _job(conclusion: str, *, runner_id: int = 7, steps: int = 3) -> dict:
    return {
        "conclusion": conclusion,
        "runner_id": runner_id,
        "steps": [{"name": f"s{i}"} for i in range(steps)],
    }


def test_checks_state_from_jobs_detects_unstarted_failures() -> None:
    from github_ops.pr_convergence import checks_state_from_jobs

    unstarted = _job("failure", runner_id=0, steps=0)
    assert checks_state_from_jobs([unstarted, unstarted]) == "not_executed"


def test_checks_state_from_jobs_keeps_real_failures_as_failure() -> None:
    from github_ops.pr_convergence import checks_state_from_jobs

    # 1 本でも実際に走って落ちた job があれば、それはコードの失敗として扱う。
    unstarted = _job("failure", runner_id=0, steps=0)
    assert checks_state_from_jobs([unstarted, _job("failure")]) == "failure"
    assert checks_state_from_jobs([_job("failure")]) == "failure"


def test_checks_state_from_jobs_success_and_pending() -> None:
    from github_ops.pr_convergence import checks_state_from_jobs

    assert checks_state_from_jobs([_job("success"), _job("skipped")]) == "success"
    assert checks_state_from_jobs([_job("success"), _job(None)]) == "pending"
    assert checks_state_from_jobs([]) == "pending"


# --- 独立 review (adversarial) の指摘に対するラチェット ----------------------


def test_missing_fields_are_not_evidence_of_unstarted() -> None:
    from github_ops.pr_convergence import checks_state_from_jobs

    # job field を持たない payload (check-runs 等) を「起動なし」と読まない。
    assert checks_state_from_jobs([{"conclusion": "failure"}]) == "failure"
    assert checks_state_from_jobs(
        [{"conclusion": "failure", "runner_id": None}]
    ) == "failure"


def test_only_plain_failure_can_be_unstarted() -> None:
    from github_ops.pr_convergence import checks_state_from_jobs

    for conclusion in ("startup_failure", "action_required", "timed_out", "stale"):
        job = _job(conclusion, runner_id=0, steps=0)
        assert checks_state_from_jobs([job]) == "failure", conclusion


def test_cancelled_job_waits_instead_of_counting_as_unstarted() -> None:
    from github_ops.pr_convergence import checks_state_from_jobs

    cancelled = {"conclusion": "cancelled", "runner_id": 0, "steps": []}
    assert checks_state_from_jobs([_job("success"), cancelled]) == "pending"


def test_workflow_change_in_pr_is_never_unstarted() -> None:
    from github_ops.pr_convergence import checks_state_from_jobs

    # PR 自身が workflow を壊しても runner なしで落ちる。課金と区別できない。
    unstarted = _job("failure", runner_id=0, steps=0)
    assert (
        checks_state_from_jobs([unstarted], workflow_files_changed=True) == "failure"
    )


def test_not_executed_still_requires_same_head_ci_evidence() -> None:
    result = decide_next_step(
        snapshot(checks_state="not_executed", checks_head_sha="c" * 40)
    )
    assert result.code == "checks_head_mismatch"
