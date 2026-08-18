from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/github-cli-ops-guard/scripts/gh_identity_probe.py"
)


def _load_module():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("skill_local_identity_probe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_remote_owner_accepts_supported_github_remote_forms() -> None:
    module = _load_module()

    assert module.parse_remote_owner("https://github.com/example-org/tooling.git") == (
        "example-org",
        "tooling",
    )
    assert module.parse_remote_owner("git@github.com:example-org/tooling.git") == (
        "example-org",
        "tooling",
    )
    assert module.parse_remote_owner("ssh://git@github.com/example-org/tooling") == (
        "example-org",
        "tooling",
    )


def test_parse_remote_owner_rejects_lookalike_hosts() -> None:
    module = _load_module()

    assert module.parse_remote_owner("https://evilgithub.com/example-org/tooling.git") == (
        None,
        None,
    )
    assert module.parse_remote_owner("git@evilgithub.com:example-org/tooling.git") == (
        None,
        None,
    )
    assert module.parse_remote_owner("https://github.com.evil/example-org/tooling.git") == (
        None,
        None,
    )
    assert module.parse_remote_owner("https://[malformed/example-org/tooling.git") == (
        None,
        None,
    )
    assert module.parse_remote_owner("https://github.com/example-org/tooling/") == (
        None,
        None,
    )


def test_run_uses_a_finite_timeout(monkeypatch) -> None:
    module = _load_module()
    captured = {}

    class Completed:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def fake_run(*args, **kwargs):  # noqa: ANN002, ANN003
        captured.update(kwargs)
        return Completed()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.run(["gh", "api", "user"], Path(".")) == (0, "ok", "")
    assert captured["timeout"] == 30


def test_run_handles_timeout_without_raising(monkeypatch) -> None:
    module = _load_module()

    def fake_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise subprocess.TimeoutExpired(kwargs.get("args", args[0]), 30)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    code, stdout, stderr = module.run(["gh", "api", "user"], Path("."))

    assert code != 0
    assert stdout == ""
    assert "timed out" in stderr


def test_run_handles_os_error_without_raising(monkeypatch) -> None:
    module = _load_module()

    def fake_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("gh executable missing")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    code, stdout, stderr = module.run(["gh", "api", "user"], Path("."))

    assert code != 0
    assert stdout == ""
    assert "gh executable missing" in stderr


def test_main_emits_fail_closed_structured_outcome_on_command_failure(
    monkeypatch, capsys
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "run",
        lambda *args, **kwargs: (127, "", "command failed: probe unavailable"),
    )
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--repo", ".", "--json"])

    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "error"
    assert result["checks"]["remote_url"]["status"] == "error"
    assert result["checks"]["gh_active_login"]["detail"] == (
        "command failed: probe unavailable"
    )
