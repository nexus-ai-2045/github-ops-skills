"""identity guard は blob を読み切れなかったとき READY を返してはならない。

CommandRunner が timeout / 起動失敗を例外ではなく returncode で返すように
なった (PR #28) ため、`if blob.returncode != 0: continue` のままだと未検査の
blob を黙って skip し、公開ガードが identity_scan_ready を返しうる
(2026-09-12 Codex P1)。変更前は例外が伝播して偶然 fail-closed だった。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from github_ops.command import NOT_EXECUTED, TIMED_OUT, CommandResult  # noqa: E402
from github_ops.result import Status  # noqa: E402
from public_identity_guard import scan_git_tree  # noqa: E402


class _Runner:
    """ls-tree は 1 path を返し、その blob の git show が code で失敗する。"""

    def __init__(self, blob_code: int) -> None:
        self.blob_code = blob_code

    def run(self, argv, **kwargs):  # noqa: ANN001, ANN003
        if argv[:2] == ["git", "ls-tree"]:
            return CommandResult(0, "secrets.txt\n", "")
        assert argv[:2] == ["git", "show"], argv
        return CommandResult(self.blob_code, "", "command timed out")


@pytest.mark.parametrize("code", [TIMED_OUT, NOT_EXECUTED])
def test_unreadable_blob_makes_the_scan_unknown_not_ready(code: int) -> None:
    outcome = scan_git_tree(_Runner(code), Path("."), "HEAD")
    assert outcome.status is Status.UNKNOWN, outcome
    assert outcome.code == "identity_scan_incomplete"
    assert outcome.evidence["path"] == "secrets.txt"
    assert outcome.evidence["returncode"] == code
