import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.execute_private_canary import (
    CanaryExecutionError,
    ExecutionRequest,
    execute_private_canary,
    validate_execution_request,
)
from github_ops.command import CommandResult


def request(**overrides) -> ExecutionRequest:
    values = {
        "target_repo": "nexus-ai-2045/github-ops-skills",
        "repo_path": Path("."),
        "branch": "canary/github-ops-skills",
        "draft_pr_title": "GitHub操作経路canary",
        "expected_account": "nexus-ai-2045",
        "approval_ref": (
            "L4-CANARY:nexus-ai-2045/github-ops-skills:"
            "canary/github-ops-skills"
        ),
        "confirm_private_canary": True,
        "execute": True,
    }
    values.update(overrides)
    return ExecutionRequest(**values)


def test_execution_requires_all_external_gates() -> None:
    errors = validate_execution_request(
        request(execute=False, confirm_private_canary=False, approval_ref=None)
    )
    assert errors == [
        "execute_missing",
        "confirmation_missing",
        "approval_ref_mismatch",
    ]


def test_execution_requires_canary_branch() -> None:
    errors = validate_execution_request(request(branch="main"))
    assert "approval_ref_mismatch" in errors
    assert "canary_branch_required" in errors
    assert "protected_branch_rejected" in errors


def test_execution_rejects_unsafe_names() -> None:
    errors = validate_execution_request(
        request(target_repo="owner/repo;bad", branch="canary/../bad")
    )
    assert "target_repo_invalid" in errors
    assert "canary_branch_invalid" in errors


def test_gate_failure_runs_no_commands() -> None:
    class FailingRunner:
        def run(self, *args, **kwargs):
            raise AssertionError("command must not run before approval gate")

    with pytest.raises(CanaryExecutionError) as caught:
        execute_private_canary(request(execute=False), runner=FailingRunner())
    assert caught.value.code == "execution_gate_blocked"
    assert caught.value.changed is False


def test_branch_probe_failure_is_not_treated_as_absent(tmp_path: Path) -> None:
    class Runner:
        def run(self, argv, **kwargs):
            command = tuple(argv[:3])
            if command == ("git", "status", "--porcelain=v1"):
                return CommandResult(0, "", "")
            if command == ("git", "remote", "get-url"):
                return CommandResult(
                    0,
                    "https://github.com/nexus-ai-2045/github-ops-skills.git\n",
                    "",
                )
            if argv[:4] == ["gh", "api", "user", "--jq"]:
                return CommandResult(0, "nexus-ai-2045\n", "")
            if argv[:3] == ["gh", "repo", "view"]:
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "nameWithOwner": "nexus-ai-2045/github-ops-skills",
                            "visibility": "PRIVATE",
                            "viewerPermission": "ADMIN",
                            "defaultBranchRef": {"name": "main"},
                        }
                    ),
                    "",
                )
            if argv[:2] == ["gh", "api"]:
                return CommandResult(1, "", "network unavailable")
            raise AssertionError(argv)

    with pytest.raises(CanaryExecutionError) as caught:
        execute_private_canary(request(repo_path=tmp_path), runner=Runner())
    assert caught.value.code == "branch_absence_unverified"
    assert caught.value.changed is False


def test_happy_path_requires_draft_read_back_and_keeps_cleanup_manual(
    tmp_path: Path,
) -> None:
    commands = []

    class Runner:
        def run(self, argv, **kwargs):
            commands.append(list(argv))
            if argv[:3] == ["git", "status", "--porcelain=v1"]:
                return CommandResult(0, "", "")
            if argv[:3] == ["git", "remote", "get-url"]:
                return CommandResult(
                    0,
                    "https://github.com/nexus-ai-2045/github-ops-skills.git\n",
                    "",
                )
            if argv[:4] == ["gh", "api", "user", "--jq"]:
                return CommandResult(0, "nexus-ai-2045\n", "")
            if argv[:3] == ["gh", "repo", "view"]:
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "nameWithOwner": "nexus-ai-2045/github-ops-skills",
                            "visibility": "PRIVATE",
                            "viewerPermission": "ADMIN",
                            "defaultBranchRef": {"name": "main"},
                        }
                    ),
                    "",
                )
            if argv[:2] == ["gh", "api"]:
                return CommandResult(1, "", "HTTP 404: Not Found")
            if argv[:3] == ["gh", "pr", "create"]:
                return CommandResult(0, "https://github.com/example/pr/3\n", "")
            if argv[:3] == ["gh", "pr", "view"]:
                return CommandResult(
                    0,
                    json.dumps(
                        {
                            "number": 3,
                            "isDraft": True,
                            "state": "OPEN",
                            "url": "https://github.com/example/pr/3",
                            "headRefName": "canary/github-ops-skills",
                            "baseRefName": "main",
                        }
                    ),
                    "",
                )
            return CommandResult(0, "", "")

    result = execute_private_canary(
        request(repo_path=tmp_path),
        runner=Runner(),
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
    )

    assert result["verified"] is True
    assert result["automatic_cleanup"] is False
    assert (tmp_path / ".github/private-canary/github-ops-skills.json").exists()
    assert any(command[:3] == ["git", "push", "origin"] for command in commands)
    assert any(command[:3] == ["gh", "pr", "create"] for command in commands)
