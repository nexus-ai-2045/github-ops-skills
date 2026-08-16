#!/usr/bin/env python3
"""Runtime-portable, read-only PR review-thread audit."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

QUERY = """
query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      headRefOid
      reviewThreads(first:100, after:$cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { id isResolved isOutdated comments(last:1) { nodes { body path line } } }
      }
    }
  }
}
"""


def graphql(owner: str, name: str, number: int, cursor: str = "") -> dict:
    completed = subprocess.run(
        [
            "gh", "api", "graphql", "-f", f"owner={owner}", "-f", f"name={name}",
            "-F", f"number={number}", "-f", f"cursor={cursor}", "-f", f"query={QUERY}",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        owner, name = args.repo.split("/", 1)
        payload = graphql(owner, name, args.pr)
        pull = payload["data"]["repository"]["pullRequest"]
        threads = list(pull["reviewThreads"]["nodes"])
        page = pull["reviewThreads"]["pageInfo"]
        while page["hasNextPage"]:
            payload = graphql(owner, name, args.pr, page["endCursor"])
            connection = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
            threads.extend(connection["nodes"])
            page = connection["pageInfo"]
        current = sum(not item["isResolved"] and not item["isOutdated"] for item in threads)
        outdated = sum(not item["isResolved"] and item["isOutdated"] for item in threads)
        result = {
            "decision": "pass" if current == 0 and outdated == 0 else "warn",
            "head_ref_oid": pull["headRefOid"],
            "unresolved_current": current,
            "unresolved_outdated": outdated,
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


if __name__ == "__main__":
    raise SystemExit(main())
