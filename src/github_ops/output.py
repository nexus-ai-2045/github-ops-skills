from __future__ import annotations

import sys


def configure_utf8_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "")
    if callable(reconfigure) and encoding != "utf8":
        reconfigure(encoding="utf-8")
