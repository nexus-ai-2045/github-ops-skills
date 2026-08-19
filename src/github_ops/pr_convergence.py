from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from .result import Outcome, Status


class ConvergencePhase(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    NEEDS_REPAIR = "NEEDS_REPAIR"
    CI_WAIT = "CI_WAIT"
    LATEST_HEAD_REVIEW = "LATEST_HEAD_REVIEW"
    EXTERNAL_REVIEW_PENDING = "EXTERNAL_REVIEW_PENDING"
    READY_FOR_HUMAN_DECISION = "READY_FOR_HUMAN_DECISION"


@dataclass(frozen=True)
class ConvergenceSnapshot:
    repository: str
    pr_number: int
    visibility: str
    actor: str
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    default_branch: str
    checks_state: str
    checks_head_sha: str
    unresolved_threads: int
    latest_review_head_sha: str | None
    latest_review_base_sha: str | None
    latest_review_outcome: str | None
    repair_cycles: int = 0
    same_failure_count: int = 0


def decide_next_step(snapshot: ConvergenceSnapshot) -> Outcome:
    evidence = {
        "schema": "github-ops/pr-convergence/v1",
        "repository": snapshot.repository,
        "pr_number": snapshot.pr_number,
        "visibility": snapshot.visibility,
        "actor": snapshot.actor,
        "base_ref": snapshot.base_ref,
        "base_sha": snapshot.base_sha,
        "head_ref": snapshot.head_ref,
        "head_sha": snapshot.head_sha,
        "checks_state": snapshot.checks_state,
        "checks_head_sha": snapshot.checks_head_sha,
        "unresolved_threads": snapshot.unresolved_threads,
        "latest_review_head_sha": snapshot.latest_review_head_sha,
        "latest_review_base_sha": snapshot.latest_review_base_sha,
        "latest_review_outcome": snapshot.latest_review_outcome,
        "repair_cycles": snapshot.repair_cycles,
        "same_failure_count": snapshot.same_failure_count,
        "operation": "pr_convergence",
    }

    required = {
        "repository": snapshot.repository,
        "actor": snapshot.actor,
        "base_ref": snapshot.base_ref,
        "base_sha": snapshot.base_sha,
        "head_ref": snapshot.head_ref,
        "head_sha": snapshot.head_sha,
        "default_branch": snapshot.default_branch,
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        return _outcome(Status.UNKNOWN, "snapshot_incomplete", ConvergencePhase.PREFLIGHT,
                        f"必須snapshotが欠落しています: {', '.join(missing)}", evidence)
    sha_values = {
        "base_sha": snapshot.base_sha,
        "head_sha": snapshot.head_sha,
        "checks_head_sha": snapshot.checks_head_sha,
    }
    if snapshot.latest_review_head_sha is not None:
        sha_values["latest_review_head_sha"] = snapshot.latest_review_head_sha
    if snapshot.latest_review_base_sha is not None:
        sha_values["latest_review_base_sha"] = snapshot.latest_review_base_sha
    invalid = [name for name, value in sha_values.items() if not re.fullmatch(r"[0-9a-f]{40}", value)]
    if (
        snapshot.pr_number <= 0
        or not re.fullmatch(r"[^/\s]+/[^/\s]+", snapshot.repository)
        or invalid
        or not isinstance(snapshot.repair_cycles, int)
        or isinstance(snapshot.repair_cycles, bool)
        or snapshot.repair_cycles < 0
        or not isinstance(snapshot.same_failure_count, int)
        or isinstance(snapshot.same_failure_count, bool)
        or snapshot.same_failure_count < 0
    ):
        return _outcome(Status.UNKNOWN, "snapshot_invalid", ConvergencePhase.PREFLIGHT,
                        "PR番号、repository、またはexact SHAが不正です", evidence)
    if snapshot.visibility != "PRIVATE":
        return _outcome(Status.BLOCKED, "private_boundary_failed", ConvergencePhase.PREFLIGHT,
                        "repositoryがPRIVATEであることを確認できません", evidence)
    if snapshot.head_ref == snapshot.default_branch:
        return _outcome(Status.BLOCKED, "default_branch_write_forbidden", ConvergencePhase.PREFLIGHT,
                        "PR headがdefault branchです", evidence)
    if snapshot.repair_cycles >= 3 or snapshot.same_failure_count >= 2:
        return _outcome(Status.BLOCKED, "repair_budget_exhausted", ConvergencePhase.NEEDS_REPAIR,
                        "修正retry予算を使い切りました", evidence)
    if snapshot.checks_state == "pending":
        return _outcome(Status.UNKNOWN, "ci_pending", ConvergencePhase.CI_WAIT,
                        "同一headのCIが完了していません", evidence)
    if snapshot.checks_state != "success":
        return _outcome(Status.BLOCKED, "ci_not_successful", ConvergencePhase.NEEDS_REPAIR,
                        "同一headのCIが成功していません", evidence)
    if snapshot.checks_head_sha != snapshot.head_sha:
        return _outcome(Status.UNKNOWN, "checks_head_mismatch", ConvergencePhase.CI_WAIT,
                        "CI証拠を同一head SHAへ束縛できません", evidence)
    if snapshot.unresolved_threads < 0:
        return _outcome(Status.UNKNOWN, "thread_count_invalid", ConvergencePhase.LATEST_HEAD_REVIEW,
                        "review thread件数が不正です", evidence)
    if snapshot.unresolved_threads:
        return _outcome(Status.BLOCKED, "review_threads_unresolved", ConvergencePhase.NEEDS_REPAIR,
                        "未解決review threadがあります", evidence)
    if snapshot.latest_review_head_sha != snapshot.head_sha:
        return _outcome(Status.UNKNOWN, "latest_head_review_pending",
                        ConvergencePhase.EXTERNAL_REVIEW_PENDING,
                        "latest-head reviewを同一head SHAへ束縛できません", evidence)
    if snapshot.latest_review_base_sha != snapshot.base_sha:
        return _outcome(Status.UNKNOWN, "latest_review_base_mismatch",
                        ConvergencePhase.EXTERNAL_REVIEW_PENDING,
                        "latest-head reviewを同一base SHAへ束縛できません", evidence)
    if snapshot.latest_review_outcome is None:
        return _outcome(Status.UNKNOWN, "latest_review_outcome_unknown",
                        ConvergencePhase.EXTERNAL_REVIEW_PENDING,
                        "latest-head reviewの判定結果を確認できません", evidence)
    if snapshot.latest_review_outcome != "clean":
        return _outcome(Status.BLOCKED, "latest_review_blocking",
                        ConvergencePhase.NEEDS_REPAIR,
                        "latest-head reviewにblocking findingがあります", evidence)
    return _outcome(Status.READY, "ready_for_human_decision",
                    ConvergencePhase.READY_FOR_HUMAN_DECISION,
                    "機械検証は完了しました。mergeは人間判断で停止します", evidence)


def _outcome(
    status: Status,
    code: str,
    phase: ConvergencePhase,
    cause: str,
    evidence: dict,
) -> Outcome:
    evidence = {**evidence, "phase": phase.value, "next_action": _next_action(phase)}
    return Outcome(
        status=status,
        code=code,
        cause=cause,
        impact="mergeは実行しません",
        recovery=evidence["next_action"],
        evidence=evidence,
    )


def _next_action(phase: ConvergencePhase) -> str:
    return {
        ConvergencePhase.PREFLIGHT: "snapshotと安全境界を再取得してください",
        ConvergencePhase.NEEDS_REPAIR: "指摘を独立検証し、TDDで修正してください",
        ConvergencePhase.CI_WAIT: "bounded budget内で同一headのCIを再取得してください",
        ConvergencePhase.LATEST_HEAD_REVIEW: "review threadを再監査してください",
        ConvergencePhase.EXTERNAL_REVIEW_PENDING: "同一headのreviewを1回だけ待機してください",
        ConvergencePhase.READY_FOR_HUMAN_DECISION: "merge判断を人間へ提示してください",
    }[phase]
