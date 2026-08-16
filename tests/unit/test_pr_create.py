import json
from pathlib import Path

from github_ops.command import CommandResult
from github_ops.pr_create import create_pr_with_japanese_gate
from github_ops.result import Status


class FakeRunner:
    def __init__(self, responses: list[CommandResult]) -> None:
        self.responses = responses
        self.calls: list[list[str]] = []

    def run(self, argv, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append(list(argv))
        return self.responses.pop(0)


def _body_file(tmp_path: Path, text: str = "## 概要\n安全なPR作成経路を追加します。") -> Path:
    path = tmp_path / "pr-body.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_blocks_without_human_confirmation(tmp_path: Path) -> None:
    runner = FakeRunner([])
    outcome = create_pr_with_japanese_gate(
        repo="owner/repo",
        base="main",
        head="codex/gate",
        title="PR日本語gateを追加",
        body_file=_body_file(tmp_path),
        confirmed=False,
        runner=runner,
    )
    assert outcome.code == "human_confirmation_required"
    assert runner.calls == []


def test_blocks_english_metadata_before_gh_call(tmp_path: Path) -> None:
    runner = FakeRunner([])
    outcome = create_pr_with_japanese_gate(
        repo="owner/repo",
        base="main",
        head="codex/gate",
        title="Add PR gate",
        body_file=_body_file(tmp_path, "## Summary\nAdd a gate."),
        confirmed=True,
        runner=runner,
    )
    assert outcome.code == "title_not_japanese"
    assert runner.calls == []


def test_blocks_non_utf8_body_before_gh_call(tmp_path: Path) -> None:
    body_file = tmp_path / "pr-body.md"
    body_file.write_bytes(b"\xff\xfe")
    runner = FakeRunner([])
    outcome = create_pr_with_japanese_gate(
        repo="owner/repo",
        base="main",
        head="codex/gate",
        title="PR日本語gateを追加",
        body_file=body_file,
        confirmed=True,
        runner=runner,
    )
    assert outcome.code == "body_file_unreadable"
    assert runner.calls == []


def test_create_uses_body_file_and_verifies_read_back(tmp_path: Path) -> None:
    title = "PR日本語gateを追加"
    body_file = _body_file(tmp_path)
    body = body_file.read_text(encoding="utf-8")
    url = "https://github.com/owner/repo/pull/12"
    runner = FakeRunner(
        [
            CommandResult(0, f"{url}\n", ""),
            CommandResult(
                0,
                json.dumps(
                    {
                        "url": url,
                        "title": title,
                        "body": body,
                        "headRefName": "codex/gate",
                        "baseRefName": "main",
                    },
                    ensure_ascii=False,
                ),
                "",
            ),
        ]
    )
    outcome = create_pr_with_japanese_gate(
        repo="owner/repo",
        base="main",
        head="codex/gate",
        title=title,
        body_file=body_file,
        confirmed=True,
        runner=runner,
    )
    assert outcome.status is Status.READY
    assert outcome.code == "pr_created_and_verified"
    assert "--body-file" in runner.calls[0]
    assert "--body" not in runner.calls[0]
    assert runner.calls[1][:4] == ["gh", "pr", "view", url]


def test_read_back_mismatch_is_unknown_without_edit(tmp_path: Path) -> None:
    title = "PR日本語gateを追加"
    body_file = _body_file(tmp_path)
    url = "https://github.com/owner/repo/pull/12"
    runner = FakeRunner(
        [
            CommandResult(0, f"{url}\n", ""),
            CommandResult(
                0,
                json.dumps(
                    {
                        "url": url,
                        "title": "Changed title",
                        "body": body_file.read_text(encoding="utf-8"),
                        "headRefName": "codex/gate",
                        "baseRefName": "main",
                    }
                ),
                "",
            ),
        ]
    )
    outcome = create_pr_with_japanese_gate(
        repo="owner/repo",
        base="main",
        head="codex/gate",
        title=title,
        body_file=body_file,
        confirmed=True,
        runner=runner,
    )
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == "pr_read_back_mismatch"
    assert len(runner.calls) == 2
