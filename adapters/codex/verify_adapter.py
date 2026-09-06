from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from github_ops.source_manifest import verify_target_hashes

REQUIRED_SKILLS = {
    "commit-push-pr",
    "cross-repo-wip-ownership",
    "github-cli-ops-guard",
    "new-repo-bootstrap",
    "post-merge-closeout",
    "pr-convergence-loop",
    "pr-status",
    "public-repo-readiness",
    "review-pr",
}

SOURCE_KEYS = {
    "source_root": str,
    "source_path": str,
    "target_path": str,
    "sha256": str,
    "source_sha256": str,
    "target_sha256": str,
    "normalized": bool,
}


def _valid_source(record: object) -> bool:
    if not isinstance(record, dict):
        return False
    for key, expected_type in SOURCE_KEYS.items():
        value = record.get(key)
        if not isinstance(value, expected_type):
            return False
        if expected_type is str and not value.strip():
            return False
    for key in ("sha256", "source_sha256", "target_sha256"):
        value = record[key]
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            return False
    for key in ("source_path", "target_path"):
        path = Path(record[key])
        if path.is_absolute() or ".." in path.parts:
            return False
    return True


def verify(repo: Path) -> dict[str, object]:
    root = (repo / "skills").resolve()
    manifest = (repo / "migration" / "source-manifest.json").resolve()
    skills = sorted(path.name for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
    manifest_payload: dict[str, object] | None = None
    manifest_sha256: str | None = None
    if manifest.is_file():
        try:
            manifest_bytes = manifest.read_bytes()
            candidate = json.loads(manifest_bytes.decode("utf-8"))
            if isinstance(candidate, dict):
                manifest_payload = candidate
            manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    sources = manifest_payload.get("sources") if manifest_payload else None
    manifest_valid = bool(
        manifest_payload
        and manifest_payload.get("schema_version") == "github-ops/source-manifest/v1"
        and isinstance(sources, list)
        and sources
        and all(_valid_source(record) for record in sources)
    )
    manifest_target_errors: list[str] = []
    provenance_skills: set[str] = set()
    if manifest_valid:
        for record in sources:
            target_parts = Path(record["target_path"]).parts
            if len(target_parts) >= 2 and target_parts[0] == "skills":
                provenance_skills.add(target_parts[1])
        try:
            manifest_target_errors = verify_target_hashes(repo.resolve())
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            manifest_target_errors = [f"manifest target verification failed: {type(exc).__name__}"]
    manifest_valid = manifest_valid and not manifest_target_errors
    missing_skills = sorted(REQUIRED_SKILLS - set(skills))
    missing_provenance_skills = sorted(REQUIRED_SKILLS - provenance_skills)
    unexpected_skills = sorted(set(skills) - REQUIRED_SKILLS)
    missing_entrypoints = []
    invalid_entrypoints = []
    for name in sorted(REQUIRED_SKILLS):
        entrypoint = root / name / "SKILL.md"
        if not entrypoint.is_file():
            missing_entrypoints.append(name)
            continue
        try:
            if not entrypoint.read_text(encoding="utf-8").strip():
                invalid_entrypoints.append(name)
        except (OSError, UnicodeError):
            invalid_entrypoints.append(name)
    return {
        "status": "READY"
        if not missing_skills
        and not unexpected_skills
        and not missing_entrypoints
        and not invalid_entrypoints
        and not missing_provenance_skills
        and manifest_valid
        else "BLOCKED",
        "skill_root": str(root),
        "skill_count": len(skills),
        "skills": skills,
        "missing_skills": missing_skills,
        "unexpected_skills": unexpected_skills,
        "missing_entrypoints": missing_entrypoints,
        "invalid_entrypoints": invalid_entrypoints,
        "missing_provenance_skills": missing_provenance_skills,
        "manifest_valid": manifest_valid,
        "manifest_target_errors": manifest_target_errors,
        "manifest_sha256": manifest_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify(args.repo)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
