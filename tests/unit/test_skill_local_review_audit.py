from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/github-cli-ops-guard/scripts/github_pr_review_thread_audit.py"
)


def _load_module():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("skill_local_review_audit", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_graphql_uses_a_finite_timeout(monkeypatch) -> None:
    module = _load_module()
    captured = {}

    class Completed:
        stdout = '{"data": {}}'

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN003
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.graphql("owner", "repo", 3)
    assert captured["timeout"] == 30


def test_json_output_includes_unresolved_thread_details(
    monkeypatch, capsys
) -> None:
    module = _load_module()
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "headRefOid": "abc123",
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [
                            {
                                "id": "thread-1",
                                "isResolved": False,
                                "isOutdated": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "body": "**Fix timeout**\nDetails",
                                            "path": "audit.py",
                                            "line": 12,
                                        }
                                    ]
                                },
                            }
                        ],
                    },
                }
            }
        }
    }
    monkeypatch.setattr(module, "graphql", lambda *args, **kwargs: payload)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--repo", "owner/repo", "--pr", "3", "--json"],
    )
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["threads"] == [
        {
            "id": "thread-1",
            "state": "unresolved_current",
            "path": "audit.py",
            "line": 12,
            "title": "Fix timeout",
        }
    ]


def test_audit_fetches_every_page_in_both_snapshots(monkeypatch, capsys) -> None:
    module = _load_module()
    first = {
        "data": {"repository": {"pullRequest": {
            "headRefOid": "abc123",
            "reviewThreads": {
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                "nodes": [],
            },
        }}}
    }
    second = {
        "data": {"repository": {"pullRequest": {
            "headRefOid": "abc123",
            "reviewThreads": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [],
            },
        }}}
    }
    calls = []

    def fake_graphql(owner, name, number, cursor=None):  # noqa: ANN001, ANN202
        calls.append(cursor)
        return deepcopy(second if cursor else first)

    monkeypatch.setattr(module, "graphql", fake_graphql)
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--repo", "owner/repo", "--pr", "3", "--json"]
    )
    assert module.main() == 0
    assert calls == [None, "cursor-1", None, "cursor-1"]
    assert json.loads(capsys.readouterr().out)["decision"] == "pass"


def test_audit_rejects_head_change_during_pagination(monkeypatch, capsys) -> None:
    module = _load_module()
    first = {
        "data": {"repository": {"pullRequest": {
            "headRefOid": "abc123",
            "reviewThreads": {
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                "nodes": [],
            },
        }}}
    }
    second = {
        "data": {"repository": {"pullRequest": {
            "headRefOid": "changed",
            "reviewThreads": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [],
            },
        }}}
    }
    monkeypatch.setattr(
        module, "graphql", lambda *args: second if len(args) == 4 else first
    )
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--repo", "owner/repo", "--pr", "3", "--json"]
    )
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "error"
    assert "head changed" in result["errors"][0]


def test_audit_rejects_repeated_pagination_cursor(monkeypatch, capsys) -> None:
    module = _load_module()
    payload = {
        "data": {"repository": {"pullRequest": {
            "headRefOid": "abc123",
            "reviewThreads": {
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                "nodes": [],
            },
        }}}
    }
    monkeypatch.setattr(module, "graphql", lambda *args: payload)
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--repo", "owner/repo", "--pr", "3", "--json"]
    )
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "error"
    assert "cursor did not advance" in result["errors"][0]


def test_audit_rejects_graphql_errors(monkeypatch, capsys) -> None:
    module = _load_module()
    payload = {
        "errors": [{"message": "partial response"}],
        "data": {"repository": {"pullRequest": {
            "headRefOid": "abc123",
            "reviewThreads": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [],
            },
        }}},
    }
    monkeypatch.setattr(module, "graphql", lambda *args: payload)
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--repo", "owner/repo", "--pr", "3", "--json"]
    )
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "error"
    assert "GraphQL returned errors" in result["errors"][0]


def test_audit_rejects_non_object_graphql_payload(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "graphql", lambda *args: [])
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--repo", "owner/repo", "--pr", "3", "--json"]
    )
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "error"
    assert "not an object" in result["errors"][0]


def test_audit_rejects_head_change_after_last_page(monkeypatch, capsys) -> None:
    module = _load_module()
    initial = {
        "data": {"repository": {"pullRequest": {
            "headRefOid": "abc123",
            "reviewThreads": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [],
            },
        }}}
    }
    changed = {
        "data": {"repository": {"pullRequest": {
            "headRefOid": "changed",
            "reviewThreads": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [],
            },
        }}}
    }
    payloads = iter((initial, changed))
    monkeypatch.setattr(module, "graphql", lambda *args: next(payloads))
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--repo", "owner/repo", "--pr", "3", "--json"]
    )
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "error"
    assert "head changed" in result["errors"][0]


def test_audit_rejects_thread_change_between_snapshots(monkeypatch, capsys) -> None:
    module = _load_module()
    initial = {
        "data": {"repository": {"pullRequest": {
            "headRefOid": "abc123",
            "reviewThreads": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [],
            },
        }}}
    }
    changed = {
        "data": {"repository": {"pullRequest": {
            "headRefOid": "abc123",
            "reviewThreads": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{
                    "id": "new-thread",
                    "isResolved": False,
                    "isOutdated": False,
                    "comments": {"nodes": []},
                }],
            },
        }}}
    }
    payloads = iter((initial, changed))
    monkeypatch.setattr(module, "graphql", lambda *args: next(payloads))
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--repo", "owner/repo", "--pr", "3", "--json"]
    )
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "error"
    assert "thread state changed" in result["errors"][0]
