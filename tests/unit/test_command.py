from __future__ import annotations

import os
from types import SimpleNamespace

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


def test_result_output_is_redacted() -> None:
    token = "gh" + "p_" + "a" * 36

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr=f"failed with {token}")

    result = CommandRunner(run_impl=fake_run).run(["gh", "api", "user"])
    assert token not in result.stderr
    assert "[REDACTED]" in result.stderr


def test_runner_uses_no_window_flag_on_windows(monkeypatch) -> None:
    captured = {}

    def fake_run(argv, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("github_ops.command.os.name", "nt")
    runner = CommandRunner(run_impl=fake_run)
    runner.run(["gh", "--version"])
    assert captured["creationflags"] != 0
