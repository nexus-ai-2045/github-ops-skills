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


def test_git_credential_login_validates_the_returned_token(monkeypatch) -> None:
    module = _load_module()
    calls = []

    def fake_run(cmd, cwd, **kwargs):  # noqa: ANN001, ANN202
        calls.append((cmd, kwargs))
        if cmd[:3] == ["git", "credential", "fill"]:
            return 0, "username=x-access-token\npassword=secret-value", ""
        return 0, "example-user", ""

    monkeypatch.setattr(module, "run", fake_run)
    username, login, error = module.git_credential_login(
        Path("."), "https://github.com/example-org/tooling.git"
    )
    assert (username, login, error) == ("x-access-token", "example-user", None)
    assert "path=example-org/tooling.git" in calls[0][1]["input_text"]
    assert calls[1][1]["env"]["GH_TOKEN"] == "secret-value"
    assert calls[1][1]["env"]["GH_HOST"] == "github.com"


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


def test_main_never_prints_remote_url_credentials(monkeypatch, capsys) -> None:
    module = _load_module()
    secret = "super-secret-token"

    def fake_git_value(cwd, *args):  # noqa: ANN001, ANN202
        if args == ("remote", "get-url", "origin"):
            return f"https://user:{secret}@github.com/example-org/tooling.git"
        if args == ("branch", "--show-current"):
            return "codex/test"
        return None

    monkeypatch.setattr(module, "git_value", fake_git_value)
    monkeypatch.setattr(module, "git_value_with_origin", lambda *args: (None, None))
    monkeypatch.setattr(module, "gh_active_login", lambda *args: ("example-user", None))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--repo", ".", "--json"])

    assert module.main() == 1
    output = capsys.readouterr().out
    assert secret not in output
    assert "user:" not in output


def test_org_owner_and_authenticated_login_are_independent(monkeypatch, capsys) -> None:
    module = _load_module()

    def fake_git_value(cwd, *args):  # noqa: ANN001, ANN202
        values = {
            ("remote", "get-url", "origin"): "https://github.com/example-org/tooling.git",
            ("branch", "--show-current"): "codex/test",
        }
        return values.get(args)

    monkeypatch.setattr(module, "git_value", fake_git_value)
    monkeypatch.setattr(
        module, "git_credential_login", lambda *args: (
            "x-access-token", "example-user", None
        )
    )
    monkeypatch.setattr(module, "gh_active_login", lambda *args: ("example-user", None))
    monkeypatch.setattr(
        module,
        "run",
        lambda *args, **kwargs: (
            0,
            '{"nameWithOwner":"example-org/tooling","visibility":"PRIVATE"}',
            "",
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT), "--repo", ".", "--expected-owner", "example-org",
            "--expected-login", "example-user", "--json",
        ],
    )

    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["checks"]["gh_active_login"]["status"] == "ok"
    assert result["checks"]["credential_username"]["status"] == "ok"


def test_expected_owner_mismatch_is_an_error(monkeypatch, capsys) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "git_value",
        lambda cwd, *args: (
            "https://github.com/actual-org/tooling.git"
            if args == ("remote", "get-url", "origin")
            else "codex/test"
            if args == ("branch", "--show-current")
            else None
        ),
    )
    monkeypatch.setattr(
        module, "git_credential_login", lambda *args: (None, "example-user", None)
    )
    monkeypatch.setattr(module, "gh_active_login", lambda *args: ("example-user", None))
    monkeypatch.setattr(
        module, "run", lambda *args, **kwargs: (
            0, '{"nameWithOwner":"actual-org/tooling","visibility":"PRIVATE"}', ""
        )
    )
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--repo", ".", "--expected-owner", "other-org", "--json"]
    )
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["checks"]["remote_owner"]["status"] == "error"


def test_effective_git_credential_login_must_match_expected_login(
    monkeypatch, capsys
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "git_value",
        lambda cwd, *args: (
            "https://github.com/example-org/tooling.git"
            if args == ("remote", "get-url", "origin")
            else "codex/test"
            if args == ("branch", "--show-current")
            else None
        ),
    )
    monkeypatch.setattr(
        module, "git_credential_login", lambda *args: (
            "x-access-token", "wrong-user", None
        )
    )
    monkeypatch.setattr(module, "gh_active_login", lambda *args: ("example-user", None))
    monkeypatch.setattr(
        module, "run", lambda *args, **kwargs: (
            0, '{"nameWithOwner":"example-org/tooling","visibility":"PRIVATE"}', ""
        )
    )
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), "--repo", ".", "--expected-login", "example-user", "--json"]
    )
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["checks"]["credential_username"]["status"] == "error"
