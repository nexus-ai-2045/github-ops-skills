from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.source_manifest import refresh_target_hashes, verify_target_hashes


def main() -> int:
    parser = argparse.ArgumentParser(description="source manifestのtarget hashを検証します")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.refresh:
        print(json.dumps({"status": "refreshed", "count": refresh_target_hashes(args.repo)}))
        return 0
    errors = verify_target_hashes(args.repo)
    print(json.dumps({"status": "ok" if not errors else "error", "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
