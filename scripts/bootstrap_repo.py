#!/usr/bin/env python3
"""新規 repository bootstrap の repository-root 入口。

実装の正本は skills/new-repo-bootstrap/scripts/bootstrap_repo.py (runtime copy 単体で動く)。
ここは同じ file を実行するだけで、ロジックを複製しない。
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "skills" / "new-repo-bootstrap" / "scripts" / "bootstrap_repo.py"

if __name__ == "__main__":
    sys.argv[0] = str(TARGET)
    runpy.run_path(str(TARGET), run_name="__main__")
