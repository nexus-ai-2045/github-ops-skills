from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path


SCHEMA_VERSION = "github-ops/source-manifest/v1"


def _portable_digest(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def _unsafe_component(repo: Path, target: Path) -> bool:
    current = repo.resolve()
    relative = target.relative_to(repo)
    for part in relative.parts:
        current /= part
        try:
            info = os.lstat(current)
        except OSError:
            return True
        attributes = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attributes & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            return True
    return False


def _manifest_path(repo: Path) -> Path:
    manifest = repo / "migration" / "source-manifest.json"
    if _unsafe_component(repo, manifest):
        raise ValueError("unsafe manifest path")
    return manifest


def verify_target_hashes(repo: Path) -> list[str]:
    try:
        manifest = _manifest_path(repo)
    except ValueError as exc:
        return [str(exc)]
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("invalid schema_version")
    records = payload.get("sources")
    if not isinstance(records, list):
        return errors + ["sources must be a list"]
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            errors.append("invalid target record")
            continue
        relative = record.get("target_path")
        expected = record.get("target_sha256") or record.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            errors.append("invalid target record")
            continue
        if relative in seen:
            errors.append(f"duplicate target path: {relative}")
            continue
        seen.add(relative)
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            errors.append(f"target escapes repository: {relative}")
            continue
        unresolved = repo / relative_path
        if _unsafe_component(repo, unresolved):
            errors.append(f"unsafe target path: {relative}")
            continue
        target = unresolved.resolve()
        try:
            target.relative_to(repo.resolve())
        except ValueError:
            errors.append(f"target escapes repository: {relative}")
            continue
        if not target.is_file():
            errors.append(f"target missing: {relative}")
            continue
        actual = _portable_digest(target)
        if actual != expected:
            errors.append(f"target hash mismatch: {relative}")
    return errors


def refresh_target_hashes(repo: Path) -> int:
    manifest = _manifest_path(repo)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    count = 0
    errors = verify_target_hashes(repo)
    structural = [error for error in errors if "hash mismatch" not in error]
    if structural:
        raise ValueError("; ".join(structural))
    for record in payload.get("sources", []):
        relative = record["target_path"]
        target = (repo / relative).resolve()
        target.relative_to(repo.resolve())
        digest = _portable_digest(target)
        record["sha256"] = digest
        record["target_sha256"] = digest
        count += 1
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return count
