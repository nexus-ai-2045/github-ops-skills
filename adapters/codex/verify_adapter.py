from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REQUIRED_SKILLS = {
    "commit-push-pr",
    "cross-repo-wip-ownership",
    "github-cli-ops-guard",
    "post-merge-closeout",
    "pr-convergence-loop",
    "pr-status",
    "public-repo-readiness",
    "review-pr",
}


def verify(repo: Path) -> dict[str, object]:
    root = (repo / "skills").resolve()
    manifest = (repo / "migration" / "source-manifest.json").resolve()
    skills = sorted(path.name for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
    manifest_payload: dict[str, object] | None = None
    if manifest.is_file():
        try:
            candidate = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                manifest_payload = candidate
        except (OSError, json.JSONDecodeError):
            pass
    manifest_valid = bool(
        manifest_payload
        and manifest_payload.get("schema_version") == "github-ops/source-manifest/v1"
        and isinstance(manifest_payload.get("sources"), list)
        and manifest_payload.get("sources")
    )
    missing_skills = sorted(REQUIRED_SKILLS - set(skills))
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
        and manifest_valid
        else "BLOCKED",
        "skill_root": str(root),
        "skill_count": len(skills),
        "skills": skills,
        "missing_skills": missing_skills,
        "unexpected_skills": unexpected_skills,
        "missing_entrypoints": missing_entrypoints,
        "invalid_entrypoints": invalid_entrypoints,
        "manifest_valid": manifest_valid,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()
        if manifest.is_file()
        else None,
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
