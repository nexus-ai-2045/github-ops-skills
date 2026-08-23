import hashlib
import json
from unittest.mock import patch
from pathlib import Path

from github_ops.source_manifest import refresh_target_hashes, verify_target_hashes


def test_target_hash_mismatch_is_detected_and_refreshable(tmp_path: Path) -> None:
    target = tmp_path / "skills" / "x" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("current\n", encoding="utf-8")
    manifest = tmp_path / "migration" / "source-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({"schema_version": "github-ops/source-manifest/v1", "sources": [{
        "target_path": "skills/x/SKILL.md",
        "sha256": "0" * 64,
        "target_sha256": "0" * 64,
    }]}), encoding="utf-8")
    assert verify_target_hashes(tmp_path) == ["target hash mismatch: skills/x/SKILL.md"]
    assert refresh_target_hashes(tmp_path) == 1
    assert verify_target_hashes(tmp_path) == []
    record = json.loads(manifest.read_text(encoding="utf-8"))["sources"][0]
    assert record["target_sha256"] == hashlib.sha256(b"current\n").hexdigest()


def test_duplicate_target_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "skills" / "x" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("current\n", encoding="utf-8")
    digest = hashlib.sha256(b"current\n").hexdigest()
    manifest = tmp_path / "migration" / "source-manifest.json"
    manifest.parent.mkdir()
    record = {"target_path": "skills/x/SKILL.md", "target_sha256": digest}
    manifest.write_text(json.dumps({
        "schema_version": "github-ops/source-manifest/v1",
        "sources": [record, record],
    }), encoding="utf-8")
    assert verify_target_hashes(tmp_path) == ["duplicate target path: skills/x/SKILL.md"]


def test_parent_traversal_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "migration" / "source-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({
        "schema_version": "github-ops/source-manifest/v1",
        "sources": [{"target_path": "../outside", "target_sha256": "0" * 64}],
    }), encoding="utf-8")
    assert verify_target_hashes(tmp_path) == ["target escapes repository: ../outside"]


def test_line_endings_have_one_portable_digest(tmp_path: Path) -> None:
    target = tmp_path / "skills" / "x" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"one\r\ntwo\r\n")
    digest = hashlib.sha256(b"one\ntwo\n").hexdigest()
    manifest = tmp_path / "migration" / "source-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({
        "schema_version": "github-ops/source-manifest/v1",
        "sources": [{"target_path": "skills/x/SKILL.md", "target_sha256": digest}],
    }), encoding="utf-8")
    assert verify_target_hashes(tmp_path) == []


def test_unverifiable_path_component_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "skills" / "x" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("current\n", encoding="utf-8")
    manifest = tmp_path / "migration" / "source-manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({
        "schema_version": "github-ops/source-manifest/v1",
        "sources": [{
            "target_path": "skills/x/SKILL.md",
            "target_sha256": hashlib.sha256(b"current\n").hexdigest(),
        }],
    }), encoding="utf-8")
    real_lstat = __import__("os").lstat

    def fail_target(path):  # noqa: ANN001, ANN202
        if Path(path) == tmp_path / "skills":
            raise PermissionError("denied")
        return real_lstat(path)

    with patch("github_ops.source_manifest.os.lstat", side_effect=fail_target):
        assert verify_target_hashes(tmp_path) == ["unsafe target path: skills/x/SKILL.md"]


def test_symlinked_manifest_is_rejected_before_refresh(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-manifest.json"
    outside.write_text(
        json.dumps({"schema_version": "github-ops/source-manifest/v1", "sources": []}),
        encoding="utf-8",
    )
    migration = tmp_path / "migration"
    migration.mkdir()
    try:
        (migration / "source-manifest.json").symlink_to(outside)
    except OSError:
        return

    assert verify_target_hashes(tmp_path) == ["unsafe manifest path"]
    with __import__("pytest").raises(ValueError, match="unsafe manifest path"):
        refresh_target_hashes(tmp_path)
    assert outside.read_text(encoding="utf-8").endswith("}")
