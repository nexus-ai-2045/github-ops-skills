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

THREAD_QUERY = """
query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      headRefOid
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
    pull_request = payload["data"]["repository"]["pullRequest"]
    head_ref_oid = pull_request["headRefOid"]
    summaries: list[ThreadSummary] = []
    resolved = 0
    unresolved_current = 0
    unresolved_outdated = 0
    page_info = pull_request["reviewThreads"].get("pageInfo") or {}
    truncated = bool(page_info.get("hasNextPage"))

    for thread in pull_request["reviewThreads"]["nodes"]:
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
                path=latest_comment.get("path", ""),
                line=(
                    latest_comment.get("line")
                    if latest_comment.get("line") is not None
                    else latest_comment.get("originalLine")
                ),
                author=(latest_comment.get("author") or {}).get("login", ""),
                title=comment_title(latest_comment.get("body", "")),
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
    )
    return json.loads(completed.stdout)


def fetch(repo: str, number: int) -> dict[str, Any]:
    payload = graphql(repo, number)
    pull_request = payload["data"]["repository"]["pullRequest"]
    all_threads = pull_request["reviewThreads"]["nodes"]
    page_info = pull_request["reviewThreads"].get("pageInfo") or {}

    while page_info.get("hasNextPage"):
        payload_page = graphql(repo, number, page_info.get("endCursor"))
        pull_request_page = payload_page["data"]["repository"]["pullRequest"]
        all_threads.extend(pull_request_page["reviewThreads"]["nodes"])
        page_info = pull_request_page["reviewThreads"].get("pageInfo") or {}

    pull_request["reviewThreads"]["nodes"] = all_threads
    pull_request["reviewThreads"]["pageInfo"] = page_info
    return payload
