"""「差分形式を確認」step を実際の bash で動かし、比較元の扱いを確かめる。"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ZERO = "0" * 40


def _step_script() -> str:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "core-suite-ci.yml").read_text(encoding="utf-8")
    )
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if step.get("name") == "差分形式を確認":
                return step["run"]
    raise AssertionError("差分形式を確認 step が無い")


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path, content: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text(content, encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _run(repo: Path, event: str, before: str = "", base: str = "") -> int:
    env = {**os.environ, "EVENT_NAME": event, "BEFORE_SHA": before, "BASE_SHA": base}
    return subprocess.run(
        [shutil.which("bash") or "bash", "-e", "-c", _step_script()],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    ).returncode


pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash が無い")


@pytest.mark.parametrize("before", ["", ZERO, "1" * 40])
def test_push_without_usable_before_compares_with_empty_tree(tmp_path: Path, before: str) -> None:
    clean = _repo(tmp_path, "ok\n")
    assert _run(clean, "push", before=before) == 0


@pytest.mark.parametrize("before", ["", ZERO, "1" * 40])
def test_push_without_usable_before_still_catches_whitespace(tmp_path: Path, before: str) -> None:
    dirty = _repo(tmp_path, "bad \n")
    assert _run(dirty, "push", before=before) != 0


def test_push_with_real_before_checks_only_the_range(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "bad \n")
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "b.txt").write_text("ok\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "second")
    assert _run(repo, "push", before=first) == 0


def test_pull_request_keeps_base_sha_comparison(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "ok\n")
    assert _run(repo, "pull_request", base=ZERO) != 0
