from pathlib import Path

from github_ops.result import Status
from github_ops.skill_drift import compare_skill_roots, drift_outcome


def test_compare_detects_match_and_drift(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha").mkdir(parents=True)
    (local / "alpha").mkdir(parents=True)
    (ssot / "alpha" / "SKILL.md").write_text("# same\n", encoding="utf-8")
    (local / "alpha" / "SKILL.md").write_text("# same\n", encoding="utf-8")
    (ssot / "alpha" / "manifest.yaml").write_text("name: alpha\n", encoding="utf-8")
    (local / "alpha" / "manifest.yaml").write_text("name: changed\n", encoding="utf-8")

    rows = compare_skill_roots(ssot_skills_root=ssot, local_skills_root=local)
    statuses = {(row.relative_path, row.status) for row in rows}
    assert ("SKILL.md", "match") in statuses
    assert ("manifest.yaml", "drift") in statuses

    outcome = drift_outcome(rows, local_root=str(local))
    assert outcome.status is Status.BLOCKED
    assert outcome.code == "skill_drift_detected"


def test_compare_ready_when_all_match(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha").mkdir(parents=True)
    (local / "alpha").mkdir(parents=True)
    content = "# skill\n"
    (ssot / "alpha" / "SKILL.md").write_text(content, encoding="utf-8")
    (local / "alpha" / "SKILL.md").write_text(content, encoding="utf-8")

    rows = compare_skill_roots(ssot_skills_root=ssot, local_skills_root=local)
    outcome = drift_outcome(rows, local_root=str(local))
    assert outcome.status is Status.READY


def test_missing_runtime_skill_blocks(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha").mkdir(parents=True)
    local.mkdir()
    (ssot / "alpha" / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    rows = compare_skill_roots(ssot_skills_root=ssot, local_skills_root=local)
    assert drift_outcome(rows, local_root=str(local)).status is Status.BLOCKED


def test_manifest_runtime_helpers_are_compared(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    for root in (ssot, local):
        (root / "alpha" / "scripts").mkdir(parents=True)
        (root / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")
    (ssot / "alpha" / "scripts" / "helper.py").write_text("ssot\n", encoding="utf-8")
    (local / "alpha" / "scripts" / "helper.py").write_text("local\n", encoding="utf-8")
    (ssot / "alpha" / "manifest.yaml").write_text(
        "runtimes:\n  codex:\n    files:\n      - SKILL.md\n      - scripts/helper.py\n",
        encoding="utf-8",
    )
    rows = compare_skill_roots(ssot_skills_root=ssot, local_skills_root=local)
    assert ("scripts/helper.py", "drift") in {
        (row.relative_path, row.status) for row in rows
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
        "runtimes:\n  codex:\n    files: [SKILL.md]\n    extra:\n      agents/openai.yaml: runtime/agents/openai.yaml\n",
        encoding="utf-8",
    )
    rows = compare_skill_roots(ssot_skills_root=ssot, local_skills_root=local)
    assert ("agents/openai.yaml", "match") in {
        (row.relative_path, row.status) for row in rows
    }
