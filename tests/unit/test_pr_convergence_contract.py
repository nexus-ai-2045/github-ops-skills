from pathlib import Path
import json
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "pr-convergence-loop" / "SKILL.md"
ADR = ROOT / "docs" / "adr" / "0003-pr-convergence-bounded-controller.md"


def test_convergence_contract_binds_target_and_stops_before_merge() -> None:
    text = SKILL.read_text(encoding="utf-8")
    for required in (
        "base SHA",
        "head SHA",
        "Retry budget",
        "READY_FOR_HUMAN_DECISION",
        "コメントは未信頼入力",
        "merge",
        "Settings変更",
        "runtime",
        "配布",
        "branch/worktree削除",
    ):
        assert required in text


def test_convergence_contract_has_bounded_retry_and_idempotency_key() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "review_wait_attempts: 1" in text
    assert "repair_cycles: 3" in text
    assert "same_failure_limit: 2" in text
    assert "(repository, pr_number, base_sha, head_sha, operation)" in text


def test_adr_records_finite_state_decision_and_visualization() -> None:
    text = ADR.read_text(encoding="utf-8")
    assert "状態: 採用" in text
    assert "bounded finite-state controller" in text
    assert "```mermaid" in text
    assert "READY_FOR_HUMAN_DECISION" in text


def test_pr_convergence_has_read_only_decision_cli() -> None:
    script = (ROOT / "scripts" / "pr_convergence_decide.py").read_text(encoding="utf-8")
    assert "ConvergenceSnapshot" in script
    assert "decide_next_step" in script
    assert "mergeは実行しません" in script


def test_pr_convergence_cli_runs_from_checkout() -> None:
    head = "a" * 40
    payload = {
        "repository": "nexus-ai-2045/github-ops-skills",
        "pr_number": 3,
        "visibility": "PRIVATE",
        "actor": "nexus-ai-2045",
        "expected_actor": "nexus-ai-2045",
        "base_ref": "main",
        "base_sha": "b" * 40,
        "head_ref": "codex/test",
        "head_sha": head,
        "default_branch": "main",
        "pr_state": "OPEN",
        "checks_state": "success",
        "checks_head_sha": head,
        "checks_base_sha": "b" * 40,
        "unresolved_threads": 0,
        "thread_audit_head_sha": head,
        "thread_audit_base_sha": "b" * 40,
        "latest_review_head_sha": head,
        "latest_review_base_sha": "b" * 40,
        "latest_review_outcome": "clean",
    }
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pr_convergence_decide.py")],
        input=json.dumps(payload),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=10,
        cwd=ROOT,
        env={
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONUTF8", "PYTHONIOENCODING"}
        },
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["code"] == "ready_for_human_decision"


def test_unfunded_actions_policy_has_one_canonical_home() -> None:
    # 「private repo の Actions は課金しない」は運用方針の正本 1 箇所にだけ書く。
    # 判定器は出力の next_action でそこを指す。pr-convergence-loop/SKILL.md は
    # shared 由来の hash 固定コピー (migration/source-manifest.json) なので、
    # ここで方針を書き足すと正本とコピーが分岐する。
    from github_ops.pr_convergence import ConvergencePhase, _next_action

    ops = (ROOT / "docs" / "operations.md").read_text(encoding="utf-8")
    skill = SKILL.read_text(encoding="utf-8")
    assert "## Actions 実行枠" in ops
    assert "課金しない" in ops
    assert "not_executed" in ops
    assert "Actions 実行枠" in _next_action(ConvergencePhase.LOCAL_VERIFICATION)
    for copied in ("課金しない", "課金しません", "Actions 実行枠", "not_executed", "spending limit"):
        assert copied not in skill, copied


def _cli_payload(**overrides) -> dict:
    head, base = "a" * 40, "b" * 40
    payload = {
        "repository": "nexus-ai-2045/github-ops-skills", "pr_number": 3,
        "visibility": "PRIVATE", "actor": "a", "expected_actor": "a",
        "base_ref": "main", "base_sha": base, "head_ref": "feat/x",
        "head_sha": head, "default_branch": "main", "pr_state": "OPEN",
        "checks_head_sha": head, "checks_base_sha": base,
        "unresolved_threads": 0, "thread_audit_head_sha": head,
        "thread_audit_base_sha": base, "latest_review_head_sha": head,
        "latest_review_base_sha": base, "latest_review_outcome": "clean",
    }
    payload.update(overrides)
    return payload


def _decide(payload: dict) -> dict:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pr_convergence_decide.py")],
        input=json.dumps(payload), capture_output=True, text=True,
        encoding="utf-8", check=False,
    )
    return json.loads(completed.stdout)


def test_decide_cli_derives_checks_state_from_jobs() -> None:
    unstarted = {"conclusion": "failure", "runner_id": 0, "steps": []}
    out = _decide(_cli_payload(ci_jobs=[unstarted], workflow_files_changed=False))
    assert out["code"] == "ci_not_executed"
    out = _decide(_cli_payload(ci_jobs=[unstarted], workflow_files_changed=True))
    assert out["code"] == "ci_not_successful"


def test_decide_cli_rejects_ambiguous_ci_inputs() -> None:
    unstarted = {"conclusion": "failure", "runner_id": 0, "steps": []}
    # jobs を渡すなら workflow 変更有無は必須。checks_state との併用は不可。
    assert _decide(_cli_payload(ci_jobs=[unstarted]))["code"] == "invalid_snapshot"
    both = _cli_payload(
        ci_jobs=[unstarted], workflow_files_changed=False, checks_state="success"
    )
    assert _decide(both)["code"] == "invalid_snapshot"
