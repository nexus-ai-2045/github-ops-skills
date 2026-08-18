"""Compare repository skill SSOT files against optional local runtime roots."""

from __future__ import annotations

import hashlib
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

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
    runtime: str,
) -> list[SkillFileDrift]:
    # Only SSOT skills are compared. Local-only skills outside this Core Suite
    # are ignored to avoid high-dimensional noise from large runtime roots.
    skills = list_skill_names(ssot_skills_root)
    rows: list[SkillFileDrift] = []
    for skill in skills:
        skill_root = ssot_skills_root / skill
        if _has_unsafe_component(ssot_skills_root, skill_root):
            rows.append(
                SkillFileDrift(
                    skill=skill,
                    relative_path=".",
                    ssot_sha256=None,
                    local_sha256=None,
                    status="unsafe_ssot_symlink",
                )
            )
            continue
        try:
            mappings = _runtime_file_mappings(skill_root, runtime=runtime)
        except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
            rows.append(
                SkillFileDrift(
                    skill=skill,
                    relative_path="manifest.yaml",
                    ssot_sha256=None,
                    local_sha256=None,
                    status=f"invalid_manifest:{type(exc).__name__}",
                )
            )
            continue
        if not mappings:
            continue
        expected_local_paths = {relative for relative, _ in mappings}
        for relative, source_relative in mappings:
            ssot_path = ssot_skills_root / skill / source_relative
            local_path = local_skills_root / skill / relative
            if _has_unsafe_component(ssot_skills_root, ssot_path):
                rows.append(
                    SkillFileDrift(
                        skill=skill,
                        relative_path=relative,
                        ssot_sha256=None,
                        local_sha256=None,
                        status="unsafe_ssot_symlink",
                    )
                )
                continue
            if _has_unsafe_component(local_skills_root, local_path):
                rows.append(
                    SkillFileDrift(
                        skill=skill,
                        relative_path=relative,
                        ssot_sha256=None,
                        local_sha256=None,
                        status="unsafe_local_symlink",
                    )
                )
                continue
            if not ssot_path.is_file():
                rows.append(
                    SkillFileDrift(
                        skill=skill,
                        relative_path=relative,
                        ssot_sha256=None,
                        local_sha256=None,
                        status="missing_declared_source",
                    )
                )
                continue
            try:
                ssot_hash = sha256_file(ssot_path)
            except OSError as exc:
                rows.append(
                    SkillFileDrift(
                        skill=skill,
                        relative_path=relative,
                        ssot_sha256=None,
                        local_sha256=None,
                        status=f"unreadable_ssot:{type(exc).__name__}",
                    )
                )
                continue
            try:
                local_hash = sha256_file(local_path) if local_path.is_file() else None
            except OSError as exc:
                rows.append(
                    SkillFileDrift(
                        skill=skill,
                        relative_path=relative,
                        ssot_sha256=ssot_hash,
                        local_sha256=None,
                        status=f"unreadable_local:{type(exc).__name__}",
                    )
                )
                continue
            if local_hash is None:
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
        local_skill_root = local_skills_root / skill
        if local_skill_root.is_dir():
            try:
                local_candidates = sorted(local_skill_root.rglob("*"))
            except OSError as exc:
                rows.append(
                    SkillFileDrift(
                        skill=skill,
                        relative_path=".",
                        ssot_sha256=None,
                        local_sha256=None,
                        status=f"unreadable_local:{type(exc).__name__}",
                    )
                )
                continue
            for candidate in local_candidates:
                if not (candidate.is_file() or candidate.is_symlink()):
                    continue
                relative = candidate.relative_to(local_skill_root).as_posix()
                if relative in expected_local_paths:
                    continue
                try:
                    local_hash = (
                        sha256_file(candidate)
                        if candidate.is_file() and not candidate.is_symlink()
                        else None
                    )
                except OSError as exc:
                    rows.append(
                        SkillFileDrift(
                            skill=skill,
                            relative_path=relative,
                            ssot_sha256=None,
                            local_sha256=None,
                            status=f"unreadable_local:{type(exc).__name__}",
                        )
                    )
                    continue
                rows.append(
                    SkillFileDrift(
                        skill=skill,
                        relative_path=relative,
                        ssot_sha256=None,
                        local_sha256=local_hash,
                        status="local_only",
                    )
                )
    return rows


def _runtime_file_mappings(
    skill_root: Path, *, runtime: str
) -> list[tuple[str, str]]:
    files = {("SKILL.md", "SKILL.md")}
    manifest = skill_root / "manifest.yaml"
    if _has_unsafe_component(skill_root, manifest):
        raise ValueError("manifest path must not contain symlinks or reparse points")
    if not manifest.is_file():
        return sorted(files)
    payload = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest root must be a mapping")
    runtimes = payload.get("runtimes", {})
    if not isinstance(runtimes, dict):
        raise ValueError("manifest runtimes must be a mapping")
    if runtime not in runtimes:
        return []
    runtime_config = runtimes[runtime]
    if not isinstance(runtime_config, dict):
        raise ValueError("runtime config must be a mapping")
    mode = runtime_config.get("mode")
    if mode == "skip":
        return []
    if mode != "copy":
        raise ValueError("runtime mode must be copy or skip")
    declared_files = runtime_config.get("files", [])
    extras = runtime_config.get("extra", {})
    if not isinstance(declared_files, list) or not all(
        isinstance(item, str) for item in declared_files
    ):
        raise ValueError("runtime files must be a list of paths")
    if not isinstance(extras, dict) or not all(
        isinstance(target, str) and isinstance(source, str)
        for target, source in extras.items()
    ):
        raise ValueError("runtime extra must map target paths to source paths")
    files = set()
    files.update((item, item) for item in declared_files)
    files.update(
        (target, source)
        for target, source in extras.items()
    )
    if not files:
        raise ValueError("copy runtime must declare at least one file")
    targets = [target for target, _ in files]
    if len(targets) != len(set(targets)):
        raise ValueError("runtime target paths must be unique")
    for target, source in files:
        if not _safe_relative_path(target) or not _safe_relative_path(source):
            raise ValueError("runtime paths must stay inside their skill roots")
    return sorted(files)


def _safe_relative_path(value: str) -> bool:
    if not value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def _has_unsafe_component(root: Path, candidate: Path) -> bool:
    root = root.absolute()
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in (Path(), *relative.parts):
        if part != Path():
            current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag):
            return True
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return True
    return False


def drift_outcome(rows: list[SkillFileDrift], *, local_root: str) -> Outcome:
    drifts = [row for row in rows if row.status == "drift"]
    local_only = [row for row in rows if row.status == "local_only"]
    missing = [row for row in rows if row.status == "ssot_only"]
    invalid = [row for row in rows if row.status.startswith("invalid_manifest:")]
    unreadable = [row for row in rows if row.status.startswith("unreadable_")]
    invalid_paths = [
        row
        for row in rows
        if row.status
        in {"missing_declared_source", "unsafe_ssot_symlink", "unsafe_local_symlink"}
    ]
    evidence = {
        "local_root": local_root,
        "compared_files": len(rows),
        "match_count": sum(1 for row in rows if row.status == "match"),
        "drift_count": len(drifts),
        "local_only_count": len(local_only),
        "ssot_only_count": sum(1 for row in rows if row.status == "ssot_only"),
        "invalid_manifest_count": len(invalid),
        "unreadable_count": len(unreadable),
        "invalid_path_count": len(invalid_paths),
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
        "invalid_manifests": [
            {"skill": row.skill, "error_type": row.status.split(":", 1)[1]}
            for row in invalid
        ],
        "unreadable_files": [
            {
                "skill": row.skill,
                "path": row.relative_path,
                "side": row.status.split(":", 1)[0].removeprefix("unreadable_"),
                "error_type": row.status.split(":", 1)[1],
            }
            for row in unreadable
        ],
        "invalid_paths": [
            {"skill": row.skill, "path": row.relative_path, "reason": row.status}
            for row in invalid_paths
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
    if drifts or local_only or missing or invalid or unreadable or invalid_paths:
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
