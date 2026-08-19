from __future__ import annotations

import argparse
import json
from pathlib import Path


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
        paths = item.get("test_paths")
        if not isinstance(paths, list) or not paths:
            errors.append(f"test_paths missing: {identifier}")
            continue
        for relative in paths:
            if not isinstance(relative, str) or not (repo / relative).is_file():
                errors.append(f"test path missing: {identifier}:{relative}")
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
