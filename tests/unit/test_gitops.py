from pathlib import Path

import pytest

from github_ops.gitops import (
    DesiredRepositoryState,
    GitOpsConfigError,
    compare_repository_state,
    load_desired_state,
)


def actual_state(**overrides):
    value = {
        "nameWithOwner": "nexus-ai-2045/tooling",
        "visibility": "PRIVATE",
        "defaultBranchRef": {"name": "main"},
        "description": "安全なGitHub運用",
        "hasIssuesEnabled": True,
        "hasWikiEnabled": False,
        "hasDiscussionsEnabled": False,
        "hasProjectsEnabled": False,
    }
    value.update(overrides)
    return value


def desired_state(**settings):
    base = {"visibility": "PRIVATE", "default_branch": "main"}
    base.update(settings)
    return DesiredRepositoryState("nexus-ai-2045/tooling", base)


def test_in_sync_is_ready() -> None:
    result = compare_repository_state(desired_state(), actual_state())
    assert result.status.value == "READY"
    assert result.code == "gitops_in_sync"


def test_drift_is_blocked_and_never_auto_applied() -> None:
    result = compare_repository_state(
        desired_state(description="期待する説明"), actual_state()
    )
    assert result.status.value == "BLOCKED"
    assert result.code == "gitops_drift_detected"
    assert result.evidence["drift"] == [
        {
            "setting": "description",
            "desired": "期待する説明",
            "actual": "安全なGitHub運用",
        }
    ]


def test_repository_mismatch_is_blocked() -> None:
    result = compare_repository_state(
        desired_state(), actual_state(nameWithOwner="other/tooling")
    )
    assert result.code == "gitops_repository_mismatch"


def test_load_desired_state_validates_schema(tmp_path: Path) -> None:
    config = tmp_path / "desired.yaml"
    config.write_text(
        "schema_version: github-ops/repository-state/v1\n"
        "repository: nexus-ai-2045/tooling\n"
        "settings:\n  visibility: PRIVATE\n",
        encoding="utf-8",
    )
    assert load_desired_state(config).settings == {"visibility": "PRIVATE"}


def test_unknown_setting_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "desired.yaml"
    config.write_text(
        "schema_version: github-ops/repository-state/v1\n"
        "repository: nexus-ai-2045/tooling\n"
        "settings:\n  dangerous_auto_apply: true\n",
        encoding="utf-8",
    )
    with pytest.raises(GitOpsConfigError):
        load_desired_state(config)
