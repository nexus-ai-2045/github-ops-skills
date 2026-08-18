from __future__ import annotations

import importlib.util
import json
import sys
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
