from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_identity_json_is_utf8_when_parent_requests_cp932() -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp932"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/gh_identity_probe.py",
            "--repo",
            ".",
            "--json",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    output = completed.stdout.decode("utf-8")
    assert "origin remoteを確認できません" in output
