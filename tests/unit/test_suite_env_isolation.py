"""test suite が呼び出し元 shell の GitHub 環境変数に左右されないこと。

pr_create などは GH_TOKEN / GITHUB_TOKEN / GH_HOST を os.environ から読む。
FakeRunner で外部を差し替えていても、開発者の shell や CI job にこれらが
あると identity probe の分岐が変わり、28 件が落ちていた。
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pr_create_tests_pass_with_ambient_github_env() -> None:
    env = dict(os.environ)
    env.update(
        GH_TOKEN="ambient-dummy",
        GITHUB_TOKEN="ambient-dummy",
        GH_HOST="enterprise.example.com",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/unit/test_pr_create.py",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout[-2000:]
