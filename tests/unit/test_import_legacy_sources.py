import hashlib
import json
from pathlib import Path

from scripts.import_legacy_sources import (
    SKILL_SOURCES,
    _safe_child,
    import_sources,
    main,
    verify_records,
)


def test_import_copies_without_modifying_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "skill-a").mkdir(parents=True)
    original = source / "skill-a" / "SKILL.md"
    original.write_text("# Skill A\n", encoding="utf-8")

    records = import_sources(
        mappings=[("shared", "skill-a/SKILL.md", "skills/skill-a/SKILL.md")],
        source_roots={"shared": source},
        target_root=target,
    )

    assert original.read_text(encoding="utf-8") == "# Skill A\n"
    assert len(records[0]["sha256"]) == 64
    assert (
        target / "skills/skill-a/SKILL.md"
    ).read_text(encoding="utf-8") == "# Skill A\n"
    assert verify_records(records, {"shared": source}, target) == []


def test_target_digest_is_portable_across_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "skill.md").write_bytes(b"one\ntwo\n")
    records = import_sources(
        mappings=[("shared", "skill.md", "skills/skill.md")],
        source_roots={"shared": source},
        target_root=target,
    )
    (target / "skills/skill.md").write_bytes(b"one\r\ntwo\r\n")
    assert verify_records(records, {"shared": source}, target) == []


def test_line_ending_conversion_is_not_reported_as_identity_normalization(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "skill.md").write_bytes(b"one\r\ntwo\r\n")

    records = import_sources(
        mappings=[("shared", "skill.md", "skills/skill.md")],
        source_roots={"shared": source},
        target_root=target,
    )

    assert records[0]["normalized"] is False


def test_import_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    actual = source / "actual.md"
    actual.write_text("safe", encoding="utf-8")
    link = source / "link.md"
    try:
        link.symlink_to(actual)
    except OSError:
        return

    try:
        import_sources(
            mappings=[("shared", "link.md", "skills/link.md")],
            source_roots={"shared": source},
            target_root=target,
        )
    except ValueError as exc:
        assert "symlink" in str(exc)
    else:
        raise AssertionError("symlink must be rejected")


def test_safe_child_rejects_escape_after_missing_component(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    try:
        _safe_child(root, "missing/../../escaped.txt")
    except ValueError as exc:
        assert "escapes root" in str(exc)
    else:
        raise AssertionError("missing component must not bypass root boundary")


def test_verify_only_handles_local_source_root_without_keyerror(
    tmp_path: Path,
    capsys,
) -> None:
    repo = tmp_path / "repo"
    (repo / "skills" / "x").mkdir(parents=True)
    target = repo / "skills" / "x" / "SKILL.md"
    target.write_text("local\n", encoding="utf-8")
    digest = hashlib.sha256(b"local\n").hexdigest()
    manifest_dir = repo / "migration"
    manifest_dir.mkdir()
    (manifest_dir / "source-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "github-ops/source-manifest/v1",
                "sources": [
                    {
                        "source_root": "github-ops-skills",
                        "source_path": "skills/x/SKILL.md",
                        "target_path": "skills/x/SKILL.md",
                        "sha256": digest,
                        "source_sha256": digest,
                        "target_sha256": digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    shared_root = tmp_path / "shared"
    shared_root.mkdir()
    agent_root = tmp_path / "agent-skills"
    agent_root.mkdir()

    exit_code = main(
        [
            "--verify-only",
            "--shared-root",
            str(shared_root),
            "--agent-skills-root",
            str(agent_root),
            "--repo",
            str(repo),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {"status": "ok", "errors": []}


def test_import_preserves_existing_local_root_records(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    shared_root = tmp_path / "shared"
    (shared_root / "skills" / "skill-a").mkdir(parents=True)
    (shared_root / "skills" / "skill-a" / "SKILL.md").write_text(
        "# Skill A\n", encoding="utf-8"
    )
    agent_root = tmp_path / "agent-skills"
    agent_root.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()

    local_digest = "a" * 64
    manifest_dir = repo / "migration"
    manifest_dir.mkdir()
    (manifest_dir / "source-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "github-ops/source-manifest/v1",
                "sources": [
                    {
                        "source_root": "github-ops-skills",
                        "source_path": "skills/local/SKILL.md",
                        "target_path": "skills/local/SKILL.md",
                        "sha256": local_digest,
                        "source_sha256": local_digest,
                        "target_sha256": local_digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.import_legacy_sources.SKILL_SOURCES",
        {"skill-a": ("shared", "skills/skill-a")},
    )

    exit_code = main(
        [
            "--shared-root",
            str(shared_root),
            "--agent-skills-root",
            str(agent_root),
            "--repo",
            str(repo),
        ]
    )
    assert exit_code == 0
    capsys.readouterr()

    payload = json.loads(
        (manifest_dir / "source-manifest.json").read_text(encoding="utf-8")
    )
    local_records = [
        record
        for record in payload["sources"]
        if record["source_root"] == "github-ops-skills"
    ]
    assert len(local_records) == 1
    assert local_records[0]["source_path"] == "skills/local/SKILL.md"
    assert local_records[0]["sha256"] == local_digest


def test_import_normalizes_private_identity_without_modifying_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "skill-a").mkdir(parents=True)
    original = source / "skill-a" / "SKILL.md"
    private_name = "y" + "as"
    original_text = (
        "# Skill A\n"
        f"`C:\\Users\\{private_name}\\Documents\\tool.ps1`\n"
        f"Do not expose {private_name}.\n"
    )
    original.write_text(original_text, encoding="utf-8")

    records = import_sources(
        mappings=[("shared", "skill-a/SKILL.md", "skills/skill-a/SKILL.md")],
        source_roots={"shared": source},
        target_root=target,
    )

    imported = (target / "skills/skill-a/SKILL.md").read_text(encoding="utf-8")
    assert original.read_text(encoding="utf-8") == original_text
    assert "C:\\Users\\" not in imported
    assert private_name not in imported
    assert "<USER_HOME>" in imported
    assert records[0]["normalized"] is True
    assert records[0]["source_sha256"] != records[0]["target_sha256"]
    assert verify_records(records, {"shared": source}, target) == []
