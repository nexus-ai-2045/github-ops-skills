from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_identity_json_is_utf8_when_parent_requests_cp932(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp932"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/gh_identity_probe.py",
            "--repo",
            str(tmp_path),
            "--json",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    output = completed.stdout.decode("utf-8")
    assert "origin remoteを確認できません" in output


def test_canary_packet_json_is_utf8_when_parent_requests_cp932(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp932"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_private_canary.py",
            "--repo",
            "example-org/example",
            "--branch",
            "canary/review",
            "--draft-pr-title",
            "レビュー用canary",
            "--review-packet",
            str(tmp_path / "packet.json"),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )

    output = completed.stdout.decode("utf-8")
    assert completed.returncode == 0
    assert "レビュー用canary" in output
    assert "現在会話でのcanary承認がありません" in output
