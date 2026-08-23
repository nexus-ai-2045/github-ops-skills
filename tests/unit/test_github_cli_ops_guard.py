from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/github-cli-ops-guard/scripts/gh_identity_probe.py"
SPEC = importlib.util.spec_from_file_location("gh_identity_probe", SCRIPT)
assert SPEC and SPEC.loader
gh_identity_probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gh_identity_probe)


def test_bundled_parser_rejects_credentials_and_non_lowercase_scheme() -> None:
    assert gh_identity_probe.parse_remote_owner(
        "https://x-access-token:secret@github.com/example-org/tooling.git"
    ) == (None, None)
    assert gh_identity_probe.parse_remote_owner(
        "HTTPS://github.com/example-org/tooling.git"
    ) == (None, None)
    assert gh_identity_probe.parse_remote_owner(
        "https://github.com:443/example-org/tooling.git"
    ) == (None, None)


def test_bundled_parser_accepts_standard_ssh_url() -> None:
    assert gh_identity_probe.parse_remote_owner(
        "ssh://git@github.com/example-org/tooling.git"
    ) == ("example-org", "tooling")
    assert gh_identity_probe.parse_remote_owner(
        "ssh://git@github.com:22/example-org/tooling.git"
    ) == ("example-org", "tooling")
    assert gh_identity_probe.parse_remote_owner(
        "ssh://git@github.com:2222/example-org/tooling.git"
    ) == (None, None)


def test_bundled_guard_checks_push_url_without_expected_login(monkeypatch, tmp_path: Path) -> None:
    def fake_git_value(cwd: Path, *args: str) -> str | None:
        assert cwd == tmp_path
        if args == ("remote", "get-url", "--all", "--push", "origin"):
            return "https://x-access-token:secret@github.com/example-org/tooling.git"
        raise AssertionError(f"unexpected git query: {args}")

    monkeypatch.setattr(gh_identity_probe, "git_value", fake_git_value)
    result = gh_identity_probe.inspect_push_remote(
        tmp_path,
        fetch_owner="example-org",
        fetch_repo="tooling",
    )
    assert result["status"] == "error"
    assert result["value"] == "configured"
    assert "secret" not in str(result)


def test_bundled_guard_rejects_push_repository_mismatch(monkeypatch, tmp_path: Path) -> None:
    def fake_git_value(cwd: Path, *args: str) -> str | None:
        if args == ("remote", "get-url", "--all", "--push", "origin"):
            return "https://github.com/other-org/tooling.git"
        raise AssertionError(f"unexpected git query: {args}")

    monkeypatch.setattr(gh_identity_probe, "git_value", fake_git_value)
    result = gh_identity_probe.inspect_push_remote(
        tmp_path,
        fetch_owner="example-org",
        fetch_repo="tooling",
    )
    assert result["status"] == "error"
    assert result["value"] == "other-org/tooling"


def test_bundled_guard_accepts_one_matching_push_url(monkeypatch, tmp_path: Path) -> None:
    def fake_git_value(cwd: Path, *args: str) -> str | None:
        if args == ("remote", "get-url", "--all", "--push", "origin"):
            return "https://github.com/example-org/tooling.git"
        raise AssertionError(f"unexpected git query: {args}")

    monkeypatch.setattr(gh_identity_probe, "git_value", fake_git_value)
    result = gh_identity_probe.inspect_push_remote(
        tmp_path,
        fetch_owner="example-org",
        fetch_repo="tooling",
    )
    assert result == {"status": "ok", "value": "example-org/tooling"}


def test_bundled_guard_accepts_case_insensitive_ssh_push_url(monkeypatch, tmp_path: Path) -> None:
    def fake_git_value(cwd: Path, *args: str) -> str | None:
        if args == ("remote", "get-url", "--all", "--push", "origin"):
            return "ssh://git@github.com/example-org/tooling.git"
        raise AssertionError(f"unexpected git query: {args}")

    monkeypatch.setattr(gh_identity_probe, "git_value", fake_git_value)
    result = gh_identity_probe.inspect_push_remote(
        tmp_path,
        fetch_owner="Example-Org",
        fetch_repo="Tooling",
    )
    assert result == {"status": "ok", "value": "example-org/tooling"}
