from pathlib import Path

from scripts.import_legacy_sources import _safe_child, import_sources, verify_records


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
