from __future__ import annotations

import json
from pathlib import Path

from github_ops.command import CommandResult
from scripts.github_remote_branch_audit import audit_remote_branches


class FakeRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = list(responses)

    def run(self, argv, **kwargs):
        # IdentityProbe consumes the first three commands; the rest are the audit reads.
        return self.responses.pop(0)


def _identity_ready() -> list[CommandResult]:
    return [
        CommandResult(0, "https://github.com/nexus-ai-2045/github-ops-skills.git\n", ""),
        CommandResult(0, "https://github.com/nexus-ai-2045/github-ops-skills.git\n", ""),
        CommandResult(0, "nexus-ai-2045\n", ""),
    ]


def _audit_responses(branches, prs) -> list[CommandResult]:
    return _identity_ready() + [
        CommandResult(0, json.dumps({"nameWithOwner": "nexus-ai-2045/github-ops-skills", "defaultBranchRef": {"name": "main"}}), ""),
        CommandResult(0, json.dumps([branches]), ""),
        CommandResult(0, json.dumps(prs), ""),
    ]


def test_classifies_only_exact_merged_heads_as_candidates(tmp_path: Path) -> None:
    branches = [
        {"name": "main", "commit": {"sha": "m"}, "protected": True},
        {"name": "merged", "commit": {"sha": "a"}, "protected": False},
        {"name": "changed", "commit": {"sha": "b"}, "protected": False},
        {"name": "open", "commit": {"sha": "c"}, "protected": False},
        {"name": "unknown", "commit": {"sha": "d"}, "protected": False},
    ]
    prs = [
        {"number": 1, "state": "MERGED", "headRefName": "merged", "headRefOid": "a"},
        {"number": 2, "state": "MERGED", "headRefName": "changed", "headRefOid": "old"},
        {"number": 3, "state": "OPEN", "headRefName": "open", "headRefOid": "c"},
    ]
    outcome = audit_remote_branches(
        FakeRunner(_audit_responses(branches, prs)),
        tmp_path,
        "nexus-ai-2045/github-ops-skills",
        expected_owner="nexus-ai-2045",
        expected_login="nexus-ai-2045",
    )
    assert outcome.status.value == "READY"
    assert outcome.evidence["candidates"] == [{"branch": "merged", "sha": "a", "pr": 1}]
    by_name = {row["branch"]: row["classification"] for row in outcome.evidence["branches"]}
    assert by_name == {
        "main": "default_branch",
        "merged": "merged_head_exact",
        "changed": "merged_head_changed",
        "open": "pr_not_merged",
        "unknown": "no_pr_evidence",
    }
    assert outcome.evidence["mutation_performed"] is False


def test_unreadable_remote_data_is_unknown() -> None:
    responses = _identity_ready() + [CommandResult(1, "", "API unavailable")]
    outcome = audit_remote_branches(
        FakeRunner(responses),
        Path("."),
        "nexus-ai-2045/github-ops-skills",
        expected_owner="nexus-ai-2045",
        expected_login="nexus-ai-2045",
    )
    assert outcome.status.value == "UNKNOWN"
    assert outcome.code == "repository_unverified"
