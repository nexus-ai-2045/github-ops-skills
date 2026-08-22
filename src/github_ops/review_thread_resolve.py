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

from .review_threads import AuditResult, ThreadSummary, error_result, fetch, summarize

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

    # Only already-resolved IDs (existing judge) — mutation is a no-op confirm.
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
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise ValueError("GitHub GraphQL payload is not an object")
    if payload.get("errors"):
        raise ValueError("GitHub GraphQL returned errors")
    return payload


def apply_resolve(
    plan: ResolvePlan,
    *,
    apply: bool,
    resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply only IDs authorized by plan_resolve. Never invents thread IDs."""
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

    run = resolver or resolve_thread
    resolved: list[dict[str, Any]] = []
    for thread_id in plan.resolve_thread_ids:
        payload = run(thread_id)
        thread = (
            payload.get("data", {})
            .get("resolveReviewThread", {})
            .get("thread", {})
        )
        resolved.append(
            {
                "id": thread.get("id", thread_id),
                "isResolved": thread.get("isResolved"),
            }
        )
    result["applied"] = True
    result["resolved"] = resolved
    return result


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
    except ValueError as exc:
        audit = error_result(str(exc))
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        audit = error_result(f"gh_api_failed: {detail}")
    except subprocess.TimeoutExpired:
        audit = error_result("gh_api_timeout")
    except OSError as exc:
        audit = error_result(f"gh_launch_failed: {exc}")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        audit = error_result(f"unexpected_github_response: {exc}")

    plan = plan_resolve(audit, proposed_thread_ids=proposed_thread_ids)
    return apply_resolve(plan, apply=apply, resolver=resolver)
