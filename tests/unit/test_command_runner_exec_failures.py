"""CommandRunner が実行時の例外を構造化し、実終了値と区別することを固定する。

握らないと --json 契約の CLI が stdout 0 バイトの traceback で死ぬ
(実測: gh 不在環境で scripts/gh_identity_probe.py --repo . --json)。
例外区分は実プロセスの終了値に重ねず、独立属性で返す。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from github_ops.command import CommandFailure, CommandRunner


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_missing_executable_becomes_execution_failed() -> None:
    result = CommandRunner().run(["definitely-not-a-real-binary-9f21"])
    assert result.returncode != 0
    assert result.failure is CommandFailure.EXECUTION_FAILED
    assert result.stdout == ""
    assert "FileNotFoundError" in result.stderr


def test_missing_cwd_becomes_execution_failed(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    gone.rmdir()
    result = CommandRunner().run([sys.executable, "-c", "pass"], cwd=gone)
    assert result.returncode != 0
    assert result.failure is CommandFailure.EXECUTION_FAILED


def test_timeout_is_distinguishable_from_a_missing_executable() -> None:
    result = CommandRunner().run(
        [sys.executable, "-c", "import time; time.sleep(5)"], timeout=1
    )
    assert result.returncode != 0
    assert result.failure is CommandFailure.TIMED_OUT
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


@pytest.mark.parametrize("exit_code", [0, 1, 124, 127])
def test_real_exit_codes_do_not_signal_execution_exceptions(exit_code: int) -> None:
    result = CommandRunner().run(
        [sys.executable, "-c", f"raise SystemExit({exit_code})"]
    )
    assert result.returncode == exit_code
    assert result.failure is None


@pytest.mark.parametrize("kind", ["timeout", "os_error", "subprocess_error"])
def test_exception_details_do_not_expose_tokens(kind: str) -> None:
    token = "gh" + "p_" + "a" * 24
    exceptions = {
        "timeout": subprocess.TimeoutExpired(["gh", token], 1, output=token, stderr=token),
        "os_error": OSError(token),
        "subprocess_error": subprocess.SubprocessError(token),
    }

    def fail(*args, **kwargs):
        raise exceptions[kind]

    result = CommandRunner(run_impl=fail).run(["gh"], redact_stdout=False)
    assert result.returncode != 0
    assert result.failure is (
        CommandFailure.TIMED_OUT if kind == "timeout" else CommandFailure.EXECUTION_FAILED
    )
    assert token not in result.stdout + result.stderr
