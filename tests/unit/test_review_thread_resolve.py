from __future__ import annotations

from copy import deepcopy

import pytest

from github_ops.review_thread_resolve import apply_resolve, plan_resolve, run_resolve
from github_ops.review_threads import AuditResult, ThreadSummary, error_result


def _thread(
    *,
    thread_id: str,
    state: str,
    title: str = "finding",
) -> ThreadSummary:
    return ThreadSummary(
        id=thread_id,
        state=state,
        path="src/example.py",
        line=10,
        author="review-bot",
        title=title,
        commit="abc",
        original_commit="def",
    )


def _audit(*threads: ThreadSummary, decision: str = "warn", truncated: bool = False) -> AuditResult:
    unresolved_current = sum(1 for thread in threads if thread.state == "unresolved_current")
    unresolved_outdated = sum(1 for thread in threads if thread.state == "unresolved_outdated")
    resolved = sum(1 for thread in threads if thread.state == "resolved")
    if truncated:
        decision = "warn"
    elif unresolved_current or unresolved_outdated:
        decision = "warn"
    elif decision != "error":
        decision = "pass"
    return AuditResult(
        decision=decision,
        head_ref_oid="a" * 40,
        base_ref_oid="b" * 40,
        resolved=resolved,
        unresolved_current=unresolved_current,
        unresolved_outdated=unresolved_outdated,
        threads=list(threads),
        errors=[],
        truncated=truncated,
    )


def test_unresolved_threads_are_materials_not_resolved() -> None:
    audit = _audit(
        _thread(thread_id="t1", state="unresolved_current", title="P1 finding"),
        _thread(thread_id="t2", state="resolved", title="done"),
    )
    plan = plan_resolve(audit)
    assert plan.decision == "hold"
    assert plan.resolve_thread_ids == ()
    assert [item["id"] for item in plan.materials] == ["t1"]


def test_audit_error_fail_closed_leaves_unresolved() -> None:
    plan = plan_resolve(error_result("gh_api_timeout"))
    assert plan.decision == "error"
    assert plan.resolve_thread_ids == ()
    assert plan.materials
    assert plan.errors == ("gh_api_timeout",)


def test_truncated_audit_cannot_judge() -> None:
    audit = _audit(_thread(thread_id="t1", state="resolved"), truncated=True)
    plan = plan_resolve(audit)
    assert plan.decision == "hold"
    assert plan.resolve_thread_ids == ()
    assert any(item.get("kind") == "audit_truncated" for item in plan.materials)


def test_proposed_unresolved_id_is_rejected() -> None:
    audit = _audit(_thread(thread_id="t1", state="unresolved_current", title="open"))
    plan = plan_resolve(audit, proposed_thread_ids=("t1",))
    assert plan.decision == "hold"
    assert plan.resolve_thread_ids == ()
    assert plan.materials[0]["id"] == "t1"


def test_proposed_already_resolved_id_is_authorized_noop() -> None:
    audit = _audit(_thread(thread_id="t1", state="resolved", title="done"))
    plan = plan_resolve(audit, proposed_thread_ids=("t1",))
    assert plan.decision == "ready"
    assert plan.resolve_thread_ids == ("t1",)
    assert plan.materials == ()


def test_apply_does_not_mutate_on_hold(monkeypatch) -> None:
    audit = _audit(_thread(thread_id="t1", state="unresolved_current"))
    plan = plan_resolve(audit, proposed_thread_ids=("t1",))
    calls: list[str] = []

    def fake_resolve(thread_id: str) -> dict:
        calls.append(thread_id)
        return {"data": {"resolveReviewThread": {"thread": {"id": thread_id, "isResolved": True}}}}

    result = apply_resolve(plan, apply=True, resolver=fake_resolve)
    assert result["applied"] is False
    assert calls == []
    assert result["materials"]


def test_apply_ready_without_ids_is_noop_success() -> None:
    audit = _audit()
    plan = plan_resolve(audit)
    assert plan.decision == "ready"
    result = apply_resolve(plan, apply=True, resolver=lambda thread_id: {})
    assert result["applied"] is True
    assert result["resolved"] == []


def test_apply_confirms_already_resolved_without_mutation() -> None:
    audit = _audit(_thread(thread_id="t1", state="resolved"))
    plan = plan_resolve(audit, proposed_thread_ids=("t1",))
    result = apply_resolve(deepcopy(plan), apply=True, resolver=None)
    assert result["applied"] is True
    assert result["resolved"] == [
        {"id": "t1", "isResolved": True, "confirmed": "audit_snapshot"}
    ]


def test_apply_injected_resolver_must_confirm_thread() -> None:
    audit = _audit(_thread(thread_id="t1", state="resolved"))
    plan = plan_resolve(audit, proposed_thread_ids=("t1",))

    def bad_resolve(thread_id: str) -> dict:
        return {
            "data": {
                "resolveReviewThread": {
                    "thread": {"id": thread_id, "isResolved": False}
                }
            }
        }

    with pytest.raises(ValueError, match="did not confirm"):
        apply_resolve(deepcopy(plan), apply=True, resolver=bad_resolve)


def test_run_resolve_converts_apply_failure_to_structured_error(monkeypatch) -> None:
    audit = _audit(_thread(thread_id="t1", state="resolved"))

    monkeypatch.setattr(
        "github_ops.review_thread_resolve.fetch",
        lambda repo, number: {"unused": True},
    )
    monkeypatch.setattr(
        "github_ops.review_thread_resolve.summarize",
        lambda payload: audit,
    )

    def bad(thread_id: str) -> dict:
        return {
            "data": {
                "resolveReviewThread": {
                    "thread": {"id": "other", "isResolved": True}
                }
            }
        }

    result = run_resolve(
        "owner/name",
        7,
        proposed_thread_ids=("t1",),
        apply=True,
        resolver=bad,
    )
    assert result["decision"] == "error"
    assert result["applied"] is False
    assert any("resolve_apply_failed" in err for err in result["errors"])
