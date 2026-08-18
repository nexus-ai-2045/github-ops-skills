from __future__ import annotations

import subprocess

from scripts import github_pr_review_thread_audit


def test_cli_converts_timeout_to_structured_error(monkeypatch, capsys) -> None:
    def timeout(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise subprocess.TimeoutExpired(["gh", "api", "graphql"], 30)

    monkeypatch.setattr(github_pr_review_thread_audit, "fetch", timeout)
    result = github_pr_review_thread_audit.main(
        ["--repo", "owner/repo", "--pr", "3", "--json"]
    )
    output = capsys.readouterr().out
    assert result == 1
    assert '"decision": "error"' in output
    assert "gh_api_timeout" in output
