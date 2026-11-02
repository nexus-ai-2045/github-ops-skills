import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import scripts.execute_private_canary as executor_module

from scripts.execute_private_canary import (
    CanaryExecutionError,
    ExecutionRequest,
    execute_private_canary,
    _parse_remote_sha,
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
        "approval_file": Path("approval.json"),
        "thread_id": "thread-1",
        "confirm_private_canary": True,
        "execute": True,
    }
    values.update(overrides)
    return ExecutionRequest(**values)


@pytest.fixture(autouse=True)
def valid_approval(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        executor_module,
        "validate_approval",
        lambda *args, **kwargs: {"nonce": "n" * 32},
    )
    monkeypatch.setattr(
        executor_module,
        "consume_approval",
        lambda *args, **kwargs: tmp_path / "approval.json.consumed",
    )


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


def test_empty_remote_sha_preserves_external_changed() -> None:
    with pytest.raises(CanaryExecutionError) as caught:
        _parse_remote_sha(CommandResult(0, "", ""))
    assert caught.value.code == "remote_sha_missing"
    assert caught.value.external_changed is True


def test_branch_probe_failure_is_not_treated_as_absent(tmp_path: Path) -> None:
    class Runner:
        def run(self, argv, **kwargs):
            command = tuple(argv[:3])
            if command == ("git", "status", "--porcelain=v1"):
                return CommandResult(0, "", "")
            if argv == ["git", "rev-parse", "HEAD"]:
                return CommandResult(0, "b" * 40 + "\n", "")
            if command == ("git", "remote", "get-url"):
                return CommandResult(
                    0,
                    "https://github.com/nexus-ai-2045/github-ops-skills.git\n",
                    "",
                )
            if argv[:4] == ["gh", "api", "user", "--jq"]:
                return CommandResult(0, "nexus-ai-2045\n", "")
            if argv[:4] == ["gh", "api", "--hostname", "github.com"]:
                return CommandResult(0, "nexus-ai-2045\n", "")
            if argv == ["git", "config", "--get", "user.name"]:
                return CommandResult(0, "nexus_ai\n", "")
            if argv == ["git", "config", "--get", "user.email"]:
                return CommandResult(0, "273569186+nexus-ai-2045@users.noreply.github.com\n", "")
            if argv == ["git", "config", "--get", "credential.https://github.com.username"]:
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
            if argv[:4] == ["gh", "api", "--hostname", "github.com"]:
                return CommandResult(0, "nexus-ai-2045\n", "")
            if argv == ["git", "config", "--get", "user.name"]:
                return CommandResult(0, "nexus_ai\n", "")
            if argv == ["git", "config", "--get", "user.email"]:
                return CommandResult(0, "273569186+nexus-ai-2045@users.noreply.github.com\n", "")
            if argv == ["git", "config", "--get", "credential.https://github.com.username"]:
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
            if argv[:4] == ["git", "ls-tree", "-r", "--name-only"]:
                return CommandResult(0, "", "")
            if argv == ["git", "rev-parse", "origin/main"]:
                return CommandResult(0, "a" * 40 + "\n", "")
            if argv == ["git", "rev-parse", "HEAD"]:
                return CommandResult(0, "b" * 40 + "\n", "")
            if argv[:3] == ["git", "ls-remote", "--heads"]:
                return CommandResult(0, "b" * 40 + "\trefs/heads/canary/github-ops-skills\n", "")
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
                            "headRefOid": "b" * 40,
                            "baseRefOid": "a" * 40,
                            "title": "GitHub操作経路canary",
                            "body": (
                                "L4 private mutation canaryです。\n\n"
                                "- visibility変更なし\n- main mergeなし\n"
                                "- cleanupは別承認\n"
                            ),
                            "files": [
                                {"path": ".github/private-canary/github-ops-skills.json"}
                            ],
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
    assert any(command[:2] == ["git", "push"] for command in commands)
    assert any(command[:3] == ["gh", "pr", "create"] for command in commands)


def test_push_remote_mismatch_blocks_before_approval_consumption(
    monkeypatch, tmp_path: Path
) -> None:
    consumed = False

    def fail_if_consumed(*args, **kwargs):
        nonlocal consumed
        consumed = True
        raise AssertionError("approval must not be consumed")

    monkeypatch.setattr(executor_module, "consume_approval", fail_if_consumed)

    class Runner:
        def run(self, argv, **kwargs):
            if argv[:3] == ["git", "status", "--porcelain=v1"]:
                return CommandResult(0, "", "")
            if argv == ["git", "remote", "get-url", "origin"]:
                return CommandResult(0, "https://github.com/nexus-ai-2045/github-ops-skills.git\n", "")
            if argv == ["git", "remote", "get-url", "--push", "origin"]:
                return CommandResult(0, "https://github.com/elsewhere/repo.git\n", "")
            if argv[:4] == ["gh", "api", "user", "--jq"]:
                return CommandResult(0, "nexus-ai-2045\n", "")
            if argv[:4] == ["gh", "api", "--hostname", "github.com"]:
                return CommandResult(0, "nexus-ai-2045\n", "")
            if argv == ["git", "config", "--get", "user.name"]:
                return CommandResult(0, "nexus_ai\n", "")
            if argv == ["git", "config", "--get", "user.email"]:
                return CommandResult(0, "273569186+nexus-ai-2045@users.noreply.github.com\n", "")
            if argv == ["git", "config", "--get", "credential.https://github.com.username"]:
                return CommandResult(0, "nexus-ai-2045\n", "")
            if argv[:3] == ["gh", "repo", "view"]:
                return CommandResult(0, json.dumps({"nameWithOwner": "nexus-ai-2045/github-ops-skills", "visibility": "PRIVATE", "viewerPermission": "ADMIN", "defaultBranchRef": {"name": "main"}}), "")
            if argv[:2] == ["gh", "api"]:
                return CommandResult(1, "", "HTTP 404: Not Found")
            if argv[:4] == ["git", "ls-tree", "-r", "--name-only"]:
                return CommandResult(0, "", "")
            if argv == ["git", "rev-parse", "origin/main"]:
                return CommandResult(0, "a" * 40 + "\n", "")
            if argv == ["git", "rev-parse", "HEAD"]:
                return CommandResult(0, "b" * 40 + "\n", "")
            return CommandResult(0, "", "")

    with pytest.raises(CanaryExecutionError) as caught:
        execute_private_canary(request(repo_path=tmp_path), runner=Runner())
    assert caught.value.code == "push_remote_mismatch"
    assert consumed is False
