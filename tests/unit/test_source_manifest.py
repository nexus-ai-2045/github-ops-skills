import hashlib
import json
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
    assert record["target_sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()


def test_duplicate_target_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "skills" / "x" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("current\n", encoding="utf-8")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
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
