"""Fail-closed review-thread resolve backed by a machine-checkable disposition record.

The audit in `github_ops.review_threads` stays the resolution SSOT. An unresolved
thread is closed only when the expected account left a `review-disposition` mark
in a reply and GitHub itself confirms the claim (fixed commit or deferred issue).
Everything else stays open and is surfaced as materials.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Mapping, Protocol

from .redaction import redact
from .review_threads import (
    GRAPHQL_TIMEOUT_SECONDS,
    MAX_GRAPHQL_PAGES,
    AuditResult,
    ThreadSummary,
    error_result,
    fetch,
    github_com_api_argv,
    github_com_env,
    repo_parts,
    summarize,
)

RESOLVE_MUTATION = """
mutation($threadId:ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
"""

RECORD_QUERY = """
query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      reviewThreads(first:100, after:$cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          comments(first:100) {
            pageInfo { hasNextPage }
            nodes {
              id
              body
              path
              author { login }
              originalCommit { oid }
            }
          }
        }
      }
    }
  }
}
"""

MARK_RE = re.compile(r"<!--\s*review-disposition:(.*?)-->", re.DOTALL)
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
REF_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*")
DISPOSITION_FIELDS = {"fixed": "commit", "deferred": "ref", "dismissed": "reason"}
COMMIT_FILES_LIMIT = 300

API_ERRORS = (
    ValueError,
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
    OSError,
    KeyError,
    TypeError,
    json.JSONDecodeError,
)


@dataclass(frozen=True)
class Disposition:
    kind: str
    commit: str = ""
    ref: str = ""
    reason: str = ""
    author: str = ""
    comment_id: str = ""


@dataclass(frozen=True)
class ParseError:
    code: str


@dataclass(frozen=True)
class ThreadVerdict:
    thread_id: str
    verdict: str
    reason_code: str


@dataclass(frozen=True)
class ThreadComment:
    id: str
    body: str
    path: str
    author: str
    original_commit: str


@dataclass(frozen=True)
class ThreadRecord:
    thread_id: str
    comments: tuple[ThreadComment, ...]
    comments_truncated: bool


@dataclass(frozen=True)
class CommitFiles:
    paths: frozenset[str]
    truncated: bool


class LookupFailure(Exception):
    pass


class NotFound(LookupFailure):
    pass


class GitHubLookup(Protocol):
    def compare_status(self, repo: str, base: str, head: str) -> str: ...

    def commit_files(self, repo: str, commit: str) -> CommitFiles: ...

    def issue_number(self, repo: str, number: int) -> int: ...


@dataclass(frozen=True)
class JudgeContext:
    repo: str
    pr_number: int
    head: str
    base: str
    expected_login: str
    lookup: GitHubLookup | None


@dataclass(frozen=True)
class ResolvePlan:
    decision: str
    resolve_thread_ids: tuple[str, ...]
    materials: tuple[dict[str, Any], ...]
    audit: dict[str, Any]
    errors: tuple[str, ...] = ()
    verdicts: tuple[ThreadVerdict, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_disposition(
    body: str, *, author: str = "", comment_id: str = ""
) -> Disposition | ParseError:
    marks = MARK_RE.findall(body)
    if not marks:
        return ParseError("no_mark")
    if len(marks) > 1:
        return ParseError("multiple_marks")
    try:
        payload = json.loads(marks[0])
    except json.JSONDecodeError:
        return ParseError("invalid_json")
    if not isinstance(payload, dict):
        return ParseError("invalid_shape")
    version = payload.get("v")
    if type(version) is not int or version != 1:
        return ParseError("invalid_version")
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in DISPOSITION_FIELDS:
        return ParseError("invalid_kind")
    field = DISPOSITION_FIELDS[kind]
    if set(payload) != {"v", "kind", field}:
        return ParseError("invalid_keys")
    value = payload[field]
    if not isinstance(value, str):
        return ParseError("invalid_value")
    if kind == "fixed" and not COMMIT_RE.fullmatch(value):
        return ParseError("invalid_value")
    if kind == "deferred" and not REF_RE.fullmatch(value):
        return ParseError("invalid_value")
    if kind == "dismissed" and not value.strip():
        return ParseError("invalid_value")
    return Disposition(
        kind=kind, author=author, comment_id=comment_id, **{field: value}
    )


def select_disposition(
    comments: tuple[ThreadComment, ...], expected_login: str
) -> Disposition | ParseError:
    replies = comments[1:]
    login = expected_login.casefold()
    marked = [bool(MARK_RE.search(comment.body)) for comment in replies]
    own = [
        index
        for index, comment in enumerate(replies)
        if marked[index] and comment.author.casefold() == login
    ]
    if not own:
        return ParseError("author_mismatch" if any(marked) else "no_record")
    chosen = replies[own[-1]]
    later = replies[own[-1] + 1 :]
    if any(comment.author.casefold() != login for comment in later):
        return ParseError("later_comment_by_other")
    return parse_disposition(
        chosen.body, author=chosen.author, comment_id=chosen.id
    )


def _hold(thread_id: str, code: str) -> ThreadVerdict:
    return ThreadVerdict(thread_id, "hold", code)


def _judge_fixed(
    thread_id: str,
    disposition: Disposition,
    first: ThreadComment,
    ctx: JudgeContext,
    lookup: GitHubLookup,
) -> ThreadVerdict:
    commit = disposition.commit
    if not first.path or not COMMIT_RE.fullmatch(first.original_commit):
        return _hold(thread_id, "first_comment_incomplete")
    try:
        if lookup.compare_status(ctx.repo, commit, ctx.head) not in {"ahead", "identical"}:
            return _hold(thread_id, "commit_not_in_head")
        if lookup.compare_status(ctx.repo, first.original_commit, commit) != "ahead":
            return _hold(thread_id, "commit_not_after_finding")
        if lookup.compare_status(ctx.repo, ctx.base, commit) not in {"ahead", "diverged"}:
            return _hold(thread_id, "commit_in_base")
        files = lookup.commit_files(ctx.repo, commit)
    except NotFound:
        return _hold(thread_id, "commit_not_found")
    except LookupFailure:
        return _hold(thread_id, "lookup_failed")
    if files.truncated:
        return _hold(thread_id, "files_truncated")
    if first.path not in files.paths:
        return _hold(thread_id, "commit_misses_path")
    return ThreadVerdict(thread_id, "resolvable", "fixed_verified")


def _judge_deferred(
    thread_id: str,
    disposition: Disposition,
    ctx: JudgeContext,
    lookup: GitHubLookup,
) -> ThreadVerdict:
    target, _, raw_number = disposition.ref.rpartition("#")
    number = int(raw_number)
    if target.casefold() != ctx.repo.casefold():
        return _hold(thread_id, "ref_other_repo")
    if number == ctx.pr_number:
        return _hold(thread_id, "ref_is_self")
    try:
        found = lookup.issue_number(ctx.repo, number)
    except NotFound:
        return _hold(thread_id, "ref_not_found")
    except LookupFailure:
        return _hold(thread_id, "lookup_failed")
    if found != number:
        return _hold(thread_id, "ref_mismatch")
    return ThreadVerdict(thread_id, "resolvable", "deferred_verified")


def judge_thread(
    thread: ThreadSummary, record: ThreadRecord | None, ctx: JudgeContext
) -> ThreadVerdict:
    if thread.state == "resolved":
        return ThreadVerdict(thread.id, "already_resolved", "already_resolved")
    if not ctx.expected_login:
        return _hold(thread.id, "expected_login_missing")
    if record is None or not record.comments:
        return _hold(thread.id, "record_missing")
    if record.comments_truncated:
        return _hold(thread.id, "comments_truncated")
    selected = select_disposition(record.comments, ctx.expected_login)
    if isinstance(selected, ParseError):
        return _hold(thread.id, selected.code)
    if selected.kind == "dismissed":
        return ThreadVerdict(thread.id, "human", "dismissed")
    if ctx.lookup is None:
        return _hold(thread.id, "lookup_unavailable")
    if selected.kind == "fixed":
        return _judge_fixed(thread.id, selected, record.comments[0], ctx, ctx.lookup)
    return _judge_deferred(thread.id, selected, ctx, ctx.lookup)


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
    records: Mapping[str, ThreadRecord] | None = None,
    expected_login: str | None = None,
    repo: str = "",
    pr_number: int = 0,
    lookup: GitHubLookup | None = None,
    proposed_thread_ids: tuple[str, ...] | None = None,
) -> ResolvePlan:
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

    ctx = JudgeContext(
        repo=repo,
        pr_number=pr_number,
        head=audit.head_ref_oid,
        base=audit.base_ref_oid,
        expected_login=expected_login or "",
        lookup=lookup,
    )
    proposed = None if proposed_thread_ids is None else set(proposed_thread_ids)
    verdicts: list[ThreadVerdict] = []
    for thread in audit.threads:
        verdict = judge_thread(thread, (records or {}).get(thread.id), ctx)
        if (
            proposed is not None
            and verdict.verdict == "resolvable"
            and thread.id not in proposed
        ):
            verdict = _hold(thread.id, "not_proposed")
        verdicts.append(verdict)

    by_id = {verdict.thread_id: verdict for verdict in verdicts}
    materials = [
        {
            **_thread_material(thread),
            "verdict": by_id[thread.id].verdict,
            "reason_code": by_id[thread.id].reason_code,
        }
        for thread in audit.threads
        if by_id[thread.id].verdict in {"hold", "human"}
    ]
    errors: list[str] = []
    if proposed is not None:
        known = {thread.id for thread in audit.threads}
        for thread_id in dict.fromkeys(proposed_thread_ids or ()):
            if thread_id not in known:
                materials.append(
                    {
                        "kind": "unknown_thread",
                        "id": thread_id,
                        "message": "thread not present in audit snapshot",
                    }
                )
                errors.append("unknown_thread")

    resolve_ids = tuple(
        thread.id for thread in audit.threads if by_id[thread.id].verdict == "resolvable"
    )
    needs_action = resolve_ids or materials
    return ResolvePlan(
        decision="hold" if needs_action else "ready",
        resolve_thread_ids=resolve_ids,
        materials=tuple(materials),
        audit=audit_dict,
        errors=tuple(dict.fromkeys(errors)),
        verdicts=tuple(verdicts),
    )


def resolve_thread(thread_id: str) -> dict[str, Any]:
    command = github_com_api_argv(
        "graphql",
        "-f",
        f"threadId={thread_id}",
        "-f",
        f"query={RESOLVE_MUTATION}",
    )
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
    result: dict[str, Any] = {
        "decision": plan.decision,
        "applied": False,
        "resolved": [],
        "materials": list(plan.materials),
        "errors": list(plan.errors),
        "audit": plan.audit,
        "verdicts": [asdict(verdict) for verdict in plan.verdicts],
    }
    if not apply:
        return result
    if not plan.resolve_thread_ids:
        if plan.decision == "ready":
            result["applied"] = True
        else:
            result["errors"] = list(plan.errors) or [
                f"resolve_not_authorized:{plan.decision}"
            ]
        return result
    if resolver is None:
        result["errors"] = list(plan.errors) + ["resolver_missing"]
        return result

    resolved: list[dict[str, Any]] = []
    for thread_id in plan.resolve_thread_ids:
        try:
            resolved.append(_verified_mutation_thread(thread_id, resolver(thread_id)))
        except API_ERRORS as exc:
            detail = redact(str(exc))
            result["decision"] = "error"
            result["errors"] = list(plan.errors) + [f"resolve_apply_failed: {detail}"]
            result["materials"] = list(plan.materials) + [
                {"kind": "resolve_apply_failed", "id": thread_id, "message": detail}
            ]
            break
    else:
        result["decision"] = "hold" if plan.materials else "ready"
    result["applied"] = bool(resolved)
    result["resolved"] = resolved
    return result


def _graphql_records(repo: str, number: int, cursor: str | None) -> dict[str, Any]:
    owner, name = repo_parts(repo)
    command = github_com_api_argv(
        "graphql",
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-F",
        f"number={number}",
        "-f",
        f"query={RECORD_QUERY}",
    )
    if cursor is not None:
        command.extend(["-f", f"cursor={cursor}"])
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
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError("GitHub GraphQL returned errors")
    return payload


def _thread_record(node: dict[str, Any]) -> ThreadRecord:
    comments = node["comments"]
    page_info = comments["pageInfo"]
    if not isinstance(page_info.get("hasNextPage"), bool):
        raise ValueError("review thread comments hasNextPage is invalid")
    return ThreadRecord(
        thread_id=node["id"],
        comments=tuple(
            ThreadComment(
                id=comment["id"],
                body=comment.get("body") or "",
                path=comment.get("path") or "",
                author=(comment.get("author") or {}).get("login", ""),
                original_commit=(comment.get("originalCommit") or {}).get("oid", ""),
            )
            for comment in comments["nodes"]
        ),
        comments_truncated=page_info["hasNextPage"],
    )


def fetch_thread_records(repo: str, number: int) -> dict[str, ThreadRecord]:
    records: dict[str, ThreadRecord] = {}
    seen_cursors: set[str] = set()
    cursor: str | None = None
    for _ in range(MAX_GRAPHQL_PAGES):
        payload = _graphql_records(repo, number, cursor)
        threads = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        for node in threads["nodes"]:
            records[node["id"]] = _thread_record(node)
        page_info = threads["pageInfo"]
        if not isinstance(page_info.get("hasNextPage"), bool):
            raise ValueError("review thread hasNextPage is invalid")
        if not page_info["hasNextPage"]:
            return records
        cursor = page_info.get("endCursor")
        if not cursor or cursor in seen_cursors:
            raise ValueError("review thread pagination cursor did not advance")
        seen_cursors.add(cursor)
    raise ValueError("review thread pagination exceeded safety limit")


class GhLookup:
    def _get(self, path: str, *extra: str) -> str:
        try:
            completed = subprocess.run(
                github_com_api_argv(path, *extra),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=GRAPHQL_TIMEOUT_SECONDS,
                env=github_com_env(),
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            if "HTTP 404" in detail:
                raise NotFound(redact(detail)) from exc
            raise LookupFailure(redact(detail)) from exc
        except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
            raise LookupFailure(redact(str(exc))) from exc
        return completed.stdout

    def compare_status(self, repo: str, base: str, head: str) -> str:
        if not COMMIT_RE.fullmatch(base) or not COMMIT_RE.fullmatch(head):
            raise LookupFailure("invalid_oid")
        owner, name = repo_parts(repo)
        return self._get(
            f"repos/{owner}/{name}/compare/{base}...{head}", "--jq", ".status"
        ).strip()

    def commit_files(self, repo: str, commit: str) -> CommitFiles:
        if not COMMIT_RE.fullmatch(commit):
            raise LookupFailure("invalid_oid")
        owner, name = repo_parts(repo)
        try:
            payload = json.loads(self._get(f"repos/{owner}/{name}/commits/{commit}"))
            files = payload["files"]
            paths = {item["filename"] for item in files}
            paths |= {
                item["previous_filename"]
                for item in files
                if item.get("previous_filename")
            }
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LookupFailure(f"unexpected_github_response: {exc}") from exc
        return CommitFiles(
            paths=frozenset(paths), truncated=len(files) >= COMMIT_FILES_LIMIT
        )

    def issue_number(self, repo: str, number: int) -> int:
        owner, name = repo_parts(repo)
        raw = self._get(f"repos/{owner}/{name}/issues/{number}", "--jq", ".number")
        try:
            return int(raw.strip())
        except ValueError as exc:
            raise LookupFailure("unexpected_github_response") from exc


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


def take_audit(repo: str, number: int) -> AuditResult:
    try:
        return summarize(fetch(repo, number))
    except API_ERRORS as exc:
        return _audit_error_from_exc(exc)


def _stale_reason(plan: ResolvePlan, fresh: AuditResult) -> str | None:
    if fresh.decision == "error" or fresh.errors or fresh.truncated:
        return "recheck_failed"
    if fresh.head_ref_oid != plan.audit.get("head_ref_oid"):
        return "head_changed"
    if fresh.base_ref_oid != plan.audit.get("base_ref_oid"):
        return "base_changed"
    states = {thread.id: thread.state for thread in fresh.threads}
    for thread_id in plan.resolve_thread_ids:
        if states.get(thread_id, "resolved") == "resolved":
            return "thread_no_longer_unresolved"
    return None


def run_resolve(
    repo: str,
    number: int,
    *,
    proposed_thread_ids: tuple[str, ...] | None = None,
    apply: bool = False,
    resolver: Callable[[str], dict[str, Any]] | None = None,
    expected_login: str | None = None,
    lookup: GitHubLookup | None = None,
    records_source: Callable[[str, int], Mapping[str, ThreadRecord]] = fetch_thread_records,
    audit_source: Callable[[str, int], AuditResult] = take_audit,
) -> dict[str, Any]:
    audit = audit_source(repo, number)
    records: Mapping[str, ThreadRecord] | None = None
    record_errors: tuple[str, ...] = ()
    has_unresolved = any(thread.state != "resolved" for thread in audit.threads)
    if expected_login and has_unresolved and audit.decision != "error" and not audit.truncated:
        try:
            records = records_source(repo, number)
        except API_ERRORS as exc:
            record_errors = (f"records_fetch_failed: {redact(str(exc))}",)

    plan = plan_resolve(
        audit,
        records=records,
        expected_login=expected_login,
        repo=repo,
        pr_number=number,
        lookup=lookup if lookup is not None else GhLookup(),
        proposed_thread_ids=proposed_thread_ids,
    )
    if record_errors:
        plan = replace(plan, errors=plan.errors + record_errors)

    if apply and plan.resolve_thread_ids:
        fresh = audit_source(repo, number)
        stale = _stale_reason(plan, fresh)
        if stale is None:
            try:
                fresh_records = records_source(repo, number)
            except API_ERRORS:
                stale = "recheck_failed"
            else:
                replanned = plan_resolve(
                    fresh,
                    records=fresh_records,
                    expected_login=expected_login,
                    repo=repo,
                    pr_number=number,
                    lookup=lookup if lookup is not None else GhLookup(),
                    proposed_thread_ids=proposed_thread_ids,
                )
                if replanned.resolve_thread_ids != plan.resolve_thread_ids:
                    stale = "verdict_changed"
        if stale is not None:
            result = apply_resolve(plan, apply=False)
            result["decision"] = "error"
            result["errors"] = list(plan.errors) + [f"stale_audit:{stale}"]
            return result
    return apply_resolve(plan, apply=apply, resolver=resolver)
