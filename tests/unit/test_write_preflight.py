from pathlib import Path

from github_ops.command import CommandResult
from github_ops.identity import IdentityProbe
from github_ops.result import Outcome, Status
from github_ops.write_preflight import evaluate_write_preflight


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], CommandResult]) -> None:
        self.responses = responses

    def run(self, argv, **kwargs):  # noqa: ANN001, ANN003
        key = tuple(argv)
        if key not in self.responses:
            raise AssertionError(f"unexpected command: {argv}")
        return self.responses[key]


class FakeIdentity:
    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome

    def probe(self, repo: Path, **kwargs) -> Outcome:  # noqa: ANN003
        return self.outcome


def _git_ok_responses(
    *,
    dirty: str = "",
    branch: str = "codex/feature",
    git_dir: str = ".git",
    common_dir: str = ".git",
) -> dict[tuple[str, ...], CommandResult]:
    root = "C:/repo"
    return {
        ("git", "rev-parse", "--show-toplevel"): CommandResult(0, root, ""),
        ("git", "branch", "--show-current"): CommandResult(0, branch, ""),
        ("git", "rev-parse", "--git-dir"): CommandResult(0, git_dir, ""),
        ("git", "rev-parse", "--git-common-dir"): CommandResult(0, common_dir, ""),
        ("git", "status", "--porcelain", "--untracked-files=all"): CommandResult(
            0, dirty, ""
        ),
        ("git", "worktree", "list", "--porcelain"): CommandResult(
            0, "worktree C:/repo\nworktree C:/repo-wt\n", ""
        ),
    }


def test_blocks_unapproved_dirty_paths(tmp_path: Path) -> None:
    runner = FakeRunner(
        _git_ok_responses(dirty=" M src/a.py\n M docs/b.md\n")
    )
    identity = FakeIdentity(
        Outcome(
            Status.READY,
            "identity_verified",
            "ok",
            "ok",
            "none",
            {"repository": "o/r", "login": "o"},
        )
    )
    outcome = evaluate_write_preflight(
        tmp_path,
        runner=runner,  # type: ignore[arg-type]
        identity_probe=identity,  # type: ignore[arg-type]
        approved_paths=("src/a.py",),
    )
    assert outcome.status is Status.BLOCKED
    assert outcome.code == "dirty_scope_unapproved"
    assert "docs/b.md" in outcome.evidence["unapproved_paths"]


def test_ready_when_location_clean_and_identity_ready(tmp_path: Path) -> None:
    runner = FakeRunner(_git_ok_responses(dirty=""))
    identity = FakeIdentity(
        Outcome(
            Status.READY,
            "identity_verified",
            "ok",
            "ok",
            "none",
            {"repository": "o/r", "login": "o"},
        )
    )
    outcome = evaluate_write_preflight(
        tmp_path,
        runner=runner,  # type: ignore[arg-type]
        identity_probe=identity,  # type: ignore[arg-type]
    )
    assert outcome.status is Status.READY
    assert outcome.code == "write_preflight_ready"
    assert outcome.evidence["location"]["branch"] == "codex/feature"
    assert outcome.evidence["location"]["worktree_count"] == 2


def test_preserves_leading_space_in_porcelain_paths(tmp_path: Path) -> None:
    # Regression: stripping full porcelain output turned " M README.md" into "M README.md"
    # and sliced path to "EADME.md".
    runner = FakeRunner(_git_ok_responses(dirty=" M README.md\n"))
    identity = FakeIdentity(
        Outcome(
            Status.READY,
            "identity_verified",
            "ok",
            "ok",
            "none",
            {"repository": "o/r", "login": "o"},
        )
    )
    outcome = evaluate_write_preflight(
        tmp_path,
        runner=runner,  # type: ignore[arg-type]
        identity_probe=identity,  # type: ignore[arg-type]
        allow_dirty=True,
    )
    assert outcome.status is Status.READY
    assert outcome.evidence["location"]["dirty_paths"] == ["README.md"]


def test_propagates_identity_block_with_location_evidence(tmp_path: Path) -> None:
    runner = FakeRunner(
        _git_ok_responses(
            dirty="",
            git_dir="C:/repo/.git/worktrees/feature",
            common_dir="C:/repo/.git",
        )
    )
    identity = FakeIdentity(
        Outcome(
            Status.BLOCKED,
            "active_login_mismatch",
            "login mismatch",
            "stop",
            "use validated token",
            {"expected_login": "a", "active_login": "b"},
        )
    )
    outcome = evaluate_write_preflight(
        tmp_path,
        runner=runner,  # type: ignore[arg-type]
        identity_probe=identity,  # type: ignore[arg-type]
    )
    assert outcome.status is Status.BLOCKED
    assert outcome.code == "active_login_mismatch"
    assert outcome.evidence["location"]["is_linked_worktree"] is True


def test_blocks_unconfirmed_environment_token(tmp_path: Path) -> None:
    runner = FakeRunner(_git_ok_responses(dirty=""))
    identity = FakeIdentity(
        Outcome(Status.READY, "unexpected", "", "", "", {"unused": True})
    )
    outcome = evaluate_write_preflight(
        tmp_path,
        token="secret",
        runner=runner,  # type: ignore[arg-type]
        identity_probe=identity,  # type: ignore[arg-type]
    )
    assert outcome.status is Status.BLOCKED
    assert outcome.code == "token_identity_unconfirmed"
