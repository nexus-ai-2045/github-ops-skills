"""Fail-closed review-thread resolve gated by the existing audit judge.

Does not invent a close protocol. The only judge is
`github_ops.review_threads` (absorbed read-only audit): GraphQL
`reviewThreads.isResolved` is the resolution SSOT. Unresolved threads are
never treated as fixed from comment text or commits. When the audit cannot
judge (error / truncated), nothing is resolved and findings are surfaced as
materials.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .redaction import redact
from .review_threads import (
    AuditResult,
    ThreadSummary,
    error_result,
    fetch,
    github_com_env,
    summarize,
)

RESOLVE_MUTATION = """
mutation($threadId:ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
"""

GRAPHQL_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ResolvePlan:
    decision: str
    resolve_thread_ids: tuple[str, ...]
    materials: tuple[dict[str, Any], ...]
    audit: dict[str, Any]
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _thread_material(thread: ThreadSummary) -> dict[str, Any]:
    return {
        "id": thread.id,
        "state": thread.state,
        "path": thread.path,
        "line": thread.line,
        "author": thread.author,
        "title": thread.title,
        "commit": thread.commit,
        "original_commit": thread.original_commit,
    }


def plan_resolve(
    audit: AuditResult,
    *,
    proposed_thread_ids: tuple[str, ...] | None = None,
) -> ResolvePlan:
    """Authorize resolve only via the existing audit judge.

    - `decision=error` or truncated audit → cannot judge → hold/error, materials.
    - Unresolved threads → materials; never authorized to resolve.
    - Already-resolved threads may appear in `resolve_thread_ids` only as
      no-op confirmations when explicitly proposed (or when no proposal filter
      is given and the audit already passed with nothing left open).
    """
    audit_dict = audit.to_dict()
    if audit.decision == "error" or audit.errors:
        materials = tuple(
            {"kind": "audit_error", "message": message} for message in audit.errors
        ) or ({"kind": "audit_error", "message": "audit_decision_error"},)
        return ResolvePlan(
            decision="error",
            resolve_thread_ids=(),
            materials=materials,
            audit=audit_dict,
            errors=tuple(audit.errors) or ("audit_decision_error",),
        )

    if audit.truncated:
        materials = tuple(
            _thread_material(thread)
            for thread in audit.threads
            if thread.state != "resolved"
        )
        materials = materials + (
            {
                "kind": "audit_truncated",
                "message": "review thread pagination incomplete; cannot judge",
            },
        )
        return ResolvePlan(
            decision="hold",
            resolve_thread_ids=(),
            materials=materials,
            audit=audit_dict,
            errors=("audit_truncated",),
        )

    unresolved = tuple(
        thread for thread in audit.threads if thread.state != "resolved"
    )
    resolved = tuple(thread for thread in audit.threads if thread.state == "resolved")
    materials = tuple(_thread_material(thread) for thread in unresolved)

    if proposed_thread_ids is None:
        # Without an explicit proposal, unresolved stay open as materials.
        # Already-clean audits authorize nothing further to mutate.
        if unresolved:
            return ResolvePlan(
                decision="hold",
                resolve_thread_ids=(),
                materials=materials,
                audit=audit_dict,
            )
        return ResolvePlan(
            decision="ready",
            resolve_thread_ids=(),
            materials=(),
            audit=audit_dict,
        )

    proposed = tuple(dict.fromkeys(proposed_thread_ids))
    known = {thread.id: thread for thread in audit.threads}
    authorized: list[str] = []
    rejected: list[dict[str, Any]] = []
    for thread_id in proposed:
        thread = known.get(thread_id)
        if thread is None:
            rejected.append(
                {
                    "kind": "unknown_thread",
                    "id": thread_id,
                    "message": "thread not present in audit snapshot",
                }
            )
            continue
        if thread.state != "resolved":
            # Existing means has not judged this thread fixed (isResolved SSOT).
            rejected.append(_thread_material(thread))
            continue
        authorized.append(thread_id)

    # Any unresolved known threads remain materials even if not proposed.
    for thread in unresolved:
        if thread.id not in proposed:
            rejected.append(_thread_material(thread))

    # Deduplicate materials by id/kind while preserving order.
    seen: set[str] = set()
    unique_materials: list[dict[str, Any]] = []
    for item in rejected:
        key = str(item.get("id") or item.get("kind") or item)
        if key in seen:
            continue
        seen.add(key)
        unique_materials.append(item)

    if unique_materials or not authorized and proposed:
        # Proposed unresolved/unknown → fail closed; leave unresolved.
        return ResolvePlan(
            decision="hold",
            resolve_thread_ids=(),
            materials=tuple(unique_materials),
            audit=audit_dict,
            errors=("unresolved_or_unjudgeable_threads",) if unique_materials else (),
        )

    # Only already-resolved IDs (existing judge) — confirmation is read-only.
    _ = resolved  # clarity: authorization came from resolved state only
    return ResolvePlan(
        decision="ready",
        resolve_thread_ids=tuple(authorized),
        materials=(),
        audit=audit_dict,
    )


def resolve_thread(thread_id: str) -> dict[str, Any]:
    command = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"threadId={thread_id}",
        "-f",
        f"query={RESOLVE_MUTATION}",
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GRAPHQL_TIMEOUT_SECONDS,
        env=github_com_env(),
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("GitHub GraphQL payload is not an object")
    if payload.get("errors"):
        raise ValueError("GitHub GraphQL returned errors")
    return payload


def _verified_mutation_thread(thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    thread = (
        payload.get("data", {})
        .get("resolveReviewThread", {})
        .get("thread", {})
    )
    if not isinstance(thread, dict):
        raise ValueError("resolve mutation thread payload is missing")
    returned_id = thread.get("id")
    is_resolved = thread.get("isResolved")
    if returned_id != thread_id or is_resolved is not True:
        raise ValueError("resolve mutation result did not confirm requested thread")
    return {"id": returned_id, "isResolved": True}


def apply_resolve(
    plan: ResolvePlan,
    *,
    apply: bool,
    resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply only IDs authorized by plan_resolve. Never invents thread IDs.

    Already-resolved authorized IDs are confirmed from the audit snapshot
    without calling resolveReviewThread. A reopen race must not be closed by a
    stale mutation. An injected resolver is still verified fail-closed when used.
    """
    result: dict[str, Any] = {
        "decision": plan.decision,
        "applied": False,
        "resolved": [],
        "materials": list(plan.materials),
        "errors": list(plan.errors),
        "audit": plan.audit,
    }
    if not apply:
        result["decision"] = plan.decision
        return result
    if plan.decision != "ready":
        # Fail closed: do not mutate when hold/error.
        result["errors"] = list(plan.errors) or [f"resolve_not_authorized:{plan.decision}"]
        return result
    if not plan.resolve_thread_ids:
        result["applied"] = True
        return result

    if resolver is None:
        # Audit already judged these threads resolved; do not write.
        result["applied"] = True
        result["resolved"] = [
            {"id": thread_id, "isResolved": True, "confirmed": "audit_snapshot"}
            for thread_id in plan.resolve_thread_ids
        ]
        return result

    resolved: list[dict[str, Any]] = []
    for thread_id in plan.resolve_thread_ids:
        payload = resolver(thread_id)
        resolved.append(_verified_mutation_thread(thread_id, payload))
    result["applied"] = True
    result["resolved"] = resolved
    return result


def _audit_error_from_exc(exc: BaseException) -> AuditResult:
    if isinstance(exc, ValueError):
        return error_result(redact(str(exc)))
    if isinstance(exc, subprocess.CalledProcessError):
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return error_result(redact(f"gh_api_failed: {detail}"))
    if isinstance(exc, subprocess.TimeoutExpired):
        return error_result("gh_api_timeout")
    if isinstance(exc, OSError):
        return error_result(redact(f"gh_launch_failed: {exc}"))
    if isinstance(exc, (KeyError, TypeError, json.JSONDecodeError)):
        return error_result(redact(f"unexpected_github_response: {exc}"))
    return error_result(redact(f"resolve_failed: {exc}"))


def run_resolve(
    repo: str,
    number: int,
    *,
    proposed_thread_ids: tuple[str, ...] | None = None,
    apply: bool = False,
    resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        audit = summarize(fetch(repo, number))
    except (
        ValueError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        audit = _audit_error_from_exc(exc)

    plan = plan_resolve(audit, proposed_thread_ids=proposed_thread_ids)
    try:
        return apply_resolve(plan, apply=apply, resolver=resolver)
    except (
        ValueError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        # Mutation-stage failures become structured errors; do not continue IDs.
        detail = redact(str(exc))
        result = apply_resolve(plan, apply=False, resolver=None)
        result["decision"] = "error"
        result["applied"] = False
        result["errors"] = list(result["errors"]) + [f"resolve_apply_failed: {detail}"]
        result["materials"] = list(result["materials"]) + [
            {"kind": "resolve_apply_failed", "message": detail}
        ]
        return result
