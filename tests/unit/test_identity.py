from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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


def test_parse_https_remote_rejects_embedded_credential() -> None:
    assert parse_github_remote(
        "https://x-access-token:not-a-real-credential@github.com/example-org/tooling.git"
    ) == (None, None)


def test_parse_redacted_remote_is_fail_closed() -> None:
    assert parse_github_remote(
        "https://x-access-token:[REDACTED]@github.com/example-org/tooling.git"
    ) == (None, None)


def test_probe_blocks_embedded_fetch_credential_without_leaking_it() -> None:
    remote = (
        "https://x-access-token:not-a-real-credential@github.com/"
        "example-org/tooling.git\n"
    )
    runner = FakeRunner(
        [
            CommandResult(0, remote, ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        Path("."),
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "embedded_remote_credential_unsupported"
    assert runner.calls[0]["redact_stdout"] is False
    assert "not-a-real-credential" not in outcome.to_json()
    assert "x-access-token" not in outcome.to_json()


def test_probe_blocks_embedded_push_credential_without_leaking_it() -> None:
    push_remote = (
        "https://x-access-token:not-a-real-credential@github.com/"
        "example-org/tooling.git\n"
    )
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, push_remote, ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        Path("."),
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "embedded_push_credential_unsupported"
    assert runner.calls[1]["redact_stdout"] is False
    assert runner.calls[1]["argv"] == [
        "git",
        "remote",
        "get-url",
        "--all",
        "--push",
        "origin",
    ]
    assert "not-a-real-credential" not in outcome.to_json()


def test_probe_blocks_multiple_push_urls() -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(
                0,
                "https://github.com/example-org/tooling.git\n"
                "git@github.com:example-org/tooling.git\n",
                "",
            ),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        Path("."),
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "push_remote_count_unsupported"


def test_probe_blocks_push_repository_mismatch() -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "https://github.com/other-org/tooling.git\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        Path("."),
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "push_repository_mismatch"
