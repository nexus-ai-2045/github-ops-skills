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


def test_compare_detects_extra_file_inside_managed_skill(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    for root in (ssot, local):
        (root / "alpha").mkdir(parents=True)
        (root / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")
    (local / "alpha" / "obsolete.py").write_text("old\n", encoding="utf-8")
    rows = _compare(ssot, local)
    assert ("obsolete.py", "local_only") in {
        (row.relative_path, row.status) for row in rows
    }
    assert drift_outcome(rows, local_root=str(local)).status is Status.BLOCKED


def test_invalid_manifest_is_a_blocked_outcome(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    for root in (ssot, local):
        (root / "alpha").mkdir(parents=True)
        (root / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")
    (ssot / "alpha" / "manifest.yaml").write_text("[]\n", encoding="utf-8")
    outcome = drift_outcome(_compare(ssot, local), local_root=str(local))
    assert outcome.status is Status.BLOCKED
    assert outcome.evidence["invalid_manifest_count"] == 1
    (ssot / "alpha" / "manifest.yaml").write_text(
        "runtimes: [\n", encoding="utf-8"
    )
    malformed = drift_outcome(_compare(ssot, local), local_root=str(local))
    assert malformed.status is Status.BLOCKED
    assert malformed.evidence["invalid_manifests"][0]["error_type"].endswith(
        "Error"
    )


def test_manifest_rejects_paths_outside_skill_root(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    for root in (ssot, local):
        (root / "alpha").mkdir(parents=True)
        (root / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")
    (ssot / "alpha" / "manifest.yaml").write_text(
        "runtimes:\n  codex:\n    mode: copy\n    files: [../outside]\n",
        encoding="utf-8",
    )
    outcome = drift_outcome(_compare(ssot, local), local_root=str(local))
    assert outcome.status is Status.BLOCKED
    assert outcome.evidence["invalid_manifest_count"] == 1


def test_manifest_rejects_unknown_mode_and_windows_traversal(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    for root in (ssot, local):
        (root / "alpha").mkdir(parents=True)
        (root / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")
    manifest = ssot / "alpha" / "manifest.yaml"
    manifest.write_text(
        "runtimes:\n  codex:\n    mode: unknown\n    files: [SKILL.md]\n",
        encoding="utf-8",
    )
    assert drift_outcome(
        _compare(ssot, local), local_root=str(local)
    ).evidence["invalid_manifest_count"] == 1
    manifest.write_text(
        "runtimes:\n  codex:\n    mode: copy\n    files: ['C:/outside']\n",
        encoding="utf-8",
    )
    assert drift_outcome(
        _compare(ssot, local), local_root=str(local)
    ).evidence["invalid_manifest_count"] == 1
    manifest.write_text(
        "runtimes:\n  codex:\n    mode: copy\n    files: ['..\\outside']\n",
        encoding="utf-8",
    )
    assert drift_outcome(
        _compare(ssot, local), local_root=str(local)
    ).evidence["invalid_manifest_count"] == 1


def test_manifest_rejects_falsey_present_runtime_values(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    for root in (ssot, local):
        (root / "alpha").mkdir(parents=True)
        (root / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")
    manifest = ssot / "alpha" / "manifest.yaml"
    for content in ("runtimes: []\n", "runtimes:\n  codex: []\n"):
        manifest.write_text(content, encoding="utf-8")
        outcome = drift_outcome(_compare(ssot, local), local_root=str(local))
        assert outcome.status is Status.BLOCKED
        assert outcome.evidence["invalid_manifest_count"] == 1


def test_unreadable_declared_file_is_a_blocked_outcome(
    tmp_path: Path, monkeypatch
) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    for root in (ssot, local):
        (root / "alpha").mkdir(parents=True)
        (root / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")

    def unreadable(path: Path) -> str:
        if path.is_relative_to(local):
            raise PermissionError("denied")
        return "same-hash"

    monkeypatch.setattr("github_ops.skill_drift.sha256_file", unreadable)
    outcome = drift_outcome(_compare(ssot, local), local_root=str(local))
    assert outcome.status is Status.BLOCKED
    assert outcome.evidence["unreadable_count"] == 1
    assert outcome.evidence["unreadable_files"][0]["error_type"] == "PermissionError"


def test_unreadable_ssot_root_is_a_structured_blocked_outcome(
    tmp_path: Path, monkeypatch
) -> None:
    def denied(_root: Path) -> list[str]:
        raise PermissionError("denied")

    monkeypatch.setattr("github_ops.skill_drift.list_skill_names", denied)
    rows = _compare(tmp_path / "ssot", tmp_path / "local")
    outcome = drift_outcome(rows, local_root=str(tmp_path / "local"))
    assert outcome.status is Status.BLOCKED
    assert outcome.evidence["unreadable_files"] == [
        {
            "skill": ".",
            "path": ".",
            "side": "ssot_root",
            "error_type": "PermissionError",
        }
    ]


def test_missing_declared_source_blocks_even_when_runtime_is_also_missing(
    tmp_path: Path,
) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha").mkdir(parents=True)
    local.mkdir()
    (ssot / "alpha" / "manifest.yaml").write_text(
        "runtimes:\n  codex:\n    mode: copy\n    files: [missing.md]\n",
        encoding="utf-8",
    )
    outcome = drift_outcome(_compare(ssot, local), local_root=str(local))
    assert outcome.status is Status.BLOCKED
    assert outcome.evidence["invalid_paths"][0]["reason"] == "missing_declared_source"


def test_expected_runtime_symlink_blocks(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha").mkdir(parents=True)
    (local / "alpha").mkdir(parents=True)
    source = ssot / "alpha" / "SKILL.md"
    source.write_text("same\n", encoding="utf-8")
    try:
        (local / "alpha" / "SKILL.md").symlink_to(source)
    except OSError:
        return
    outcome = drift_outcome(_compare(ssot, local), local_root=str(local))
    assert outcome.status is Status.BLOCKED
    assert outcome.evidence["invalid_paths"][0]["reason"] == "unsafe_local_symlink"


def test_declared_ssot_symlink_blocks(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha").mkdir(parents=True)
    (local / "alpha").mkdir(parents=True)
    target = tmp_path / "source.md"
    target.write_text("same\n", encoding="utf-8")
    try:
        (ssot / "alpha" / "SKILL.md").symlink_to(target)
    except OSError:
        return
    (local / "alpha" / "SKILL.md").write_text("same\n", encoding="utf-8")
    outcome = drift_outcome(_compare(ssot, local), local_root=str(local))
    assert outcome.status is Status.BLOCKED
    assert outcome.evidence["invalid_paths"][0]["reason"] == "unsafe_ssot_symlink"


def test_declared_ssot_parent_symlink_blocks(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    outside = tmp_path / "outside"
    (ssot / "alpha").mkdir(parents=True)
    (local / "alpha" / "scripts").mkdir(parents=True)
    outside.mkdir()
    (outside / "helper.py").write_text("same\n", encoding="utf-8")
    try:
        (ssot / "alpha" / "scripts").symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    (local / "alpha" / "scripts" / "helper.py").write_text(
        "same\n", encoding="utf-8"
    )
    (ssot / "alpha" / "manifest.yaml").write_text(
        "runtimes:\n  codex:\n    mode: copy\n    files: [scripts/helper.py]\n",
        encoding="utf-8",
    )
    outcome = drift_outcome(_compare(ssot, local), local_root=str(local))
    assert outcome.status is Status.BLOCKED
    assert outcome.evidence["invalid_paths"][0]["reason"] == "unsafe_ssot_symlink"


def test_manifest_rejects_falsey_files_and_extra(tmp_path: Path) -> None:
    ssot = tmp_path / "ssot"
    local = tmp_path / "local"
    (ssot / "alpha").mkdir(parents=True)
    (local / "alpha").mkdir(parents=True)
    manifest = ssot / "alpha" / "manifest.yaml"
    for field, value in (("files", "null"), ("extra", "false")):
        manifest.write_text(
            f"runtimes:\n  codex:\n    mode: copy\n    {field}: {value}\n",
            encoding="utf-8",
        )
        outcome = drift_outcome(_compare(ssot, local), local_root=str(local))
        assert outcome.status is Status.BLOCKED
        assert outcome.evidence["invalid_manifest_count"] == 1
