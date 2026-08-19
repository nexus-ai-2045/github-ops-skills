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
        "checks_state": "success",
        "checks_head_sha": head,
        "unresolved_threads": 0,
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
