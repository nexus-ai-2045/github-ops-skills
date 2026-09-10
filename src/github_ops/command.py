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


# 子プロセスが「起動できなかった」/「時間切れ」を returncode で区別する。
# 呼び出し側はこの 2 つを別の所見に写す (pr create の timeout は
# 「PR が作られた可能性がある」ので再作成させない)。shell の慣例値に合わせた。
TIMED_OUT = 124
NOT_EXECUTED = 127


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
        try:
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
        except subprocess.TimeoutExpired:
            # timeout と「起動できなかった」は呼び出し側で意味が違う。
            # pr create では timeout は「PR が作られた可能性がある」ので
            # 再作成させてはならない。潰さずに区別できる形で返す。
            # 124 / 127 は shell の慣例値に合わせた。
            return CommandResult(
                returncode=124,
                stdout="",
                stderr="command timed out",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            # 実行ファイル不在・cwd 不在など。subprocess は returncode を返す前に
            # 投げるため、握らないと --json 契約の CLI が stdout 0 バイトの
            # traceback で死ぬ (実測: gh_identity_probe.py --repo . --json)。
            return CommandResult(
                returncode=127,
                stdout="",
                stderr=redact(f"{type(exc).__name__}: {exc}"),
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
