"""公開identity guardの実CLIを通じて終了値とJSON契約を検証する。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "public_identity_guard.py"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={repo / 'no-hooks'}",
            *args,
        ],
        cwd=repo,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "sample.txt").write_text("安全な本文\n", encoding="utf-8")
    _git(repo, "add", "sample.txt")
    _git(repo, "commit", "-m", "Add safe sample")
    return repo


def _cli(repo: Path, *args: str, env: dict[str, str] | None = None):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert completed.stdout.strip(), completed.stderr
    assert "Traceback" not in completed.stderr
    return completed, json.loads(completed.stdout)


def test_cli_safe_tree_returns_zero_and_ready_json(sample_repo: Path) -> None:
    completed, payload = _cli(sample_repo)
    assert completed.returncode == 0
    assert payload["status"] == "READY"
    assert payload["code"] == "identity_scan_ready"


def test_cli_exposure_returns_nonzero_and_blocked_json(sample_repo: Path) -> None:
    sensitive = "C:" + "\\Users\\private-person\\secret.txt"
    (sample_repo / "sample.txt").write_text(sensitive, encoding="utf-8")
    _git(sample_repo, "add", "sample.txt")
    _git(sample_repo, "commit", "-m", "Add exposure fixture")
    completed, payload = _cli(sample_repo)
    assert completed.returncode == 1
    assert payload["status"] == "BLOCKED"
    assert payload["code"] == "identity_exposure_detected"
    assert "windows_home_path" in payload["evidence"]["rules"]
    assert "private-person" not in completed.stdout + completed.stderr


@pytest.mark.parametrize("failure", ["bad_revision", "missing_git", "missing_blob"])
def test_cli_unreadable_git_returns_nonzero_and_unknown_json(
    sample_repo: Path, failure: str, tmp_path: Path
) -> None:
    args: list[str] = []
    env = None
    if failure == "bad_revision":
        args = ["--range", "nonexistent-revision-for-test"]
    elif failure == "missing_git":
        empty_bin = tmp_path / "empty-bin"
        empty_bin.mkdir()
        env = {**os.environ, "PATH": str(empty_bin)}
    else:
        # このテスト専用のloose blobだけを消し、tree列挙成功後の読取失敗を作る。
        blob = _git(sample_repo, "rev-parse", "HEAD:sample.txt")
        (sample_repo / ".git" / "objects" / blob[:2] / blob[2:]).unlink()
    completed, payload = _cli(sample_repo, *args, env=env)
    assert completed.returncode == 1
    assert payload["status"] == "UNKNOWN"
    assert payload["code"] == (
        "identity_scan_incomplete" if failure == "missing_blob" else "git_range_unverified"
    )


@pytest.mark.parametrize("failure", ["missing", "directory", "invalid_utf8"])
def test_cli_unreadable_artifact_returns_unknown_json(
    sample_repo: Path, tmp_path: Path, failure: str
) -> None:
    artifact = tmp_path / "artifact.txt"
    if failure == "directory":
        artifact.mkdir()
    elif failure == "invalid_utf8":
        artifact.write_bytes(b"\xff")
    completed, payload = _cli(sample_repo, "--artifact", str(artifact))
    assert completed.returncode == 1
    assert payload["status"] == "UNKNOWN"
    assert payload["code"] == "artifact_unverified"
    assert "error_type" in payload["evidence"]


def test_unreadable_artifact_is_not_overwritten_by_earlier_finding(
    sample_repo: Path, tmp_path: Path
) -> None:
    exposed = tmp_path / "exposed.txt"
    token = "gh" + "p_" + "a" * 36
    exposed.write_text(token, encoding="utf-8")
    completed, payload = _cli(
        sample_repo, "--artifact", str(exposed), "--artifact", str(tmp_path / "missing.txt")
    )
    assert completed.returncode == 1
    assert payload["status"] == "UNKNOWN"
    assert payload["code"] == "artifact_unverified"
    assert token not in completed.stdout + completed.stderr
