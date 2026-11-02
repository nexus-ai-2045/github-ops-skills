#!/usr/bin/env python3
"""Runtime-portable, read-only PR review-thread audit."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

QUERY = """
query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      headRefOid
      baseRefOid
      reviewThreads(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          comments(last:1) { nodes { body path line originalLine } }
        }
      }
    }
  }
}
"""

GRAPHQL_TIMEOUT_SECONDS = 30
MAX_GRAPHQL_PAGES = 100
TOKEN_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)(Authorization:\s*Bearer\s+)\S+"),
    re.compile(r"(?i)(GH_TOKEN\s*=\s*)\S+"),
)


def redact(text: str) -> str:
    result = text
    for pattern in TOKEN_PATTERNS:
        result = pattern.sub(
            lambda match: f"{match.group(1) if match.lastindex else ''}[REDACTED]",
            result,
        )
    return result


def comment_title(body: str) -> str:
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    marker = "</sub></sub>"
    if marker in first_line:
        first_line = first_line.split(marker, 1)[1].strip()
    return first_line.strip("* ")


def graphql(owner: str, name: str, number: int, cursor: str | None = None) -> dict:
    command = [
        "gh", "api", "--hostname", "github.com", "graphql", "-f", f"owner={owner}", "-f", f"name={name}",
        "-F", f"number={number}", "-f", f"query={QUERY}",
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


def fetch_snapshot(owner: str, name: str, number: int) -> dict:
    payload = graphql(owner, name, number)
    _validate_graphql_payload(payload)
    pull = payload["data"]["repository"]["pullRequest"]
    if not isinstance(pull["headRefOid"], str) or not pull["headRefOid"]:
        raise ValueError("pull request head oid is missing")
    if not isinstance(pull["baseRefOid"], str) or not pull["baseRefOid"]:
        raise ValueError("pull request base oid is missing")
    threads = list(pull["reviewThreads"]["nodes"])
    page = _page_info(pull)
    head_ref_oid = pull["headRefOid"]
    base_ref_oid = pull["baseRefOid"]
    seen_cursors: set[str] = set()
    page_count = 1
    while page["hasNextPage"]:
        cursor = page.get("endCursor")
        if not cursor or cursor in seen_cursors:
            raise ValueError("review thread pagination cursor did not advance")
        if page_count >= MAX_GRAPHQL_PAGES:
            raise ValueError("review thread pagination exceeded safety limit")
        seen_cursors.add(cursor)
        page_payload = graphql(owner, name, number, cursor)
        _validate_graphql_payload(page_payload)
        page_pull = page_payload["data"]["repository"]["pullRequest"]
        if page_pull["headRefOid"] != head_ref_oid:
            raise ValueError("pull request head changed during review thread audit")
        if page_pull["baseRefOid"] != base_ref_oid:
            raise ValueError("pull request base changed during review thread audit")
        threads.extend(page_pull["reviewThreads"]["nodes"])
        page = _page_info(page_pull)
        page_count += 1
    pull["reviewThreads"]["nodes"] = threads
    pull["reviewThreads"]["pageInfo"] = page
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.repo.count("/") != 1:
            raise ValueError("repo must be in owner/name format")
        owner, name = args.repo.split("/", 1)
        if not owner or not name:
            raise ValueError("repo must be in owner/name format")
        payload = fetch_snapshot(owner, name, args.pr)
        pull = payload["data"]["repository"]["pullRequest"]
        threads = list(pull["reviewThreads"]["nodes"])
        head_ref_oid = pull["headRefOid"]
        base_ref_oid = pull["baseRefOid"]
        final_payload = fetch_snapshot(owner, name, args.pr)
        final_pull = final_payload["data"]["repository"]["pullRequest"]
        if final_pull["headRefOid"] != head_ref_oid:
            raise ValueError("pull request head changed during review thread audit")
        if final_pull["baseRefOid"] != base_ref_oid:
            raise ValueError("pull request base changed during review thread audit")
        if final_pull["reviewThreads"]["nodes"] != threads:
            raise ValueError("review thread state changed during audit")
        if any(
            not isinstance(item.get("isResolved"), bool)
            or not isinstance(item.get("isOutdated"), bool)
            for item in threads
        ):
            raise ValueError("review thread state is not boolean")
        current = sum(not item["isResolved"] and not item["isOutdated"] for item in threads)
        outdated = sum(not item["isResolved"] and item["isOutdated"] for item in threads)
        unresolved = []
        for item in threads:
            if item["isResolved"]:
                continue
            comments = item["comments"]["nodes"]
            latest = comments[-1] if comments else {}
            unresolved.append(
                {
                    "id": item["id"],
                    "state": (
                        "unresolved_outdated"
                        if item["isOutdated"]
                        else "unresolved_current"
                    ),
                    "path": redact(latest.get("path", "")),
                    "line": (
                        latest.get("line")
                        if latest.get("line") is not None
                        else latest.get("originalLine")
                    ),
                    "title": redact(comment_title(latest.get("body", ""))),
                }
            )
        result = {
            "decision": "pass" if current == 0 and outdated == 0 else "warn",
            "head_ref_oid": pull["headRefOid"],
            "base_ref_oid": pull["baseRefOid"],
            "unresolved_current": current,
            "unresolved_outdated": outdated,
            "threads": unresolved,
        }
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        result = {"decision": "error", "errors": [str(exc)]}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(" ".join(f"{key}={value}" for key, value in result.items()))
    return 0 if result["decision"] == "pass" else 1


def _validate_graphql_payload(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError("GitHub GraphQL payload is not an object")
    if payload.get("errors"):
        raise ValueError("GitHub GraphQL returned errors")


def _page_info(pull: dict) -> dict:
    page = pull["reviewThreads"]["pageInfo"]
    if not isinstance(page, dict):
        raise ValueError("review thread pageInfo is missing")
    if not isinstance(page.get("hasNextPage"), bool):
        raise ValueError("review thread hasNextPage is invalid")
    return page


if __name__ == "__main__":
    raise SystemExit(main())
