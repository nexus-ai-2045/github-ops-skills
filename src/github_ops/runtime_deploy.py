"""Plan, deploy, verify, and roll back manifest-managed runtime skills."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .skill_drift import (
    _has_unsafe_component,
    _runtime_file_mappings,
    _safe_relative_path,
    sha256_file,
)


PROJECTION_MARKER = ".github-ops-projection.json"
OWNER_REPOSITORY = "nexus-ai-2045/github-ops-skills"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _managed_files(
    repo_root: Path,
    target_root: Path,
    *,
    runtime: str,
    selected_skills: list[str] | None,
) -> list[dict[str, Any]]:
    repo_root = repo_root.resolve(strict=True)
    skills_root = repo_root / "skills"
    target_root = target_root.resolve(strict=False)
    if target_root.is_symlink() or _has_unsafe_component(target_root.parent, target_root):
        raise ValueError("target root must not be a symlink or reparse point")
    available = {path.name: path for path in skills_root.iterdir() if path.is_dir()}
    selected = set(selected_skills or available)
    missing = sorted(selected - set(available))
    if missing:
        raise ValueError(f"unknown skills: {missing}")
    entries: list[dict[str, Any]] = []
    for name in sorted(selected):
        skill_root = available[name]
        for destination_relative, source_relative in _runtime_file_mappings(
            skill_root, runtime=runtime
        ):
            source = skill_root / source_relative
            destination = target_root / name / destination_relative
            if _has_unsafe_component(skills_root, source):
                raise ValueError(f"unsafe source path: {name}/{source_relative}")
            if _has_unsafe_component(target_root, destination):
                raise ValueError(f"unsafe destination path: {name}/{destination_relative}")
            if not source.is_file():
                raise ValueError(f"missing source file: {name}/{source_relative}")
            source_hash = sha256_file(source)
            destination_hash = sha256_file(destination) if destination.is_file() else None
            entries.append(
                {
                    "skill": name,
                    "relative_path": destination_relative,
                    "source": source,
                    "destination": destination,
                    "source_sha256": source_hash,
                    "destination_sha256": destination_hash,
                    "status": (
                        "missing"
                        if destination_hash is None
                        else "match"
                        if destination_hash == source_hash
                        else "drift"
                    ),
                }
            )
    if not entries:
        raise ValueError(f"no managed files for runtime: {runtime}")
    for skill in sorted({entry["skill"] for entry in entries}):
        managed = {
            entry["relative_path"]: entry["source_sha256"]
            for entry in entries
            if entry["skill"] == skill
        }
        content = (
            json.dumps(
                {
                    "schema_version": "github-ops-skill-projection/v1",
                    "owner_repository": OWNER_REPOSITORY,
                    "skill": skill,
                    "runtime": runtime,
                    "managed_files": managed,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        destination = target_root / skill / PROJECTION_MARKER
        destination_hash = sha256_file(destination) if destination.is_file() else None
        marker_hash = hashlib.sha256(content).hexdigest()
        entries.append(
            {
                "skill": skill,
                "relative_path": PROJECTION_MARKER,
                "source": None,
                "content": content,
                "destination": destination,
                "source_sha256": marker_hash,
                "destination_sha256": destination_hash,
                "status": (
                    "missing"
                    if destination_hash is None
                    else "match"
                    if destination_hash == marker_hash
                    else "drift"
                ),
            }
        )
    return entries


def plan_skills(
    repo_root: Path,
    target_root: Path,
    *,
    runtime: str,
    selected_skills: list[str] | None = None,
) -> dict[str, Any]:
    entries = _managed_files(
        repo_root, target_root, runtime=runtime, selected_skills=selected_skills
    )
    summary = {
        state: sum(1 for entry in entries if entry["status"] == state)
        for state in ("match", "drift", "missing")
    }
    return {
        "status": "ready" if summary["drift"] == 0 and summary["missing"] == 0 else "drift",
        "runtime": runtime,
        "target_root": str(target_root.resolve(strict=False)),
        "summary": summary,
        "files": [
            {
                "skill": entry["skill"],
                "path": entry["relative_path"],
                "status": entry["status"],
            }
            for entry in entries
        ],
    }


def _validate_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("schema_version") != "github-ops-runtime-deploy/v1":
        raise ValueError("unsupported receipt schema")
    files = receipt.get("files")
    if not isinstance(files, list):
        raise ValueError("receipt files must be a list")
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("receipt file entry must be an object")
        skill = entry.get("skill")
        relative = entry.get("relative_path")
        if (
            not isinstance(skill, str)
            or not _safe_relative_path(skill)
            or "/" in skill
            or not isinstance(relative, str)
            or not _safe_relative_path(relative)
        ):
            raise ValueError("unsafe receipt path")


def _restore(receipt: dict[str, Any]) -> None:
    _validate_receipt(receipt)
    target_root = Path(receipt["target_root"])
    backup_path = Path(receipt["backup_path"])
    for entry in receipt["files"]:
        destination = target_root / entry["skill"] / entry["relative_path"]
        if entry["existed_before"]:
            source = backup_path / "files" / entry["skill"] / entry["relative_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        else:
            destination.unlink(missing_ok=True)


def deploy_skills(
    repo_root: Path,
    target_root: Path,
    *,
    runtime: str,
    selected_skills: list[str] | None,
    backup_root: Path,
    approval_ref: str,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("deploy requires explicit confirm")
    if not approval_ref.strip():
        raise ValueError("deploy requires approval_ref")
    entries = _managed_files(
        repo_root, target_root, runtime=runtime, selected_skills=selected_skills
    )
    operation = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    backup_path = backup_root.resolve() / operation
    receipt_path = backup_path / "receipt.json"
    receipt: dict[str, Any] = {
        "schema_version": "github-ops-runtime-deploy/v1",
        "status": "preparing",
        "created_at": _now(),
        "approval_ref": approval_ref,
        "runtime": runtime,
        "target_root": str(target_root.resolve(strict=False)),
        "backup_path": str(backup_path),
        "verified": False,
        "files": [],
    }
    try:
        for entry in entries:
            destination: Path = entry["destination"]
            existed = destination.is_file()
            record = {
                "skill": entry["skill"],
                "relative_path": entry["relative_path"],
                "source_sha256": entry["source_sha256"],
                "existed_before": existed,
            }
            receipt["files"].append(record)
            if existed:
                backup = backup_path / "files" / entry["skill"] / entry["relative_path"]
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
        receipt["status"] = "backup_complete"
        _write_json(receipt_path, receipt)

        for entry in entries:
            destination: Path = entry["destination"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=f".{destination.name}.", delete=False
            ) as handle:
                content = entry.get("content")
                handle.write(
                    content if isinstance(content, bytes) else Path(entry["source"]).read_bytes()
                )
                temporary = Path(handle.name)
            os.replace(temporary, destination)

        failures = [
            entry
            for entry in entries
            if sha256_file(entry["destination"]) != entry["source_sha256"]
        ]
        if failures:
            raise RuntimeError("post-deploy verification failed")
        receipt["status"] = "verified"
        receipt["verified"] = True
        receipt["verified_at"] = _now()
        _write_json(receipt_path, receipt)
    except Exception:
        if receipt_path.exists():
            _restore(receipt)
            receipt["status"] = "rolled_back_after_failure"
            _write_json(receipt_path, receipt)
        raise
    return {
        "status": "verified",
        "runtime": runtime,
        "managed_files": len(entries),
        "receipt_path": str(receipt_path),
    }


def rollback_deployment(receipt_path: Path) -> dict[str, Any]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    _validate_receipt(receipt)
    if receipt.get("status") not in {"verified", "backup_complete"}:
        raise ValueError("receipt is not rollback eligible")
    _restore(receipt)
    rollback = {
        "status": "rolled_back",
        "receipt_path": str(receipt_path),
        "rolled_back_at": _now(),
    }
    _write_json(receipt_path.parent / "rollback-receipt.json", rollback)
    return rollback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "deploy"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--repo", type=Path, default=Path.cwd())
        sub.add_argument("--runtime", choices=("codex", "claude", "grok"), required=True)
        sub.add_argument("--target-root", type=Path, required=True)
        sub.add_argument("--skill", action="append", dest="skills")
        sub.add_argument("--json", action="store_true")
        if command == "deploy":
            sub.add_argument("--backup-root", type=Path, required=True)
            sub.add_argument("--approval-ref", required=True)
            sub.add_argument("--confirm", action="store_true")
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--receipt", type=Path, required=True)
    rollback.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "rollback":
        result = rollback_deployment(args.receipt)
    elif args.command == "plan":
        result = plan_skills(
            args.repo, args.target_root, runtime=args.runtime, selected_skills=args.skills
        )
    else:
        result = deploy_skills(
            args.repo,
            args.target_root,
            runtime=args.runtime,
            selected_skills=args.skills,
            backup_root=args.backup_root,
            approval_ref=args.approval_ref,
            confirmed=args.confirm,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
