from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .redaction import redact


class CommandFailure(str, Enum):
    TIMED_OUT = "timed_out"
    EXECUTION_FAILED = "execution_failed"


@dataclass(frozen=True)
class CommandResult:
    # failure がある場合は既存の非ゼロ検査用に 1 を返す。
    # 実プロセスの終了値と例外の区分は failure で区別する。
    returncode: int
    stdout: str
    stderr: str
    failure: CommandFailure | None = None


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
            # 部分出力にはsecretが含まれ得るので、例外本文・出力を持ち出さない。
            # PR作成が済んでいる可能性を、実プロセスの終了値と分離して返す。
            return CommandResult(
                returncode=1,
                stdout="",
                stderr="command timed out",
                failure=CommandFailure.TIMED_OUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            # 起動・通信などの失敗をJSON契約へ戻す。子プロセスや外部操作が
            # 未実行だったとは断定しない。
            return CommandResult(
                returncode=1,
                stdout="",
                stderr=redact(f"{type(exc).__name__}: {exc}"),
                failure=CommandFailure.EXECUTION_FAILED,
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
