from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def verify(repo: Path) -> dict[str, object]:
    root = (repo / "skills").resolve()
    manifest = (repo / "migration" / "source-manifest.json").resolve()
    skills = sorted(path.name for path in root.iterdir() if path.is_dir())
    return {
        "status": "READY" if len(skills) == 7 and manifest.is_file() else "BLOCKED",
        "skill_root": str(root),
        "skill_count": len(skills),
        "skills": skills,
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
