"""CommandRunner が子プロセスの起動失敗を returncode へ写すことを固定する。

握らないと --json 契約の CLI が stdout 0 バイトの traceback で死ぬ
(実測: gh 不在環境で scripts/gh_identity_probe.py --repo . --json)。
timeout と「起動できなかった」は呼び出し側で意味が違うので別の値にする。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from github_ops.command import NOT_EXECUTED, TIMED_OUT, CommandRunner


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_missing_executable_becomes_not_executed() -> None:
    result = CommandRunner().run(["definitely-not-a-real-binary-9f21"])
    assert result.returncode == NOT_EXECUTED
    assert result.stdout == ""
    assert "FileNotFoundError" in result.stderr


def test_missing_cwd_becomes_not_executed(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    gone.rmdir()
    result = CommandRunner().run([sys.executable, "-c", "pass"], cwd=gone)
    assert result.returncode == NOT_EXECUTED


def test_timeout_is_distinguishable_from_a_missing_executable() -> None:
    result = CommandRunner().run(
        [sys.executable, "-c", "import time; time.sleep(5)"], timeout=1
    )
    assert result.returncode == TIMED_OUT
    assert result.returncode != NOT_EXECUTED
    assert result.stderr == "command timed out"


def test_json_cli_still_emits_json_when_gh_is_absent(tmp_path: Path) -> None:
    """--json を謳う CLI は gh が無くても JSON を返すこと。

    PATH から gh を消して実際に起動し、stdout が json.loads できることを見る。
    """
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    env = dict(os.environ, PATH=str(empty_bin))
    completed = subprocess.run(
        [sys.executable, "scripts/gh_identity_probe.py", "--repo", ".", "--json"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.stdout.strip(), completed.stderr
    payload = json.loads(completed.stdout)
    assert "status" in payload
