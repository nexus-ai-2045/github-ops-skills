from __future__ import annotations

from dataclasses import dataclass, field

from github_ops.command import CommandResult
from github_ops.identity import IdentityProbe, parse_github_remote


@dataclass
class FakeRunner:
    results: list[CommandResult]
    calls: list[dict] = field(default_factory=list)
    http_extra_headers: CommandResult | None = None

    def run(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), **kwargs})
        if list(argv[:3]) == ["git", "config", "--get-regexp"]:
            return self.http_extra_headers or CommandResult(1, "", "")
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
    assert parse_github_remote("ssh://git@github.com/example-org/tooling.git") == (
        "example-org",
        "tooling",
    )


def test_parse_https_remote_rejects_embedded_credential() -> None:
    assert parse_github_remote(
        "https://x-access-token:not-a-real-secret@github.com/example-org/tooling.git"
    ) == (None, None)


def test_parse_malformed_or_redacted_remote_fails_closed() -> None:
    assert parse_github_remote(
        "https://x-access-token:[REDACTED]@github.com/example-org/tooling.git"
    ) == (None, None)


def test_parse_https_remote_rejects_explicit_port() -> None:
    assert parse_github_remote(
        "https://github.com:443/example-org/tooling.git"
    ) == (None, None)


def test_probe_blocks_embedded_fetch_credential_without_leaking_it(tmp_path) -> None:
    remote = (
        "https://x-access-token:not-a-real-secret@github.com/"
        "example-org/tooling.git\n"
    )
    runner = FakeRunner(
        [
            CommandResult(0, remote, ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "embedded_remote_credential_unsupported"
    assert runner.calls[0]["redact_stdout"] is False
    assert "not-a-real-secret" not in outcome.to_json()


def test_probe_blocks_embedded_push_credential_without_leaking_it(tmp_path) -> None:
    push_remote = (
        "https://x-access-token:not-a-real-secret@github.com/"
        "example-org/tooling.git\n"
    )
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, push_remote, ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "embedded_push_credential_unsupported"
    assert runner.calls[1]["redact_stdout"] is False
    assert "not-a-real-secret" not in outcome.to_json()


def test_probe_blocks_mismatched_git_credential_token_owner(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "protocol=https\nhost=github.com\nusername=example-user\npassword=hidden\n", ""),
            CommandResult(0, "other-user\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "token_login_mismatch"
    assert outcome.evidence["token_login"] == "other-user"
    assert runner.calls[4]["scoped_env"] == {
        "GH_HOST": "github.com",
        "GH_TOKEN": "hidden",
    }


def test_probe_accepts_x_access_token_username_when_token_owner_matches(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "username=x-access-token\npassword=hidden\n", ""),
            CommandResult(0, "example-user\n", ""),
            CommandResult(0, "example-user\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "READY"
    assert outcome.evidence["credential_username"] == "x-access-token"


def test_probe_blocks_http_authorization_header_override(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
        ],
        http_extra_headers=CommandResult(
            0,
            "http.https://github.com/.extraheader Authorization: Basic hidden\n",
            "",
        ),
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "http_auth_override_unsupported"


def test_credential_username_is_redacted_in_evidence(tmp_path) -> None:
    secret_username = "ghp_" + "A" * 24
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, f"username={secret_username}\npassword=hidden\n", ""),
            CommandResult(0, "example-user\n", ""),
            CommandResult(0, "example-user\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path, expected_owner="example-org", expected_login="example-user"
    )
    assert outcome.evidence["credential_username"] == "[REDACTED]"


def test_probe_stops_when_git_credential_has_no_token(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "username=example-user\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "UNKNOWN"
    assert outcome.code == "credential_token_unavailable"


def test_probe_verifies_ssh_authenticated_login(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "git@github.com:example-org/tooling.git\n", ""),
            CommandResult(0, "git@github.com:example-org/tooling.git\n", ""),
            CommandResult(1, "", ""),
            CommandResult(
                1,
                "",
                "Hi example-user! You've successfully authenticated, but GitHub does not provide shell access.\n",
            ),
            CommandResult(0, "example-user\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "READY"
    assert outcome.evidence["ssh_login"] == "example-user"
    assert runner.calls[3]["argv"][-1] == "git@github.com"


def test_probe_accepts_standard_ssh_push_url(tmp_path) -> None:
    ssh_url = "ssh://git@github.com/example-org/tooling.git"
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, f"{ssh_url}\n", ""),
            CommandResult(1, "", ""),
            CommandResult(
                1,
                "",
                "Hi example-user! You've successfully authenticated, but GitHub does not provide shell access.\n",
            ),
            CommandResult(0, "example-user\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "READY"
    assert outcome.evidence["ssh_login"] == "example-user"


def test_probe_blocks_mismatched_ssh_login(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "git@github.com:example-org/tooling.git\n", ""),
            CommandResult(0, "git@github.com:example-org/tooling.git\n", ""),
            CommandResult(1, "", ""),
            CommandResult(
                1,
                "",
                "Hi other-user! You've successfully authenticated, but GitHub does not provide shell access.\n",
            ),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "ssh_login_mismatch"


def test_probe_blocks_configured_ssh_command(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "git@github.com:example-org/tooling.git\n", ""),
            CommandResult(0, "git@github.com:example-org/tooling.git\n", ""),
            CommandResult(0, "ssh -i alternate-key\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "ssh_transport_override_unsupported"
    assert outcome.evidence["override_sources"] == ["core.sshCommand"]


def test_probe_blocks_ssh_environment_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i command-key")
    monkeypatch.setenv("GIT_SSH", "alternate-ssh")
    runner = FakeRunner(
        [
            CommandResult(0, "git@github.com:example-org/tooling.git\n", ""),
            CommandResult(0, "git@github.com:example-org/tooling.git\n", ""),
            CommandResult(1, "", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "ssh_transport_override_unsupported"
    assert outcome.evidence["override_sources"] == ["GIT_SSH_COMMAND", "GIT_SSH"]


def test_probe_blocks_divergent_push_repository(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "https://github.com/example-org/other.git\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "push_repository_mismatch"


def test_probe_validates_push_repository_without_expected_login(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "https://github.com/example-org/other.git\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(tmp_path, expected_owner="example-org")
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "push_repository_mismatch"


def test_probe_blocks_multiple_push_urls(tmp_path) -> None:
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
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "push_remote_count_unsupported"


def test_probe_verifies_credential_for_uppercase_https_scheme(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "HTTPS://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "HTTPS://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "username=example-user\npassword=hidden\n", ""),
            CommandResult(0, "other-user\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "token_login_mismatch"


def test_probe_uses_exact_push_url_path_for_https_credential(tmp_path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "https://github.com/example-org/tooling\n", ""),
            CommandResult(0, "username=example-user\npassword=hidden\n", ""),
            CommandResult(0, "example-user\n", ""),
            CommandResult(0, "example-user\n", ""),
        ]
    )
    outcome = IdentityProbe(runner).probe(
        tmp_path,
        expected_owner="example-org",
        expected_login="example-user",
    )
    assert outcome.status.value == "READY"
    assert runner.calls[3]["input_text"] == (
        "protocol=https\nhost=github.com\npath=example-org/tooling\n\n"
    )
