from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .redaction import redact


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def __init__(
        self,
        *,
        run_impl: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._run_impl = run_impl

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | str | None = None,
        scoped_env: Mapping[str, str] | None = None,
        timeout: float = 15,
    ) -> CommandResult:
        env = os.environ.copy()
        if scoped_env:
            env.update(scoped_env)
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        )
        completed = self._run_impl(
            list(argv),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            creationflags=creationflags,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=redact(completed.stdout or ""),
            stderr=redact(completed.stderr or ""),
        )
