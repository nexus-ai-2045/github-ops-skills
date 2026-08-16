"""Compare repository skill SSOT files against optional local runtime roots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from .result import Outcome, Status


@dataclass(frozen=True)
class SkillFileDrift:
    skill: str
    relative_path: str
    ssot_sha256: str | None
    local_sha256: str | None
    status: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_skill_names(skills_root: Path) -> list[str]:
    if not skills_root.is_dir():
        return []
    return sorted(path.name for path in skills_root.iterdir() if path.is_dir())


def compare_skill_roots(
    *,
    ssot_skills_root: Path,
    local_skills_root: Path,
) -> list[SkillFileDrift]:
    # Only SSOT skills are compared. Local-only skills outside this Core Suite
    # are ignored to avoid high-dimensional noise from large runtime roots.
    skills = list_skill_names(ssot_skills_root)
    rows: list[SkillFileDrift] = []
    for skill in skills:
        skill_root = ssot_skills_root / skill
        mappings = _runtime_file_mappings(skill_root)
        for relative, source_relative in mappings:
            ssot_path = ssot_skills_root / skill / source_relative
            local_path = local_skills_root / skill / relative
            ssot_hash = sha256_file(ssot_path) if ssot_path.is_file() else None
            local_hash = sha256_file(local_path) if local_path.is_file() else None
            if ssot_hash is None and local_hash is None:
                continue
            if ssot_hash is None:
                status = "local_only"
            elif local_hash is None:
                status = "ssot_only"
            elif ssot_hash == local_hash:
                status = "match"
            else:
                status = "drift"
            rows.append(
                SkillFileDrift(
                    skill=skill,
                    relative_path=relative,
                    ssot_sha256=ssot_hash,
                    local_sha256=local_hash,
                    status=status,
                )
            )
    return rows


def _runtime_file_mappings(skill_root: Path) -> list[tuple[str, str]]:
    files = {("SKILL.md", "SKILL.md")}
    manifest = skill_root / "manifest.yaml"
    if not manifest.is_file():
        return sorted(files)
    files.add(("manifest.yaml", "manifest.yaml"))
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    for runtime in (payload.get("runtimes") or {}).values():
        files.update((item, item) for item in (runtime.get("files") or []))
        files.update((target, source) for target, source in (runtime.get("extra") or {}).items())
    return sorted(files)


def drift_outcome(rows: list[SkillFileDrift], *, local_root: str) -> Outcome:
    drifts = [row for row in rows if row.status == "drift"]
    local_only = [row for row in rows if row.status == "local_only"]
    missing = [row for row in rows if row.status == "ssot_only"]
    evidence = {
        "local_root": local_root,
        "compared_files": len(rows),
        "match_count": sum(1 for row in rows if row.status == "match"),
        "drift_count": len(drifts),
        "local_only_count": len(local_only),
        "ssot_only_count": sum(1 for row in rows if row.status == "ssot_only"),
        "drifts": [
            {
                "skill": row.skill,
                "path": row.relative_path,
                "ssot_sha256": row.ssot_sha256,
                "local_sha256": row.local_sha256,
            }
            for row in drifts
        ],
        "local_only": [
            {"skill": row.skill, "path": row.relative_path} for row in local_only
        ],
    }
    if not rows:
        return Outcome(
            status=Status.UNKNOWN,
            code="drift_no_overlap",
            cause="比較対象のskill fileが見つかりません",
            impact="runtime同期状態を断定できません",
            recovery="local rootとskills/を確認してください",
            evidence=evidence,
        )
    if drifts or local_only or missing:
        return Outcome(
            status=Status.BLOCKED,
            code="skill_drift_detected",
            cause="SSOTとlocal runtime skillに差分があります",
            impact="古い手順や未吸収の運用ゲートが混在する可能性があります",
            recovery="差分をレビューし、portableな学習だけをSSOTへ吸収してください",
            evidence=evidence,
        )
    return Outcome(
        status=Status.READY,
        code="skill_drift_clean",
        cause="比較したskill fileはSSOTと一致しています",
        impact="runtime参照をSSOT前提で扱えます",
        recovery="none",
        evidence=evidence,
    )
