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
        os_name: str = os.name,
    ) -> None:
        self._run_impl = run_impl
        self._os_name = os_name

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | str | None = None,
        input_text: str | None = None,
        redact_stdout: bool = True,
        scoped_env: Mapping[str, str] | None = None,
        unset_env: set[str] | None = None,
        timeout: float = 15,
    ) -> CommandResult:
        env = os.environ.copy()
        for name in unset_env or set():
            env.pop(name, None)
        if scoped_env:
            env.update(scoped_env)
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if self._os_name == "nt"
            else 0
        )
        completed = self._run_impl(
            list(argv),
            cwd=cwd,
            env=env,
            capture_output=True,
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
            creationflags=creationflags,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=(
                redact(completed.stdout or "")
                if redact_stdout
                else (completed.stdout or "")
            ),
            stderr=redact(completed.stderr or ""),
        )
