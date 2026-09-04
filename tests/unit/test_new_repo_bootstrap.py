"""new-repo-bootstrap: 新規 repository の作成を 1 本の fail-closed 手順にまとめる script のテスト。

runner を差し替えて git / gh を呼ばずに検査する。token は出力へ出ない。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/new-repo-bootstrap/scripts/bootstrap_repo.py"
)
TOKEN = "gho_" + "x" * 36
OWNER = "nexus-ai-2045"
NEXUS_EMAIL = "273569186+nexus-ai-2045@users.noreply.github.com"


def _load_module():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("new_repo_bootstrap", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass の遅延 annotation 解決に必要
    spec.loader.exec_module(module)
    return module


class FakeRunner:
    """argv の先頭一致で応答を返す。呼び出しと scoped_env を記録する。"""

    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str, str]]) -> None:
        self.responses = responses
        self.calls: list[tuple[tuple[str, ...], dict]] = []

    def run(self, argv, *, cwd=None, scoped_env=None, timeout=30):  # noqa: ANN001
        argv = tuple(argv)
        self.calls.append((argv, {"cwd": cwd, "scoped_env": dict(scoped_env or {})}))
        for prefix, response in self.responses.items():
            if argv[: len(prefix)] == prefix:
                return response
        return (0, "", "")

    def called(self, *prefix: str) -> list[tuple[tuple[str, ...], dict]]:
        return [call for call in self.calls if call[0][: len(prefix)] == prefix]


def _happy_responses(repo_dir: Path) -> dict:
    return {
        ("gh", "auth", "token"): (0, TOKEN + "\n", ""),
        ("gh", "api", "user"): (0, OWNER + "\n", ""),
        ("gh", "repo", "view"): (1, "", "GraphQL: Could not resolve to a Repository"),
        ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
        ("git", "remote", "get-url", "origin"): (1, "", "error: No such remote"),
        ("git", "log", "--format=%an|%ae"): (0, "", ""),
        ("git", "rev-list", "--count", "HEAD"): (1, "", "fatal: bad revision"),
        ("git", "status", "--porcelain"): (0, "", ""),
    }


def _created(visibility: str) -> dict:
    """create_remote 後の read-back 応答 (gh api repos/<nwo>)。"""
    return {("gh", "api", f"repos/{OWNER}/demo"): (0, json.dumps({"full_name": f"{OWNER}/demo", "visibility": visibility}), "")}


@pytest.fixture
def module():  # noqa: ANN201
    return _load_module()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "Projects" / "Documents" / ".repos" / "nexus_ai").mkdir(parents=True)
    return tmp_path


def test_default_local_root_depends_on_visibility_and_env(module, home) -> None:
    public = module.default_local_root(home, "public", {})
    private = module.default_local_root(home, "private", {})
    assert public == home / "Projects/Documents/.repos/nexus_ai"
    assert private == home / "Projects/Documents/.repos/nexus_ai/private"
    custom = module.default_local_root(home, "public", {"GITHUB_OPS_REPO_ROOT": str(home / "elsewhere")})
    assert custom == home / "elsewhere"


def test_build_plan_uses_nexus_identity_and_rejects_unknown_owner_without_identity(module, home) -> None:
    plan = module.build_plan(owner=OWNER, name="demo", visibility="public", description="d", home=home, env={})
    assert plan.repo_dir == home / "Projects/Documents/.repos/nexus_ai/demo"
    assert (plan.commit_name, plan.commit_email) == ("nexus_ai", NEXUS_EMAIL)
    with pytest.raises(module.BootstrapError):
        module.build_plan(owner="someone-else", name="demo", visibility="public", description="d", home=home, env={})
    other = module.build_plan(
        owner="someone-else", name="demo", visibility="private", description="d", home=home, env={},
        commit_name="Some One", commit_email="s@example.com",
    )
    assert other.commit_name == "Some One"


def test_build_plan_rejects_bad_names(module, home) -> None:
    for bad in ("", "with space", "../escape", "a/b"):
        with pytest.raises(module.BootstrapError):
            module.build_plan(owner=OWNER, name=bad, visibility="public", description="d", home=home, env={})


def test_preflight_ready_when_token_matches_and_remote_absent(module, home) -> None:
    plan = module.build_plan(owner=OWNER, name="demo", visibility="public", description="d", home=home, env={})
    runner = FakeRunner(_happy_responses(plan.repo_dir))
    result = module.Bootstrapper(plan, runner, today=date(2026, 9, 5)).preflight()
    assert result["status"] == "READY"
    assert result["checks"]["token_login"] == "ok"
    assert result["checks"]["remote_absent"] == "ok"
    assert result["checks"]["local_dir"] == "absent"
    api_calls = runner.called("gh", "api", "user")
    assert api_calls and api_calls[0][1]["scoped_env"]["GH_TOKEN"] == TOKEN
    assert TOKEN not in json.dumps(result)


def test_preflight_blocks_on_token_login_mismatch(module, home) -> None:
    plan = module.build_plan(owner=OWNER, name="demo", visibility="public", description="d", home=home, env={})
    responses = _happy_responses(plan.repo_dir)
    responses[("gh", "api", "user")] = (0, "someone-else\n", "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=date(2026, 9, 5)).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["token_login"] == "mismatch"
    assert TOKEN not in json.dumps(result)


def test_preflight_blocks_when_remote_already_exists_or_origin_configured(module, home) -> None:
    plan = module.build_plan(owner=OWNER, name="demo", visibility="public", description="d", home=home, env={})
    responses = _happy_responses(plan.repo_dir)
    responses[("gh", "repo", "view")] = (0, '{"nameWithOwner":"nexus-ai-2045/demo"}', "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=date(2026, 9, 5)).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["remote_absent"] == "exists"

    plan.repo_dir.mkdir(parents=True)
    responses = _happy_responses(plan.repo_dir)
    responses[("git", "remote", "get-url", "origin")] = (0, "https://github.com/x/y.git\n", "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=date(2026, 9, 5)).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["local_dir"] == "has_origin"


def test_preflight_blocks_when_existing_commits_have_other_identity(module, home) -> None:
    plan = module.build_plan(owner=OWNER, name="demo", visibility="public", description="d", home=home, env={})
    plan.repo_dir.mkdir(parents=True)
    responses = _happy_responses(plan.repo_dir)
    responses[("git", "log", "--format=%an|%ae")] = (0, "Personal Name|me@example.com\n", "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=date(2026, 9, 5)).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["commit_identity"] == "mismatch"


def test_render_templates_and_scaffold_never_overwrites(module, home) -> None:
    plan = module.build_plan(owner=OWNER, name="demo", visibility="public", description="デモ", home=home, env={})
    templates = module.render_templates(plan, today=date(2026, 9, 5))
    assert set(templates) == {"LICENSE", "README.md", "SECURITY.md", "PREFLIGHT.md", "CONTRIBUTING.md", ".gitignore"}
    assert "Copyright (c) 2026 nexus_ai" in templates["LICENSE"]
    assert "repo-preflight:review-record" in templates["PREFLIGHT.md"]
    assert "デモ" in templates["README.md"]
    plan.repo_dir.mkdir(parents=True)
    (plan.repo_dir / "README.md").write_text("mine", encoding="utf-8")
    written = module.scaffold_docs(plan, today=date(2026, 9, 5))
    assert "README.md" not in written and "LICENSE" in written
    assert (plan.repo_dir / "README.md").read_text(encoding="utf-8") == "mine"
    assert str(home) not in (plan.repo_dir / "PREFLIGHT.md").read_text(encoding="utf-8")


def test_registry_row_inserts_before_anchor_and_uses_tilde_path(module, home) -> None:
    plan = module.build_plan(owner=OWNER, name="demo", visibility="public", description="デモ", home=home, env={})
    row = module.registry_row(plan, today=date(2026, 9, 5))
    assert row.startswith("| `nexus-ai-2045/demo`（デモ） | public | **nexus-ai-2045** |")
    assert "~/Projects/Documents/.repos/nexus_ai/demo" in row and str(home) not in row
    text = "| a | b | c | d |\n| 公開協業 repo 全般 | - | x | y |\n\nrest\n"
    updated = module.insert_registry_row(text, row)
    assert updated is not None and updated.index(row) < updated.index("| 公開協業 repo 全般")
    assert module.insert_registry_row("no anchor here\n", row) is None
    assert module.insert_registry_row(updated, row) == updated  # 二重登録しない


def test_execute_runs_steps_in_order_and_scopes_token(module, home, tmp_path) -> None:
    registry = tmp_path / "map.md"
    registry.write_text("| a | b | c | d |\n| 公開協業 repo 全般 | - | x | y |\n", encoding="utf-8")
    wrapper = tmp_path / "push.sh"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    preflight = tmp_path / "readiness_scan.py"
    preflight.write_text("", encoding="utf-8")
    plan = module.build_plan(
        owner=OWNER, name="demo", visibility="public", description="デモ", home=home, env={},
        registry_file=registry, push_wrapper=wrapper, preflight_script=preflight,
    )
    responses = _happy_responses(plan.repo_dir)
    scan = {"status": "pass", "checks": {k: {"status": "pass"} for k in
            ("required_documents", "secret_scan", "personal_path_scan", "commit_identity")}}
    responses[("python3", str(preflight))] = (0, json.dumps(scan), "")
    responses[("gh", "repo", "create")] = (0, "https://github.com/nexus-ai-2045/demo\n", "")
    responses[("bash", str(wrapper))] = (0, "pushed\n", "")
    responses[("gh", "api", "-X", "PATCH")] = (0, "{}", "")
    responses[("gh", "api", "-X", "PUT")] = (0, "", "")
    responses.update(_created("public"))
    runner = FakeRunner(responses)
    report = module.Bootstrapper(plan, runner, today=date(2026, 9, 5)).execute()

    assert report["status"] == "READY", report
    names = [step["name"] for step in report["steps"]]
    assert names == ["preflight", "prepare_local", "set_identity", "scaffold_docs", "initial_commit",
                     "readiness_scan", "create_remote", "add_remote", "push", "lockdown", "register", "verify"]
    assert all(step["status"] in {"ok", "skipped"} for step in report["steps"])
    create = runner.called("gh", "repo", "create")[0]
    assert create[0][:5] == ("gh", "repo", "create", "nexus-ai-2045/demo", "--public")
    assert create[1]["scoped_env"]["GH_TOKEN"] == TOKEN
    assert runner.called("git", "init", "-b", "main")
    assert runner.called("git", "config", "user.name", "nexus_ai")
    assert runner.called("git", "remote", "add", "origin", "https://github.com/nexus-ai-2045/demo.git")
    assert runner.called("bash", str(wrapper))
    assert not runner.called("git", "push")
    assert "private-vulnerability-reporting" in " ".join(runner.called("gh", "api", "-X", "PUT")[0][0])
    assert "nexus-ai-2045/demo" in registry.read_text(encoding="utf-8")
    assert TOKEN not in json.dumps(report)


def test_execute_stops_at_readiness_scan_failure_before_creating_remote(module, home, tmp_path) -> None:
    preflight = tmp_path / "readiness_scan.py"
    preflight.write_text("", encoding="utf-8")
    plan = module.build_plan(owner=OWNER, name="demo", visibility="public", description="デモ", home=home, env={},
                             preflight_script=preflight)
    responses = _happy_responses(plan.repo_dir)
    scan = {"status": "blocked", "checks": {"required_documents": {"status": "pass"}, "secret_scan": {"status": "fail"},
                                             "personal_path_scan": {"status": "pass"}, "commit_identity": {"status": "pass"}}}
    responses[("python3", str(preflight))] = (0, json.dumps(scan), "")
    runner = FakeRunner(responses)
    report = module.Bootstrapper(plan, runner, today=date(2026, 9, 5)).execute()
    assert report["status"] == "BLOCKED"
    assert report["steps"][-1]["name"] == "readiness_scan" and report["steps"][-1]["status"] == "fail"
    assert not runner.called("gh", "repo", "create")


def test_execute_without_preflight_script_is_fail_closed_unless_allowed(module, home) -> None:
    plan = module.build_plan(owner=OWNER, name="demo", visibility="private", description="デモ", home=home, env={})
    responses = _happy_responses(plan.repo_dir)
    responses[("gh", "repo", "create")] = (0, "", "")
    responses.update(_created("private"))
    report = module.Bootstrapper(plan, FakeRunner(responses), today=date(2026, 9, 5)).execute()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "readiness_scan"
    report = module.Bootstrapper(plan, FakeRunner(responses), today=date(2026, 9, 5), allow_no_preflight=True).execute()
    assert report["status"] == "READY"
    steps = {step["name"]: step for step in report["steps"]}
    assert steps["readiness_scan"]["status"] == "skipped"
    assert steps["push"]["status"] == "skipped" and "cc-push" in steps["push"]["detail"] or "wrapper" in steps["push"]["detail"]
    assert steps["lockdown"]["status"] == "skipped"  # private は lockdown 対象外
    assert steps["register"]["status"] == "skipped"


def test_main_without_confirm_only_runs_preflight(module, home, capsys) -> None:
    plan_probe = module.build_plan(owner=OWNER, name="demo", visibility="public", description="デモ", home=home, env={})
    runner = FakeRunner(_happy_responses(plan_probe.repo_dir))
    code = module.main(["--owner", OWNER, "--name", "demo", "--visibility", "public", "--description", "デモ", "--json"],
                       runner=runner, home=home, env={}, today=date(2026, 9, 5))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["mode"] == "preflight" and out["status"] == "READY"
    assert not runner.called("git", "init") and not runner.called("gh", "repo", "create")
    assert TOKEN not in json.dumps(out)


def test_main_confirm_executes_and_reports_json(module, home, capsys) -> None:
    plan_probe = module.build_plan(owner=OWNER, name="demo", visibility="private", description="デモ", home=home, env={})
    responses = _happy_responses(plan_probe.repo_dir)
    responses[("gh", "repo", "create")] = (0, "", "")
    responses.update(_created("private"))
    runner = FakeRunner(responses)
    code = module.main(["--owner", OWNER, "--name", "demo", "--visibility", "private", "--description", "デモ",
                        "--confirm", "--allow-no-preflight", "--json"],
                       runner=runner, home=home, env={}, today=date(2026, 9, 5))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["mode"] == "execute" and out["status"] == "READY"
    assert runner.called("gh", "repo", "create")
    assert TOKEN not in json.dumps(out)


def test_resume_accepts_existing_remote_and_matching_origin(module, home) -> None:
    """途中で止まった後の再実行: remote が既にあり origin が一致していれば続きから進める。"""
    plan = module.build_plan(owner=OWNER, name="demo", visibility="private", description="デモ", home=home, env={})
    plan.repo_dir.mkdir(parents=True)
    responses = _happy_responses(plan.repo_dir)
    responses[("gh", "repo", "view")] = (0, '{"nameWithOwner":"nexus-ai-2045/demo"}', "")
    responses[("git", "remote", "get-url", "origin")] = (0, plan.remote_url + "\n", "")
    responses[("git", "rev-list", "--count", "HEAD")] = (0, "3\n", "")
    responses.update(_created("private"))
    blocked = module.Bootstrapper(plan, FakeRunner(responses), today=date(2026, 9, 5), allow_no_preflight=True).preflight()
    assert blocked["status"] == "BLOCKED"
    runner = FakeRunner(responses)
    boot = module.Bootstrapper(plan, runner, today=date(2026, 9, 5), allow_no_preflight=True, resume=True)
    assert boot.preflight()["status"] == "READY"
    report = boot.execute()
    assert report["status"] == "READY", report
    steps = {step["name"]: step for step in report["steps"]}
    assert steps["create_remote"]["status"] == "skipped" and steps["add_remote"]["status"] == "skipped"
    assert steps["initial_commit"]["status"] == "skipped"
    assert not runner.called("gh", "repo", "create") and not runner.called("git", "remote", "add")


def test_resume_still_blocks_when_origin_points_elsewhere(module, home) -> None:
    plan = module.build_plan(owner=OWNER, name="demo", visibility="private", description="デモ", home=home, env={})
    plan.repo_dir.mkdir(parents=True)
    responses = _happy_responses(plan.repo_dir)
    responses[("gh", "repo", "view")] = (0, "{}", "")
    responses[("git", "remote", "get-url", "origin")] = (0, "https://github.com/x/y.git\n", "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=date(2026, 9, 5), resume=True).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["local_dir"] == "has_origin"


def test_main_resume_flag(module, home, capsys) -> None:
    plan_probe = module.build_plan(owner=OWNER, name="demo", visibility="private", description="デモ", home=home, env={})
    plan_probe.repo_dir.mkdir(parents=True)
    responses = _happy_responses(plan_probe.repo_dir)
    responses[("gh", "repo", "view")] = (0, "{}", "")
    responses[("git", "remote", "get-url", "origin")] = (0, plan_probe.remote_url + "\n", "")
    runner = FakeRunner(responses)
    code = module.main(["--name", "demo", "--visibility", "private", "--description", "デモ", "--resume", "--json"],
                       runner=runner, home=home, env={}, today=date(2026, 9, 5))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["status"] == "READY" and out["checks"]["remote_absent"] == "exists_resume"


def test_skip_push_marks_push_skipped_and_continues(module, home) -> None:
    """人の手で初回 push を済ませた後に --resume --skip-push で lockdown 以降だけを行う。"""
    plan = module.build_plan(owner=OWNER, name="demo", visibility="public", description="デモ", home=home, env={})
    plan.repo_dir.mkdir(parents=True)
    responses = _happy_responses(plan.repo_dir)
    responses[("gh", "repo", "view")] = (0, "{}", "")
    responses[("git", "remote", "get-url", "origin")] = (0, plan.remote_url + "\n", "")
    responses[("git", "rev-list", "--count", "HEAD")] = (0, "3\n", "")
    responses[("gh", "api", "-X", "PATCH")] = (0, "{}", "")
    responses[("gh", "api", "-X", "PUT")] = (0, "", "")
    responses.update(_created("public"))
    runner = FakeRunner(responses)
    report = module.Bootstrapper(plan, runner, today=date(2026, 9, 5), allow_no_preflight=True, resume=True, skip_push=True).execute()
    assert report["status"] == "READY", report
    steps = {step["name"]: step for step in report["steps"]}
    assert steps["push"]["status"] == "skipped" and "skip-push" in steps["push"]["detail"]
    assert steps["lockdown"]["status"] == "ok"
    assert not runner.called("bash")
