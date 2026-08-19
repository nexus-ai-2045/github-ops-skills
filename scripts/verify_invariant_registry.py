from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_IDS = {
    "GHO-TYPE-001",
    "GHO-ID-001",
    "GHO-ID-002",
    "GHO-PATH-001",
    "GHO-PROV-001",
}
ALLOWED_ENFORCEMENT = {"test", "ci"}


def verify(repo: Path) -> list[str]:
    payload = json.loads((repo / "policy" / "invariants.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("schema_version") != "github-ops/invariants/v1":
        errors.append("invalid schema_version")
    items = payload.get("invariants")
    if not isinstance(items, list) or not items:
        return errors + ["invariants must be a non-empty list"]
    seen: set[str] = set()
    for item in items:
        identifier = item.get("id") if isinstance(item, dict) else None
        if not isinstance(identifier, str) or not identifier:
            errors.append("invariant id is required")
            continue
        if identifier in seen:
            errors.append(f"duplicate invariant id: {identifier}")
        seen.add(identifier)
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"title missing: {identifier}")
        if item.get("enforcement") not in ALLOWED_ENFORCEMENT:
            errors.append(f"invalid enforcement: {identifier}")
        paths = item.get("test_paths")
        if not isinstance(paths, list) or not paths:
            errors.append(f"test_paths missing: {identifier}")
            continue
        for relative in paths:
            if not isinstance(relative, str):
                errors.append(f"test path missing: {identifier}:{relative}")
                continue
            relative_path = Path(relative)
            candidate = (repo / relative_path).resolve()
            try:
                candidate.relative_to(repo.resolve())
            except ValueError:
                errors.append(f"test path escapes repository: {identifier}:{relative}")
                continue
            if relative_path.is_absolute() or ".." in relative_path.parts or not candidate.is_file():
                errors.append(f"test path missing: {identifier}:{relative}")
    for missing in sorted(REQUIRED_IDS - seen):
        errors.append(f"required invariant missing: {missing}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    errors = verify(args.repo)
    print(json.dumps({"status": "ok" if not errors else "error", "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
