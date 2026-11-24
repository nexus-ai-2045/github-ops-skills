from __future__ import annotations

import json
from pathlib import Path

import pytest

from github_ops.gh_write_policy import ALLOWED_SUBCOMMANDS, check_scope, classify

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "gh_write_policy_golden.jsonl"
TARGET = "nexus-ai-2045/github-ops-skills"


def _decide(gh_args: list[str], confirm_repo: str | None) -> list[str | None]:
    result = classify(gh_args)
    if result.reason is not None:
        return [result.subcommand, result.reason]
    return [result.subcommand, check_scope(gh_args, TARGET, confirm_repo)]


def _golden_rows() -> list[list]:
    return [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line]


def test_golden_matches_projects_entrypoint_decisions() -> None:
    rows = _golden_rows()
    assert len(rows) > 2000
    mismatches = [
        (gh_args, confirm, [sub, reason], _decide(gh_args, confirm))
        for gh_args, confirm, sub, reason in rows
        if _decide(gh_args, confirm) != [sub, reason]
    ]
    assert mismatches == []


def test_golden_covers_every_allowlisted_operation() -> None:
    allowed = {
        tuple(gh_args[:2])
        for gh_args, _confirm, _sub, reason in _golden_rows()
        if reason is None and gh_args and gh_args[0] != "api"
    }
    expected = {(top, sub) for top, subs in ALLOWED_SUBCOMMANDS.items() for sub in subs}
    assert expected <= allowed


@pytest.mark.parametrize(
    ("gh_args", "reason"),
    [
        (["pr", "merge", "1"], "pr_merge_use_pr_merge_guarded"),
        (["release", "create", "v1"], "release_not_allowed"),
        (["repo", "delete", TARGET], "subcommand_not_allowlisted"),
        (["secret", "set", "X"], "subcommand_not_allowlisted"),
        ([], "empty_gh_command"),
    ],
)
def test_classify_denies_operations_outside_the_table(gh_args: list[str], reason: str) -> None:
    assert classify(gh_args).reason == reason


def test_repo_rename_needs_confirmation_and_explicit_target() -> None:
    args = ["repo", "rename", "new-name", "--repo", TARGET]
    assert check_scope(args, TARGET, None) == "repo_change_needs_confirm"
    assert check_scope(args, TARGET, TARGET) is None
    assert check_scope(["repo", "rename", "new-name"], TARGET, TARGET) == "repo_change_target_not_explicit"


@pytest.mark.parametrize(
    "method_args",
    [
        ["-iXDELETE"],
        ["-iX", "DELETE"],
        ["-i", "-X", "DELETE"],
        ["-X=DELETE"],
        ["-iX=PATCH"],
        ["-if", "name=x"],
        ["-Z"],
    ],
)
def test_grouped_short_flags_cannot_hide_a_write_to_the_repository_root(method_args: list[str]) -> None:
    args = ["api", f"repos/{TARGET}", *method_args]
    assert check_scope(args, TARGET) == "api_path_needs_dedicated_entrypoint"


@pytest.mark.parametrize("method_args", [["-i"], ["-q", ".name"], ["-qXDELETE"], ["-X", "GET"]])
def test_reads_of_the_repository_root_stay_allowed(method_args: list[str]) -> None:
    assert check_scope(["api", f"repos/{TARGET}", *method_args], TARGET) is None


def test_api_write_to_dedicated_path_is_denied() -> None:
    args = ["api", f"repos/{TARGET}/pulls/2/merge", "-X", "PUT"]
    assert check_scope(args, TARGET) == "api_path_needs_dedicated_entrypoint"
