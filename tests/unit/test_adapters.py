from pathlib import Path
import subprocess
import sys

from adapters.claude.verify_adapter import verify as verify_claude
from adapters.codex.verify_adapter import verify as verify_codex


def test_both_adapters_resolve_the_same_skill_root() -> None:
    repo = Path(__file__).resolve().parents[2]
    codex = verify_codex(repo)
    claude = verify_claude(repo)
    assert codex["skill_root"] == claude["skill_root"]
    assert codex["skill_count"] == 7
    assert codex["manifest_sha256"] == claude["manifest_sha256"]


def test_claude_adapter_supports_direct_script_execution() -> None:
    repo = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(repo / "adapters/claude/verify_adapter.py"),
            "--repo",
            str(repo),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"status": "READY"' in completed.stdout
