import json
import subprocess
from pathlib import Path

from github_ops.command import CommandResult
from github_ops.pr_create import create_pr_with_japanese_gate
from github_ops.result import Status


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40


class FakeRunner:
    def __init__(self, responses: list[CommandResult | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def run(self, argv, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append({"argv": list(argv), **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _body_file(tmp_path: Path, text: str = "## 概要\n安全なPR作成経路を追加します。") -> Path:
    path = tmp_path / "pr-body.md"
    path.write_text(text, encoding="utf-8")
    return path


def _kwargs(tmp_path: Path, **overrides):  # noqa: ANN003
    body_file = overrides.pop("body_file", None) or _body_file(tmp_path)
    payload = {
        "repo": "example-org/tooling",
        "base": "main",
        "head": "codex/gate",
        "repo_root": tmp_path,
        "account_map_file": FIXTURES / "account-map.valid.yaml",
        "expected_base_sha": BASE_SHA,
        "expected_head_sha": HEAD_SHA,
        "title": "PR日本語gateを追加",
        "body_file": body_file,
        "confirmed": True,
    }
    payload.update(overrides)
    return payload


def _preflight_ready() -> list[CommandResult]:
    repo_info = {
        "nameWithOwner": "example-org/tooling",
        "visibility": "PRIVATE",
        "viewerPermission": "ADMIN",
        "defaultBranchRef": {"name": "main"},
    }
    return [
        CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
        CommandResult(0, "example-user\n", ""),
        CommandResult(0, "", ""),
        CommandResult(0, f"{HEAD_SHA}\n", ""),
        CommandResult(0, f"{BASE_SHA}\n", ""),
        CommandResult(0, f"{HEAD_SHA}\trefs/heads/codex/gate\n", ""),
        CommandResult(0, json.dumps(repo_info), ""),
    ]


def _read_back(title: str, body: str, url: str) -> CommandResult:
    return CommandResult(
        0,
        json.dumps(
            {
                "url": url,
                "title": title,
                "body": body,
                "headRefName": "codex/gate",
                "headRefOid": HEAD_SHA,
                "baseRefName": "main",
            },
            ensure_ascii=False,
        ),
        "",
    )


def test_blocks_without_human_confirmation(tmp_path: Path) -> None:
    runner = FakeRunner([])
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, confirmed=False), runner=runner
    )
    assert outcome.code == "human_confirmation_required"
    assert runner.calls == []


def test_blocks_english_metadata_before_gh_call(tmp_path: Path) -> None:
    runner = FakeRunner([])
    outcome = create_pr_with_japanese_gate(
        **_kwargs(
            tmp_path,
            title="Add PR gate",
            body_file=_body_file(tmp_path, "## Summary\nAdd a gate."),
        ),
        runner=runner,
    )
    assert outcome.code == "title_not_japanese"
    assert runner.calls == []


def test_blocks_non_utf8_body_before_gh_call(tmp_path: Path) -> None:
    body_file = tmp_path / "pr-body.md"
    body_file.write_bytes(b"\xff\xfe")
    runner = FakeRunner([])
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, body_file=body_file), runner=runner
    )
    assert outcome.code == "body_file_unreadable"
    assert runner.calls == []


def test_blocks_when_identity_preflight_fails(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/tooling.git\n", ""),
            CommandResult(0, "wrong-user\n", ""),
        ]
    )
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.code == "active_login_mismatch"
    assert all(call["argv"][:3] != ["gh", "pr", "create"] for call in runner.calls)


def test_fork_qualified_head_is_blocked(tmp_path: Path) -> None:
    runner = FakeRunner([])
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, head="user:gate"), runner=runner
    )
    assert outcome.code == "fork_head_unsupported"
    assert runner.calls == []


def test_create_uses_validated_body_snapshot_and_verifies_read_back(tmp_path: Path) -> None:
    title = "PR日本語gateを追加"
    body_file = _body_file(tmp_path)
    body = body_file.read_text(encoding="utf-8")
    url = "https://github.com/example-org/tooling/pull/12"
    runner = FakeRunner(
        _preflight_ready()
        + [CommandResult(0, f"{url}\n", ""), _read_back(title, body, url)]
    )
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, title=title, body_file=body_file), runner=runner
    )
    assert outcome.status is Status.READY
    assert outcome.code == "pr_created_and_verified"
    create_call = runner.calls[-2]
    assert create_call["argv"][-2:] == ["--body-file", "-"]
    assert create_call["input_text"] == body
    assert runner.calls[-1]["argv"][:4] == ["gh", "pr", "view", url]
    assert runner.calls[-1]["redact_stdout"] is False


def test_token_shaped_literal_compares_before_output_redaction(tmp_path: Path) -> None:
    token_literal = "gh" + "p_" + "a" * 24
    body_file = _body_file(tmp_path, f"## 概要\n検査例は{token_literal}です。")
    body = body_file.read_text(encoding="utf-8")
    url = "https://github.com/example-org/tooling/pull/12"
    runner = FakeRunner(
        _preflight_ready()
        + [
            CommandResult(0, f"{url}\n", ""),
            _read_back("PR日本語gateを追加", body, url),
        ]
    )
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, body_file=body_file), runner=runner
    )
    assert outcome.status is Status.READY
    assert token_literal not in json.dumps(outcome.to_dict())


def test_read_back_timeout_returns_unknown_with_url(tmp_path: Path) -> None:
    url = "https://github.com/example-org/tooling/pull/12"
    runner = FakeRunner(
        _preflight_ready()
        + [
            CommandResult(0, f"{url}\n", ""),
            subprocess.TimeoutExpired(["gh", "pr", "view"], 15),
        ]
    )
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == "pr_read_back_timeout"
    assert outcome.evidence["url"] == url


def test_read_back_mismatch_is_unknown_without_edit(tmp_path: Path) -> None:
    body_file = _body_file(tmp_path)
    body = body_file.read_text(encoding="utf-8")
    url = "https://github.com/example-org/tooling/pull/12"
    runner = FakeRunner(
        _preflight_ready()
        + [CommandResult(0, f"{url}\n", ""), _read_back("Changed title", body, url)]
    )
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, body_file=body_file), runner=runner
    )
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == "pr_read_back_mismatch"
    assert len(runner.calls) == 9
