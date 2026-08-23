"""Portable GitHub PR review-thread audit (read-only).

Absorbed from the existing workspace helper
`shared/scripts/github_pr_review_thread_audit.py` without inventing a new
merge product. This module only classifies reviewThreads resolution state.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from typing import Any

from .redaction import redact

THREAD_QUERY = """
query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      headRefOid
      baseRefOid
      reviewThreads(first:100, after:$cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          isResolved
          isOutdated
          comments(last:1) {
            nodes {
              id
              path
              line
              originalLine
              body
              author { login }
              commit { oid }
              originalCommit { oid }
            }
          }
        }
      }
    }
  }
}
"""

GRAPHQL_TIMEOUT_SECONDS = 30
MAX_GRAPHQL_PAGES = 100


@dataclass(frozen=True)
class ThreadSummary:
    id: str
    state: str
    path: str
    line: int | None
    author: str
    title: str
    commit: str
    original_commit: str


@dataclass(frozen=True)
class AuditResult:
    decision: str
    head_ref_oid: str
    base_ref_oid: str
    resolved: int
    unresolved_current: int
    unresolved_outdated: int
    threads: list[ThreadSummary]
    errors: list[str]
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def repo_parts(repo: str) -> tuple[str, str]:
    parts = repo.strip().split("/", 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError("repo must be in owner/name format")
    return parts[0], parts[1]


def comment_title(body: str) -> str:
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    marker = "</sub></sub>"
    if marker in first_line:
        first_line = first_line.split(marker, 1)[1].strip()
    return first_line.strip("* ")


def summarize(payload: dict[str, Any]) -> AuditResult:
    _validate_graphql_payload(payload)
    pull_request = payload["data"]["repository"]["pullRequest"]
    head_ref_oid = pull_request["headRefOid"]
    if not isinstance(head_ref_oid, str) or not head_ref_oid:
        raise ValueError("pull request head oid is missing")
    base_ref_oid = pull_request["baseRefOid"]
    if not isinstance(base_ref_oid, str) or not base_ref_oid:
        raise ValueError("pull request base oid is missing")
    summaries: list[ThreadSummary] = []
    resolved = 0
    unresolved_current = 0
    unresolved_outdated = 0
    page_info = _page_info(pull_request)
    truncated = bool(page_info.get("hasNextPage"))
    nodes = pull_request["reviewThreads"]["nodes"]
    if not isinstance(nodes, list):
        raise ValueError("review thread nodes is not a list")

    for thread in nodes:
        if not isinstance(thread.get("isResolved"), bool) or not isinstance(
            thread.get("isOutdated"), bool
        ):
            raise ValueError("review thread state is not boolean")
        comments = thread["comments"]["nodes"]
        latest_comment = comments[-1] if comments else {}
        if thread["isResolved"]:
            state = "resolved"
            resolved += 1
        elif thread["isOutdated"]:
            state = "unresolved_outdated"
            unresolved_outdated += 1
        else:
            state = "unresolved_current"
            unresolved_current += 1

        summaries.append(
            ThreadSummary(
                id=thread["id"],
                state=state,
                path=redact(latest_comment.get("path", "")),
                line=(
                    latest_comment.get("line")
                    if latest_comment.get("line") is not None
                    else latest_comment.get("originalLine")
                ),
                author=(latest_comment.get("author") or {}).get("login", ""),
                title=redact(comment_title(latest_comment.get("body", ""))),
                commit=(latest_comment.get("commit") or {}).get("oid", ""),
                original_commit=(latest_comment.get("originalCommit") or {}).get(
                    "oid", ""
                ),
            )
        )

    decision = (
        "pass"
        if unresolved_current == 0 and unresolved_outdated == 0 and not truncated
        else "warn"
    )
    return AuditResult(
        decision=decision,
        head_ref_oid=head_ref_oid,
        base_ref_oid=base_ref_oid,
        resolved=resolved,
        unresolved_current=unresolved_current,
        unresolved_outdated=unresolved_outdated,
        threads=summaries,
        errors=[],
        truncated=truncated,
    )


def error_result(message: str) -> AuditResult:
    return AuditResult(
        decision="error",
        head_ref_oid="",
        base_ref_oid="",
        resolved=0,
        unresolved_current=0,
        unresolved_outdated=0,
        threads=[],
        errors=[message],
        truncated=False,
    )


def graphql(repo: str, number: int, cursor: str | None = None) -> dict[str, Any]:
    owner, name = repo_parts(repo)
    command = [
        "gh",
        "api",
        "--hostname",
        "github.com",
        "graphql",
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-F",
        f"number={number}",
        "-f",
        f"query={THREAD_QUERY}",
    ]
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
    )
    return json.loads(completed.stdout)


def _fetch_snapshot(repo: str, number: int) -> dict[str, Any]:
    payload = graphql(repo, number)
    _validate_graphql_payload(payload)
    pull_request = payload["data"]["repository"]["pullRequest"]
    nodes = pull_request["reviewThreads"]["nodes"]
    if not isinstance(nodes, list):
        raise ValueError("review thread nodes is not a list")
    all_threads = list(nodes)
    page_info = _page_info(pull_request)
    head_ref_oid = pull_request["headRefOid"]
    if not isinstance(head_ref_oid, str) or not head_ref_oid:
        raise ValueError("pull request head oid is missing")
    base_ref_oid = pull_request["baseRefOid"]
    if not isinstance(base_ref_oid, str) or not base_ref_oid:
        raise ValueError("pull request base oid is missing")
    seen_cursors: set[str] = set()
    page_count = 1

    while page_info.get("hasNextPage"):
        cursor = page_info.get("endCursor")
        if not cursor or cursor in seen_cursors:
            raise ValueError("review thread pagination cursor did not advance")
        if page_count >= MAX_GRAPHQL_PAGES:
            raise ValueError("review thread pagination exceeded safety limit")
        seen_cursors.add(cursor)
        payload_page = graphql(repo, number, cursor)
        _validate_graphql_payload(payload_page)
        pull_request_page = payload_page["data"]["repository"]["pullRequest"]
        if pull_request_page["headRefOid"] != head_ref_oid:
            raise ValueError("pull request head changed during review thread audit")
        if pull_request_page["baseRefOid"] != base_ref_oid:
            raise ValueError("pull request base changed during review thread audit")
        page_nodes = pull_request_page["reviewThreads"]["nodes"]
        if not isinstance(page_nodes, list):
            raise ValueError("review thread nodes is not a list")
        all_threads.extend(page_nodes)
        page_info = _page_info(pull_request_page)
        page_count += 1

    pull_request["reviewThreads"]["nodes"] = all_threads
    pull_request["reviewThreads"]["pageInfo"] = page_info
    return payload


def fetch(repo: str, number: int) -> dict[str, Any]:
    first = _fetch_snapshot(repo, number)
    second = _fetch_snapshot(repo, number)
    first_pull = first["data"]["repository"]["pullRequest"]
    second_pull = second["data"]["repository"]["pullRequest"]
    if first_pull["headRefOid"] != second_pull["headRefOid"]:
        raise ValueError("pull request head changed during review thread audit")
    if first_pull["baseRefOid"] != second_pull["baseRefOid"]:
        raise ValueError("pull request base changed during review thread audit")
    if first_pull["reviewThreads"]["nodes"] != second_pull["reviewThreads"]["nodes"]:
        raise ValueError("review thread state changed during audit")
    return second


def _validate_graphql_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("GitHub GraphQL payload is not an object")
    if payload.get("errors"):
        raise ValueError("GitHub GraphQL returned errors")


def _page_info(pull_request: dict[str, Any]) -> dict[str, Any]:
    page_info = pull_request["reviewThreads"]["pageInfo"]
    if not isinstance(page_info, dict):
        raise ValueError("review thread pageInfo is missing")
    if not isinstance(page_info.get("hasNextPage"), bool):
        raise ValueError("review thread hasNextPage is invalid")
    return page_info
