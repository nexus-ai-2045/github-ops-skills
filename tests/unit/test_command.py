from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

from github_ops.command import CommandRunner


def test_scoped_env_does_not_mutate_parent(monkeypatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    captured = {}

    def fake_run(argv, **kwargs):
        captured.update(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    runner = CommandRunner(run_impl=fake_run)
    runner.run(["gh", "api", "user"], scoped_env={"GH_TOKEN": "secret"})
    assert captured["GH_TOKEN"] == "secret"
    assert os.environ.get("GH_TOKEN") is None


def test_unset_env_removes_token_only_from_child(monkeypatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "parent-secret")
    captured = {}

    def fake_run(argv, **kwargs):
        captured.update(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    CommandRunner(run_impl=fake_run).run(["gh", "auth", "status"], unset_env={"GH_TOKEN"})
    assert "GH_TOKEN" not in captured
    assert os.environ["GH_TOKEN"] == "parent-secret"


def test_result_output_is_redacted() -> None:
    token = "gh" + "p_" + "a" * 36

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr=f"failed with {token}")

    result = CommandRunner(run_impl=fake_run).run(["gh", "api", "user"])
    assert token not in result.stderr
    assert "[REDACTED]" in result.stderr


def test_stdout_redaction_can_be_disabled_without_exposing_stderr() -> None:
    token = "gh" + "p_" + "a" * 36

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout=token, stderr=token)

    result = CommandRunner(run_impl=fake_run).run(
        ["gh", "pr", "view"], redact_stdout=False
    )
    assert result.stdout == token
    assert token not in result.stderr


def test_runner_uses_no_window_flag_on_windows() -> None:
    captured = {}

    def fake_run(argv, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch("github_ops.command.subprocess.CREATE_NO_WINDOW", 0x08000000, create=True):
        runner = CommandRunner(run_impl=fake_run, os_name="nt")
        runner.run(["gh", "--version"])
    assert captured["creationflags"] != 0


def test_runner_decodes_machine_output_as_utf8() -> None:
    captured = {}

    def fake_run(argv, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="日本語", stderr="")

    result = CommandRunner(run_impl=fake_run).run(["git", "show", "HEAD"])
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert result.stdout == "日本語"
