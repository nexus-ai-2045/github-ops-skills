from __future__ import annotations

from dataclasses import dataclass, field

from github_ops.command import CommandResult
from github_ops.identity import IdentityProbe, parse_github_remote


@dataclass
class FakeRunner:
    results: list[CommandResult]
    calls: list[dict] = field(default_factory=list)

    def run(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), **kwargs})
        return self.results.pop(0)


def test_token_login_mismatch_is_blocked() -> None:
    runner = FakeRunner([CommandResult(0, "other-user\n", "")])
    outcome = IdentityProbe(runner).validate_token_login(
        expected_login="example-user",
        token="secret",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "token_login_mismatch"
    assert runner.calls[0]["scoped_env"] == {"GH_TOKEN": "secret"}


def test_token_login_match_is_ready() -> None:
    runner = FakeRunner([CommandResult(0, "example-user\n", "")])
    outcome = IdentityProbe(runner).validate_token_login(
        expected_login="example-user",
        token="secret",
    )
    assert outcome.status.value == "READY"
    assert outcome.evidence["token_login"] == "example-user"


def test_active_login_probe_removes_token_env() -> None:
    runner = FakeRunner([CommandResult(0, "global-user\n", "")])
    login, error = IdentityProbe(runner).active_login()
    assert login == "global-user"
    assert error is None
    assert set(runner.calls[0]["unset_env"]) == {"GH_TOKEN", "GITHUB_TOKEN"}


def test_parse_https_and_ssh_remotes() -> None:
    assert parse_github_remote("https://github.com/example-org/tooling.git") == (
        "example-org",
        "tooling",
    )
    assert parse_github_remote("git@github.com:example-org/tooling.git") == (
        "example-org",
        "tooling",
    )
