from pathlib import Path
import subprocess
import sys

from adapters.claude.verify_adapter import verify as verify_claude
from adapters.codex.verify_adapter import verify as verify_codex
from adapters.grok.verify_adapter import verify as verify_grok


def test_all_adapters_resolve_the_same_skill_root() -> None:
    repo = Path(__file__).resolve().parents[2]
    codex = verify_codex(repo)
    claude = verify_claude(repo)
    grok = verify_grok(repo)
    assert codex["skill_root"] == claude["skill_root"] == grok["skill_root"]
    assert codex["skill_count"] == 8
    assert codex["manifest_sha256"] == claude["manifest_sha256"] == grok["manifest_sha256"]
    assert "public-repo-readiness" in codex["skills"]
    assert (repo / "skills/public-repo-readiness/manifest.yaml").is_file()


def test_adapter_blocks_when_required_skill_is_missing(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    for name in {
        "commit-push-pr",
        "github-cli-ops-guard",
        "post-merge-closeout",
        "pr-convergence-loop",
        "pr-status",
        "public-repo-readiness",
        "review-pr",
    }:
        (skills / name).mkdir(parents=True)
    migration = tmp_path / "migration"
    migration.mkdir()
    (migration / "source-manifest.json").write_text(
        '{"schema_version":"github-ops/source-manifest/v1","sources":[{}]}',
        encoding="utf-8",
    )
    result = verify_codex(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["missing_skills"] == ["cross-repo-wip-ownership"]


def test_adapter_blocks_empty_required_skill_directories(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    for source in (repo / "skills").iterdir():
        if source.is_dir():
            (tmp_path / "skills" / source.name).mkdir(parents=True)
    (tmp_path / "migration").mkdir()
    (tmp_path / "migration" / "source-manifest.json").write_text(
        '{"schema_version":"github-ops/source-manifest/v1","sources":[{}]}',
        encoding="utf-8",
    )
    result = verify_codex(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["missing_entrypoints"]


def test_adapter_blocks_blank_and_non_utf8_entrypoints(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    for source in (repo / "skills").iterdir():
        if source.is_dir():
            target = tmp_path / "skills" / source.name
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("# usable\n", encoding="utf-8")
    (tmp_path / "skills" / "commit-push-pr" / "SKILL.md").write_text(
        "  \n", encoding="utf-8"
    )
    (tmp_path / "skills" / "review-pr" / "SKILL.md").write_bytes(b"\xff")
    (tmp_path / "migration").mkdir()
    (tmp_path / "migration" / "source-manifest.json").write_text(
        '{"schema_version":"github-ops/source-manifest/v1","sources":[{}]}',
        encoding="utf-8",
    )
    result = verify_codex(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["invalid_entrypoints"] == ["commit-push-pr", "review-pr"]


def test_adapter_blocks_invalid_source_manifest(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    for source in (repo / "skills").iterdir():
        if source.is_dir():
            (tmp_path / "skills" / source.name).mkdir(parents=True)
    (tmp_path / "migration").mkdir()
    (tmp_path / "migration" / "source-manifest.json").write_text(
        "not-json", encoding="utf-8"
    )
    result = verify_grok(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["manifest_valid"] is False


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


def test_grok_adapter_supports_direct_script_execution() -> None:
    repo = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(repo / "adapters/grok/verify_adapter.py"),
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
