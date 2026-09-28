from __future__ import annotations

from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.cli import check_pr_japanese_main as main


if __name__ == "__main__":
    raise SystemExit(main())
