import json
import subprocess
from pathlib import Path

import pytest

from github_ops.command import CommandFailure, CommandResult
from github_ops.pr_create import _verify_content, create_pr_with_japanese_gate
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
        if argv[:2] == ["git", "merge-base"]:
            return CommandResult(0, "c" * 40 + "\n", "")
        if argv[:2] == ["git", "merge-tree"]:
            return CommandResult(0, "d" * 40 + "\n", "")
        if argv[:2] == ["git", "rev-parse"] and argv[-1].endswith("^{tree}"):
            return CommandResult(0, "e" * 40 + "\n", "")
        if argv[:2] == ["git", "diff"]:
            return CommandResult(0, "README.md\0", "")
        if argv[:3] == ["git", "--literal-pathspecs", "ls-tree"]:
            oid = "f" * 40 if argv[4] == HEAD_SHA else "e" * 40
            return CommandResult(0, f"100644 blob {oid}\tREADME.md\0", "")
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
                "baseRefOid": BASE_SHA,
                "isDraft": False,
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
    assert create_call["argv"][create_call["argv"].index("--repo") + 1] == (
        "github.com/example-org/tooling"
    )
    assert create_call["input_text"] == body
    assert create_call["scoped_env"] == {"GH_HOST": "github.com"}
    assert runner.calls[-1]["argv"][:4] == ["gh", "pr", "view", url]
    assert runner.calls[-1]["redact_stdout"] is False
    assert runner.calls[-1]["scoped_env"] == {"GH_HOST": "github.com"}
    assert runner.calls[-1]["argv"][runner.calls[-1]["argv"].index("--repo") + 1] == (
        "github.com/example-org/tooling"
    )


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
            CommandResult(1, "", "command timed out", CommandFailure.TIMED_OUT),
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
    assert len(runner.calls) == 17


def test_origin_repository_must_match_repo_argument(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            CommandResult(0, "https://github.com/example-org/other.git\n", ""),
            CommandResult(0, "https://github.com/example-org/other.git\n", ""),
            CommandResult(0, "example-user\n", ""),
        ]
    )
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.code == "remote_repository_mismatch"
    assert all(call["argv"][:3] != ["gh", "pr", "create"] for call in runner.calls)


def test_failed_create_is_unknown_and_must_not_be_retried(tmp_path: Path) -> None:
    runner = FakeRunner(_preflight_ready() + [CommandResult(1, "", "network lost")])
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == "pr_create_indeterminate"
    assert outcome.evidence["head"] == "codex/gate"


def test_explicit_public_visibility_is_supported(tmp_path: Path) -> None:
    responses = _preflight_ready()
    repo_info = json.loads(responses[-1].stdout)
    repo_info["visibility"] = "PUBLIC"
    responses[-1] = CommandResult(0, json.dumps(repo_info), "")
    body = _body_file(tmp_path).read_text(encoding="utf-8")
    url = "https://github.com/example-org/tooling/pull/12"
    runner = FakeRunner(
        responses
        + [
            CommandResult(0, f"{url}\n", ""),
            _read_back("PR日本語gateを追加", body, url),
        ]
    )
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, expected_visibility="PUBLIC"), runner=runner
    )
    assert outcome.status is Status.READY


def test_invalid_expected_visibility_is_blocked_before_commands(tmp_path: Path) -> None:
    runner = FakeRunner([])
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, expected_visibility="UNKNOWN"), runner=runner
    )
    assert outcome.code == "expected_visibility_invalid"
    assert runner.calls == []


def test_live_remote_base_mismatch_is_blocked(tmp_path: Path) -> None:
    responses = _preflight_ready()
    responses[5] = CommandResult(0, f"{'c' * 40}\trefs/heads/main\n", "")
    runner = FakeRunner(responses)
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.code == "pr_preflight_mismatch"


def test_read_back_base_sha_mismatch_is_unknown(tmp_path: Path) -> None:
    body_file = _body_file(tmp_path)
    body = body_file.read_text(encoding="utf-8")
    url = "https://github.com/example-org/tooling/pull/12"
    read_back = _read_back("PR日本語gateを追加", body, url)
    payload = json.loads(read_back.stdout)
    payload["baseRefOid"] = "c" * 40
    runner = FakeRunner(
        _preflight_ready()
        + [CommandResult(0, f"{url}\n", ""), CommandResult(0, json.dumps(payload), "")]
    )
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, body_file=body_file), runner=runner
    )
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == "pr_read_back_mismatch"


def test_non_default_base_branch_is_supported(tmp_path: Path) -> None:
    responses = _preflight_ready()
    responses[5] = CommandResult(0, f"{BASE_SHA}\trefs/heads/develop\n", "")
    body = _body_file(tmp_path).read_text(encoding="utf-8")
    url = "https://github.com/example-org/tooling/pull/12"
    read_back = _read_back("PR日本語gateを追加", body, url)
    payload = json.loads(read_back.stdout)
    payload["baseRefName"] = "develop"
    runner = FakeRunner(
        responses
        + [CommandResult(0, f"{url}\n", ""), CommandResult(0, json.dumps(payload), "")]
    )
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, base="develop"), runner=runner
    )
    assert outcome.status is Status.READY


def test_conflicting_github_host_is_blocked_before_commands(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GH_HOST", "enterprise.example.com")
    runner = FakeRunner([])
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.code == "github_host_mismatch"
    assert runner.calls == []


def test_read_back_os_error_returns_unknown_with_url(tmp_path: Path) -> None:
    url = "https://github.com/example-org/tooling/pull/12"
    runner = FakeRunner(
        _preflight_ready()
        + [
            CommandResult(0, f"{url}\n", ""),
            CommandResult(1, "", "spawn failed", CommandFailure.EXECUTION_FAILED),
        ]
    )
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == "pr_read_back_execution_failed"
    assert outcome.evidence["url"] == url


def test_create_os_error_returns_unknown_without_retry(tmp_path: Path) -> None:
    runner = FakeRunner(
        _preflight_ready()
        + [CommandResult(1, "", "spawn failed", CommandFailure.EXECUTION_FAILED)]
    )
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == "pr_create_execution_failed"
    assert outcome.evidence["head"] == "codex/gate"


def test_requested_draft_state_is_verified(tmp_path: Path) -> None:
    body = _body_file(tmp_path).read_text(encoding="utf-8")
    url = "https://github.com/example-org/tooling/pull/12"
    runner = FakeRunner(
        _preflight_ready()
        + [CommandResult(0, f"{url}\n", ""), _read_back("PR日本語gateを追加", body, url)]
    )
    outcome = create_pr_with_japanese_gate(
        **_kwargs(tmp_path, draft=True), runner=runner
    )
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == "pr_read_back_mismatch"


@pytest.mark.parametrize("exit_code", [124, 127])
@pytest.mark.parametrize("stage", ["create", "read_back"])
def test_real_exit_codes_remain_indeterminate_without_retry(
    tmp_path: Path, exit_code: int, stage: str
) -> None:
    url = "https://github.com/example-org/tooling/pull/12"
    responses = _preflight_ready()
    if stage == "read_back":
        responses.append(CommandResult(0, url, ""))
    responses.append(CommandResult(exit_code, "", "child failed"))
    runner = FakeRunner(responses)
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == (
        "pr_create_indeterminate" if stage == "create" else "pr_read_back_failed"
    )
    assert sum(call["argv"][1:3] == ["pr", "create"] for call in runner.calls) == 1
    assert not runner.responses


@pytest.mark.parametrize("stage", ["create", "read_back"])
@pytest.mark.parametrize("raw_exception", [False, True])
def test_timeout_stays_distinct_and_never_retries(
    tmp_path: Path, stage: str, raw_exception: bool
) -> None:
    url = "https://github.com/example-org/tooling/pull/12"
    token = "gh" + "p_" + "a" * 24
    responses = _preflight_ready()
    if stage == "read_back":
        responses.append(CommandResult(0, url, ""))
    responses.append(
        subprocess.TimeoutExpired(["gh", token], 1, output=token, stderr=token)
        if raw_exception
        else CommandResult(1, "", "command timed out", CommandFailure.TIMED_OUT)
    )
    runner = FakeRunner(responses)
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == f"pr_{stage}_timeout"
    assert token not in outcome.to_json()
    assert "再作成せず" in outcome.recovery
    if stage == "read_back":
        assert outcome.evidence["url"] == url
    assert sum(call["argv"][1:3] == ["pr", "create"] for call in runner.calls) == 1
    assert not runner.responses


@pytest.mark.parametrize("stage", ["create", "read_back"])
def test_injected_execution_exception_redacts_evidence(tmp_path: Path, stage: str) -> None:
    url = "https://github.com/example-org/tooling/pull/12"
    token = "gh" + "p_" + "a" * 24
    responses = _preflight_ready()
    if stage == "read_back":
        responses.append(CommandResult(0, url, ""))
    responses.append(subprocess.SubprocessError(token))
    runner = FakeRunner(responses)
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == f"pr_{stage}_execution_failed"
    assert token not in outcome.to_json()
    assert "再作成せず" in outcome.recovery
    assert sum(call["argv"][1:3] == ["pr", "create"] for call in runner.calls) == 1


def test_raw_timeout_from_injected_runner_is_still_a_timeout(tmp_path: Path) -> None:
    """差し替えた runner が生の TimeoutExpired を投げても timeout に写すこと。

    TimeoutExpired は SubprocessError の subclass なので、広い except が先に
    受けると pr_create_execution_failed に潰れる (2026-09-12 Codex P2)。
    """
    runner = FakeRunner(
        _preflight_ready() + [subprocess.TimeoutExpired(["gh", "pr", "create"], 60)]
    )
    outcome = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert outcome.status is Status.UNKNOWN
    assert outcome.code == "pr_create_timeout"


def test_raw_read_back_timeout_from_injected_runner_is_still_a_timeout(
    tmp_path: Path,
) -> None:
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


@pytest.mark.parametrize(
    "purpose,code",
    [("resident_adaptation", "resident_adaptation_not_publishable"),
     ("guess", "branch_purpose_invalid")],
)
def test_branch_purpose_blocks_before_external_calls(tmp_path, purpose, code):
    runner = FakeRunner([])
    result = create_pr_with_japanese_gate(**_kwargs(tmp_path, branch_purpose=purpose), runner=runner)
    assert result.code == code
    assert runner.calls == []


def _git_fixture(tmp_path, object_format="sha1"):
    from github_ops.command import CommandRunner
    root = tmp_path / "fixture"
    root.mkdir()
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    git("init", "-q", "-b", "main", f"--object-format={object_format}")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (root / "README.md").write_text("one\ntwo\nthree\nfour\nfive\n")
    (root / "feature.txt").write_text("old\n")
    git("add", ".")
    git("commit", "-qm", "Initial")
    initial = git("rev-parse", "HEAD")
    def commit(name):
        git("add", ".")
        git("commit", "-qm", name)
        return git("rev-parse", "HEAD")
    def check(base, head):
        before = git("show-ref")
        status = git("status", "--porcelain")
        result = _verify_content(repo_root=root, base_sha=base, head_sha=head, runner=CommandRunner())
        assert git("show-ref") == before
        assert git("status", "--porcelain") == status
        return result
    return root, git, initial, commit, check


def test_real_git_unique_readme_with_unrelated_new_base_file_passes(tmp_path):
    root, git, initial, commit, check = _git_fixture(tmp_path)
    (root / "new-base.txt").write_text("preserve\n")
    base = commit("Base addition")
    git("checkout", "-q", "-b", "development", initial)
    with (root / "README.md").open("a") as file:
        file.write("Unique example\n")
    head = commit("Example")
    assert check(base, head).code == "content_unique"


def test_real_git_adopted_old_baseline_preserves_new_base_file(tmp_path):
    root, git, initial, commit, check = _git_fixture(tmp_path)
    (root / "feature.txt").write_text("adopted\n")
    base_feature = commit("Adopt feature")
    (root / "new-base.txt").write_text("preserve\n")
    base = commit("New base feature")
    git("checkout", "-q", "-b", "adaptation", initial)
    (root / "feature.txt").write_text("adopted\n")
    head = commit("Same feature different history")
    assert head != base_feature
    assert check(base, head).code == "content_already_adopted"
    assert check(base, base).code == "content_already_adopted"


def test_real_git_partial_adoption_stops(tmp_path):
    root, git, initial, commit, check = _git_fixture(tmp_path)
    (root / "feature.txt").write_text("adopted\n")
    base = commit("Adopt feature")
    git("checkout", "-q", "-b", "development", initial)
    (root / "feature.txt").write_text("adopted\n")
    (root / "unique.txt").write_text("new\n")
    head = commit("Partial adoption and unique")
    assert check(base, head).code == "content_adoption_review_required"


def test_real_git_same_file_clean_overlap_stops(tmp_path):
    root, git, initial, commit, check = _git_fixture(tmp_path)
    (root / "README.md").write_text("adopted\ntwo\nthree\nfour\nfive\n")
    base = commit("Base edits first line")
    git("checkout", "-q", "-b", "development", initial)
    (root / "README.md").write_text("one\ntwo\nthree\nfour\nunique\n")
    head = commit("Head edits last line")
    assert check(base, head).code == "content_adoption_review_required"


def test_real_git_conflicting_or_missing_objects_stops(tmp_path):
    root, git, initial, commit, check = _git_fixture(tmp_path)
    (root / "feature.txt").write_text("base\n")
    base = commit("Base conflict")
    git("checkout", "-q", "-b", "development", initial)
    (root / "feature.txt").write_text("head\n")
    head = commit("Head conflict")
    assert check(base, head).status is Status.UNKNOWN
    assert check("0" * 40, head).status is Status.UNKNOWN


def test_adopted_content_blocks_create_after_preflight(tmp_path):
    class AdoptedRunner(FakeRunner):
        def run(self, argv, **kwargs):
            if argv[:2] == ["git", "merge-tree"]:
                self.calls.append({"argv": list(argv), **kwargs})
                return CommandResult(0, "e" * 40 + "\n", "")
            return super().run(argv, **kwargs)
    runner = AdoptedRunner(_preflight_ready())
    result = create_pr_with_japanese_gate(**_kwargs(tmp_path), runner=runner)
    assert result.code == "content_already_adopted"
    assert not runner.responses
    assert not any(call["argv"][:3] == ["gh", "pr", "create"] for call in runner.calls)


def test_real_git_literal_glob_filename_is_not_other_path(tmp_path):
    root, git, initial, commit, check = _git_fixture(tmp_path)
    (root / "feature.txt").write_text("base\n")
    base = commit("Change existing")
    git("checkout", "-q", "-b", "development", initial)
    (root / "*.txt").write_text("unique literal path\n")
    head = commit("Add literal glob filename")
    assert check(base, head).code == "content_unique"


@pytest.mark.parametrize("path", ["bad\rname.txt", "bad\nname.txt", "bad\ufffdname.txt"])
def test_real_git_unreliable_text_path_stops(tmp_path, path):
    root, git, initial, commit, check = _git_fixture(tmp_path)
    (root / path).write_text("unique\n")
    head = commit("Add unusual path")
    assert check(initial, head).code == "content_evidence_invalid"


@pytest.mark.parametrize("command,output", [
    ("merge-base", "garbage\n"),
    ("merge-tree", "garbage\n"),
    ("rev-parse", "garbage\n"),
    ("diff", "README.md"),
    ("diff", "README.md\0README.md\0"),
    ("diff", "README.md\0\0"),
    ("ls-tree", "garbage\0"),
    ("ls-tree", "100644 blob " + "f" * 40 + "\twrong.txt\0"),
    ("ls-tree", "100644 blob " + "f" * 40 + "\tREADME.md"),
    ("ls-tree", "100644 blob " + "f" * 40 + "\tREADME.md\0" * 2),
    ("ls-tree", "100644 tree " + "f" * 40 + "\tREADME.md\0"),
    ("ls-tree", "100600 blob " + "f" * 40 + "\tREADME.md\0"),
    ("ls-tree", "100644 blob malformed\tREADME.md\0"),
    ("ls-tree", ""),
])
def test_malformed_success_never_passes_content_gate(tmp_path, command, output):
    class MalformedRunner(FakeRunner):
        def run(self, argv, **kwargs):
            if command in argv[:3]:
                return CommandResult(0, output, "")
            return super().run(argv, **kwargs)
    result = _verify_content(repo_root=tmp_path, base_sha=BASE_SHA,
                             head_sha=HEAD_SHA, runner=MalformedRunner([]))
    assert result.status is Status.UNKNOWN


@pytest.mark.parametrize("oid", ["-invalid", "a" * 39, "z" * 40])
def test_invalid_fixed_oid_runs_no_commands(tmp_path, oid):
    runner = FakeRunner([])
    result = _verify_content(repo_root=tmp_path, base_sha=oid,
                             head_sha=HEAD_SHA, runner=runner)
    assert result.code == "content_evidence_invalid"
    assert runner.calls == []


def test_real_git_sha256_unique_change_passes(tmp_path):
    root, git, initial, commit, check = _git_fixture(tmp_path, "sha256")
    (root / "unique.txt").write_text("unique\n")
    head = commit("Unique SHA256 change")
    assert len(head) == 64
    assert check(initial, head).code == "content_unique"


@pytest.mark.parametrize("command", ["merge-base", "rev-parse", "merge-tree", "diff", "ls-tree"])
def test_failure_field_even_zero_status_stops(tmp_path, command):
    class FailureRunner(FakeRunner):
        def run(self, argv, **kwargs):
            if command in argv[:3]:
                return CommandResult(0, "", "", CommandFailure.EXECUTION_FAILED)
            return super().run(argv, **kwargs)
    result = _verify_content(repo_root=tmp_path, base_sha=BASE_SHA,
                             head_sha=HEAD_SHA, runner=FailureRunner([]))
    assert result.status is Status.UNKNOWN
