from __future__ import annotations

from github_ops.review_threads import fetch, repo_parts, summarize
from github_ops.review_threads import THREAD_QUERY


def _payload(*threads: dict) -> dict:
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "headRefOid": "abc123",
                    "reviewThreads": {
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        },
                        "nodes": list(threads),
                    },
                },
            },
        },
    }


def _thread(*, resolved: bool, outdated: bool, title: str = "Use token matching") -> dict:
    return {
        "id": "thread-1",
        "isResolved": resolved,
        "isOutdated": outdated,
        "comments": {
            "nodes": [
                {
                    "id": "comment-1",
                    "path": "scripts/example.py",
                    "line": 12,
                    "originalLine": 10,
                    "body": f"**<sub><sub>badge</sub></sub>  {title}**\n\nBody",
                    "author": {"login": "review-bot"},
                    "commit": {"oid": "abc123"},
                    "originalCommit": {"oid": "def456"},
                },
            ],
        },
    }


def test_summarize_passes_when_all_threads_are_resolved() -> None:
    result = summarize(_payload(_thread(resolved=True, outdated=False)))
    assert result.decision == "pass"
    assert result.resolved == 1
    assert result.unresolved_current == 0
    assert result.unresolved_outdated == 0


def test_summarize_warns_for_unresolved_current_and_outdated_threads() -> None:
    result = summarize(
        _payload(
            _thread(resolved=False, outdated=False, title="Current issue"),
            _thread(resolved=False, outdated=True, title="Old issue"),
        )
    )
    assert result.decision == "warn"
    assert result.unresolved_current == 1
    assert result.unresolved_outdated == 1
    assert [thread.state for thread in result.threads] == [
        "unresolved_current",
        "unresolved_outdated",
    ]


def test_repo_parts_requires_owner_name_format() -> None:
    try:
        repo_parts("missing-owner")
    except ValueError as exc:
        assert "owner/name" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_summarize_warns_when_payload_is_truncated() -> None:
    payload = _payload(_thread(resolved=True, outdated=False))
    payload["data"]["repository"]["pullRequest"]["reviewThreads"]["pageInfo"] = {
        "hasNextPage": True,
        "endCursor": "cursor-1",
    }
    result = summarize(payload)
    assert result.decision == "warn"
    assert result.truncated is True


def test_fetch_follows_all_review_thread_pages(monkeypatch) -> None:
    pages = [
        _payload(_thread(resolved=True, outdated=False, title="First page")),
        _payload(_thread(resolved=False, outdated=True, title="Second page")),
    ]
    pages[0]["data"]["repository"]["pullRequest"]["reviewThreads"]["pageInfo"] = {
        "hasNextPage": True,
        "endCursor": "cursor-1",
    }
    calls: list[str | None] = []

    def fake_graphql(repo: str, number: int, cursor: str | None = None) -> dict:
        calls.append(cursor)
        return pages[1] if cursor else pages[0]

    monkeypatch.setattr("github_ops.review_threads.graphql", fake_graphql)
    payload = fetch("owner/name", 123)
    assert calls == [None, "cursor-1"]
    nodes = payload["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    assert len(nodes) == 2


def test_query_requests_latest_comment_only() -> None:
    assert "comments(last:1)" in THREAD_QUERY


def test_graphql_omits_cursor_on_initial_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0
        stdout = '{"data": {}}'
        stderr = ""

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003
        captured["command"] = command
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr("github_ops.review_threads.subprocess.run", fake_run)
    from github_ops.review_threads import graphql

    graphql("owner/name", 3)
    assert not any(str(item).startswith("cursor=") for item in captured["command"])
    assert captured.get("timeout") == 30


def test_summarize_falls_back_to_original_line_for_outdated_comment() -> None:
    thread = _thread(resolved=False, outdated=True)
    thread["comments"]["nodes"][0]["line"] = None
    result = summarize(_payload(thread))
    assert result.threads[0].line == 10
