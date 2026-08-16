from pathlib import Path

from github_ops.result import Status
from github_ops.skill_drift import compare_skill_roots, drift_outcome


def _compare(ssot: Path, local: Path, runtime: str = "codex"):
    return compare_skill_roots(ssot_skills_root=ssot, local_skills_root=local, runtime=runtime)


def test_compare_detects_match_and_declared_file_drift(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha").mkdir(parents=True)
    (local / "alpha").mkdir(parents=True)
    (ssot / "alpha" / "SKILL.md").write_text("# same\n", encoding="utf-8")
    (local / "alpha" / "SKILL.md").write_text("# same\n", encoding="utf-8")
    (ssot / "alpha" / "helper.py").write_text("ssot\n", encoding="utf-8")
    (local / "alpha" / "helper.py").write_text("local\n", encoding="utf-8")
    (ssot / "alpha" / "manifest.yaml").write_text(
        "runtimes:\n  codex:\n    mode: copy\n    files: [SKILL.md, helper.py]\n",
        encoding="utf-8",
    )
    rows = _compare(ssot, local)
    statuses = {(row.relative_path, row.status) for row in rows}
    assert ("SKILL.md", "match") in statuses
    assert ("helper.py", "drift") in statuses
    assert drift_outcome(rows, local_root=str(local)).status is Status.BLOCKED


def test_compare_ready_when_all_match(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    for root in (ssot, local):
        (root / "alpha").mkdir(parents=True)
        (root / "alpha" / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    assert drift_outcome(_compare(ssot, local), local_root=str(local)).status is Status.READY


def test_missing_runtime_skill_blocks(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha").mkdir(parents=True)
    local.mkdir()
    (ssot / "alpha" / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    assert drift_outcome(_compare(ssot, local), local_root=str(local)).status is Status.BLOCKED


def test_manifest_runtime_helpers_are_compared(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    for root in (ssot, local):
        (root / "alpha" / "scripts").mkdir(parents=True)
        (root / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")
    (ssot / "alpha" / "scripts" / "helper.py").write_text("ssot\n", encoding="utf-8")
    (local / "alpha" / "scripts" / "helper.py").write_text("local\n", encoding="utf-8")
    (ssot / "alpha" / "manifest.yaml").write_text(
        "runtimes:\n  codex:\n    mode: copy\n    files: [SKILL.md, scripts/helper.py]\n",
        encoding="utf-8",
    )
    assert ("scripts/helper.py", "drift") in {
        (row.relative_path, row.status) for row in _compare(ssot, local)
    }


def test_manifest_extra_maps_ssot_source_to_runtime_target(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha" / "runtime" / "agents").mkdir(parents=True)
    (local / "alpha" / "agents").mkdir(parents=True)
    for root in (ssot, local):
        (root / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")
    content = "model: same\n"
    (ssot / "alpha" / "runtime" / "agents" / "openai.yaml").write_text(content, encoding="utf-8")
    (local / "alpha" / "agents" / "openai.yaml").write_text(content, encoding="utf-8")
    (ssot / "alpha" / "manifest.yaml").write_text(
        "runtimes:\n  codex:\n    mode: copy\n    files: [SKILL.md]\n"
        "    extra:\n      agents/openai.yaml: runtime/agents/openai.yaml\n",
        encoding="utf-8",
    )
    assert ("agents/openai.yaml", "match") in {
        (row.relative_path, row.status) for row in _compare(ssot, local)
    }


def test_runtime_selection_honors_runtime_and_skip(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha" / "runtime").mkdir(parents=True)
    (local / "alpha").mkdir(parents=True)
    for root in (ssot, local):
        (root / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")
    (ssot / "alpha" / "runtime" / "codex.yaml").write_text("codex only\n", encoding="utf-8")
    (ssot / "alpha" / "manifest.yaml").write_text(
        "runtimes:\n"
        "  claude:\n    mode: copy\n    files: [SKILL.md]\n"
        "  codex:\n    mode: copy\n    files: [SKILL.md]\n"
        "    extra:\n      agents/openai.yaml: runtime/codex.yaml\n"
        "  grok:\n    mode: skip\n",
        encoding="utf-8",
    )
    assert not any(
        row.relative_path == "agents/openai.yaml"
        for row in _compare(ssot, local, "claude")
    )
    assert _compare(ssot, local, "grok") == []
