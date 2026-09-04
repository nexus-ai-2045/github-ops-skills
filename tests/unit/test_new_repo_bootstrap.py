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

SCRIPT = Path(__file__).resolve().parents[2] / "skills/new-repo-bootstrap/scripts/bootstrap_repo.py"
TOKEN = "gho_" + "x" * 36
OWNER = "nexus-ai-2045"
NEXUS_EMAIL = "273569186+nexus-ai-2045@users.noreply.github.com"
NEXUS = f"nexus_ai|{NEXUS_EMAIL}"
SHA = "a" * 40
TODAY = date(2026, 9, 5)


def _load_module():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("new_repo_bootstrap", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass の遅延 annotation 解決に必要
    spec.loader.exec_module(module)
    return module


class FakeRunner:
    """argv の最長一致 prefix で応答を返す。呼び出しと scoped_env を記録する。"""

    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str, str]]) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[tuple[str, ...], dict]] = []

    def run(self, argv, *, cwd=None, scoped_env=None, timeout=30):  # noqa: ANN001
        argv = tuple(argv)
        self.calls.append((argv, {"cwd": cwd, "scoped_env": dict(scoped_env or {})}))
        best = None
        for prefix, response in self.responses.items():
            if argv[: len(prefix)] == prefix and (best is None or len(prefix) > len(best[0])):
                best = (prefix, response)
        return best[1] if best else (0, "", "")

    def called(self, *prefix: str) -> list[tuple[tuple[str, ...], dict]]:
        return [call for call in self.calls if call[0][: len(prefix)] == prefix]


def _fresh(repo_dir: Path) -> dict:
    """新規作成 (remote 無し・local 無し) の応答。"""
    return {
        ("gh", "auth", "token"): (0, TOKEN + "\n", ""),
        ("gh", "api", "user"): (0, OWNER + "\n", ""),
        ("gh", "repo", "view"): (1, "", "GraphQL: Could not resolve to a Repository"),
        ("git", "rev-parse", "--show-toplevel"): (0, str(repo_dir) + "\n", ""),
        ("git", "rev-parse", "HEAD"): (0, SHA + "\n", ""),
        ("git", "remote", "get-url", "origin"): (1, "", "error: No such remote"),
        ("git", "log", "--format=%an|%ae|%cn|%ce"): (0, "", ""),
        ("git", "rev-list", "--count", "HEAD"): (1, "", "fatal: bad revision"),
        ("git", "status", "--porcelain", "--untracked-files=all"): (0, "", ""),
    }


def _remote(visibility: str, *, sha: str = SHA) -> dict:
    """remote が存在する時の read-back 応答。"""
    return {
        ("gh", "repo", "view"): (0, json.dumps({"nameWithOwner": f"{OWNER}/demo", "visibility": visibility.upper()}), ""),
        ("gh", "api", f"repos/{OWNER}/demo", "--jq"): (0, json.dumps({"full_name": f"{OWNER}/demo", "visibility": visibility, "default_branch": "main"}), ""),
        ("gh", "api", f"repos/{OWNER}/demo/branches/main"): (0, sha + "\n", ""),
    }


def _scan(ok: bool = True, **overrides: str) -> str:
    checks = {k: {"status": "pass"} for k in ("required_documents", "secret_scan", "personal_path_scan", "commit_identity")}
    checks.update({"ci_configuration": {"status": "unknown"}, "origin": {"status": "unknown"}})
    for name, status in overrides.items():
        checks[name] = {"status": status}
    return json.dumps({"status": "pass" if ok else "blocked", "checks": checks})


@pytest.fixture
def module():  # noqa: ANN201
    return _load_module()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "Projects" / "Documents" / ".repos" / "nexus_ai").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def tools(tmp_path: Path) -> dict:
    registry = tmp_path / "map.md"
    registry.write_text("| a | b | c | d |\n| 公開協業 repo 全般 | - | x | y |\n", encoding="utf-8")
    wrapper = tmp_path / "push.sh"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    preflight = tmp_path / "readiness_scan.py"
    preflight.write_text("", encoding="utf-8")
    return {"registry_file": registry, "push_wrapper": wrapper, "preflight_script": preflight}


def _plan(module, home, visibility="public", **kw):  # noqa: ANN001, ANN202
    return module.build_plan(owner=OWNER, name="demo", visibility=visibility, description="デモ", home=home, env={}, **kw)


# ---------- plan ----------

def test_default_local_root_depends_on_visibility_and_env(module, home) -> None:
    assert module.default_local_root(home, "public", {}) == home / "Projects/Documents/.repos/nexus_ai"
    assert module.default_local_root(home, "private", {}) == home / "Projects/Documents/.repos/nexus_ai/private"
    assert module.default_local_root(home, "public", {"GITHUB_OPS_REPO_ROOT": str(home / "x")}) == home / "x"


def test_build_plan_identity_and_validation(module, home) -> None:
    plan = _plan(module, home)
    assert plan.repo_dir == home / "Projects/Documents/.repos/nexus_ai/demo"
    assert (plan.commit_name, plan.commit_email) == ("nexus_ai", NEXUS_EMAIL)
    with pytest.raises(module.BootstrapError):
        module.build_plan(owner="someone-else", name="demo", visibility="public", description="d", home=home, env={})
    assert module.build_plan(owner="someone-else", name="demo", visibility="private", description="d", home=home, env={},
                             commit_name="Some One", commit_email="s@example.com").commit_name == "Some One"
    for bad in ("", "with space", "../escape", "a/b"):
        with pytest.raises(module.BootstrapError):
            module.build_plan(owner=OWNER, name=bad, visibility="public", description="d", home=home, env={})


# ---------- preflight ----------

def test_preflight_ready_and_token_scoped(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    runner = FakeRunner(_fresh(plan.repo_dir))
    result = module.Bootstrapper(plan, runner, today=TODAY).preflight()
    assert result["status"] == "READY", result
    assert result["checks"]["token_login"] == "ok" and result["checks"]["remote_absent"] == "ok"
    assert result["checks"]["local_dir"] == "absent" and result["checks"]["preflight_script"] == "ok"
    assert runner.called("gh", "api", "user")[0][1]["scoped_env"]["GH_TOKEN"] == TOKEN
    assert TOKEN not in json.dumps(result)


def test_preflight_blocks_token_mismatch(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _fresh(plan.repo_dir)
    responses[("gh", "api", "user")] = (0, "someone-else\n", "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["token_login"] == "mismatch"
    assert TOKEN not in json.dumps(result)


def test_preflight_blocks_missing_scanner_unless_allowed(module, home) -> None:
    plan = _plan(module, home)
    result = module.Bootstrapper(plan, FakeRunner(_fresh(plan.repo_dir)), today=TODAY).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["preflight_script"] == "missing"
    result = module.Bootstrapper(plan, FakeRunner(_fresh(plan.repo_dir)), today=TODAY, allow_no_preflight=True).preflight()
    assert result["status"] == "READY" and result["checks"]["preflight_script"] == "skipped"


def test_preflight_blocks_existing_remote_or_foreign_origin(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = {**_fresh(plan.repo_dir), **_remote("public")}
    result = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["remote_absent"] == "exists"
    plan.repo_dir.mkdir(parents=True)
    responses = _fresh(plan.repo_dir)
    responses[("git", "remote", "get-url", "origin")] = (0, "https://github.com/x/y.git\n", "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["local_dir"] == "has_origin"


def test_preflight_blocks_nested_worktree_and_committer_mismatch(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    plan.repo_dir.mkdir(parents=True)
    responses = _fresh(plan.repo_dir)
    responses[("git", "rev-parse", "--show-toplevel")] = (0, str(plan.repo_dir.parent) + "\n", "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["local_dir"] == "nested_in_other_repo"
    responses = _fresh(plan.repo_dir)
    responses[("git", "log", "--format=%an|%ae|%cn|%ce")] = (0, f"{NEXUS}|Personal|me@example.com\n", "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["commit_identity"] == "mismatch"
    responses[("git", "log", "--format=%an|%ae|%cn|%ce")] = (0, f"{NEXUS}|{NEXUS}\n", "")
    assert module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).preflight()["checks"]["commit_identity"] == "ok"


def test_resume_requires_local_state_and_matching_visibility(module, home, tools) -> None:
    plan = _plan(module, home, "private", **tools)
    responses = {**_fresh(plan.repo_dir), **_remote("private")}
    result = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY, resume=True).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["local_dir"] == "absent"   # remote だけあって local が無い
    plan.repo_dir.mkdir(parents=True)
    responses[("git", "remote", "get-url", "origin")] = (0, plan.remote_url + "\n", "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY, resume=True).preflight()
    assert result["status"] == "READY" and result["checks"]["remote_absent"] == "exists_resume"
    assert result["checks"]["local_dir"] == "origin_matches"
    responses.update(_remote("public"))
    result = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY, resume=True).preflight()
    assert result["status"] == "BLOCKED" and result["checks"]["remote_absent"] == "exists_visibility_public"


# ---------- templates / registry ----------

def test_templates_scaffold_and_visibility_claim(module, home) -> None:
    plan = _plan(module, home)
    templates = module.render_templates(plan, today=TODAY)
    assert set(templates) == set(module.SCAFFOLD_ORDER)
    assert "Copyright (c) 2026 nexus_ai" in templates["LICENSE"]
    assert "repo-preflight:review-record" in templates["PREFLIGHT.md"] and "状態: 公開済み" in templates["PREFLIGHT.md"]
    assert "状態: 非公開" in module.render_templates(_plan(module, home, "private"), today=TODAY)["PREFLIGHT.md"]
    plan.repo_dir.mkdir(parents=True)
    (plan.repo_dir / "README.md").write_text("mine", encoding="utf-8")
    written = module.scaffold_docs(plan, today=TODAY)
    assert "README.md" not in written and "LICENSE" in written
    assert (plan.repo_dir / "README.md").read_text(encoding="utf-8") == "mine"
    assert str(home) not in (plan.repo_dir / "PREFLIGHT.md").read_text(encoding="utf-8")


def test_registry_row_dedup_by_repository_key(module, home) -> None:
    plan = _plan(module, home)
    row = module.registry_row(plan, today=TODAY)
    assert row.startswith(f"| `{OWNER}/demo`（デモ） | public | **{OWNER}** |")
    assert "~/Projects/Documents/.repos/nexus_ai/demo" in row and str(home) not in row
    text = "| a | b | c | d |\n| 公開協業 repo 全般 | - | x | y |\n"
    updated = module.insert_registry_row(text, row, key=f"{OWNER}/demo")
    assert updated is not None and updated.index(row) < updated.index("| 公開協業 repo 全般")
    assert module.insert_registry_row(updated, row, key=f"{OWNER}/demo") == updated
    later = module.registry_row(plan, today=date(2026, 9, 6))
    again = module.insert_registry_row(updated, later, key=f"{OWNER}/demo")
    assert again.count(f"| `{OWNER}/demo`") == 1 and "2026-09-06" in again
    assert module.insert_registry_row("no anchor\n", row, key=f"{OWNER}/demo") is None


# ---------- execute ----------

def _happy_execute(plan, tools, visibility="public"):  # noqa: ANN001, ANN202
    responses = _fresh(plan.repo_dir)
    responses[("python3", str(tools["preflight_script"]))] = (0, _scan(), "")
    responses[("gh", "repo", "create")] = (0, "", "")
    responses[("bash", str(tools["push_wrapper"]))] = (0, "pushed\n", "")
    responses[("gh", "api", "-X", "PATCH")] = (0, "{}", "")
    responses[("gh", "api", "-X", "PUT")] = (0, "", "")
    responses[("gh", "api", "-X", "POST")] = (0, "{}", "")
    responses[("gh", "api", "-X", "DELETE")] = (0, "", "")
    responses.update({k: v for k, v in _remote(visibility).items() if k[:3] != ("gh", "repo", "view")})
    return responses


def test_execute_order_lockdown_before_push_and_main_promotion(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    runner = FakeRunner(_happy_execute(plan, tools))
    report = module.Bootstrapper(plan, runner, today=TODAY).execute()
    assert report["status"] == "READY", report
    names = [s["name"] for s in report["steps"]]
    assert names == ["preflight", *module.STEP_ORDER]
    assert names.index("lockdown") < names.index("push")
    assert all(s["status"] in {"ok", "skipped"} for s in report["steps"])
    create = runner.called("gh", "repo", "create")[0]
    assert create[0][:5] == ("gh", "repo", "create", f"{OWNER}/demo", "--public") and create[1]["scoped_env"]["GH_TOKEN"] == TOKEN
    assert runner.called("git", "init", "-b", "main") and runner.called("git", "config", "user.name", "nexus_ai")
    push = runner.called("bash", str(tools["push_wrapper"]))[0][0]
    assert push[-2:] == ("--branch", module.INIT_BRANCH)
    assert not runner.called("git", "push")
    post = runner.called("gh", "api", "-X", "POST")[0][0]
    assert "ref=refs/heads/main" in post and f"sha={SHA}" in post
    assert any("default_branch=main" in " ".join(c[0]) for c in runner.called("gh", "api", "-X", "PATCH"))
    assert runner.called("gh", "api", "-X", "DELETE")
    assert f"`{OWNER}/demo`" in tools["registry_file"].read_text(encoding="utf-8")
    assert TOKEN not in json.dumps(report)


def test_execute_stops_on_scan_failure_before_remote(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _happy_execute(plan, tools)
    responses[("python3", str(tools["preflight_script"]))] = (0, _scan(secret_scan="fail"), "")
    runner = FakeRunner(responses)
    report = module.Bootstrapper(plan, runner, today=TODAY).execute()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "readiness_scan"
    assert not runner.called("gh", "repo", "create")
    responses[("python3", str(tools["preflight_script"]))] = (0, _scan(ci_configuration="fail"), "")
    report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).execute()
    assert report["steps"][-1]["status"] == "fail" and "ci_configuration" in report["steps"][-1]["detail"]
    responses[("python3", str(tools["preflight_script"]))] = (2, "", "boom")
    report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).execute()
    assert report["steps"][-1]["status"] == "fail" and "rc=2" in report["steps"][-1]["detail"]
    responses[("python3", str(tools["preflight_script"]))] = (1, json.dumps({"status": "tool_error", "issues": ["not_git_repository"], "checks": {}}), "")
    report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).execute()
    assert report["steps"][-1]["status"] == "fail" and "tool_error" in report["steps"][-1]["detail"]
    # remote 未作成で origin / CI が unknown → scanner は rc=1 / blocked を返すが、fail が無ければ進む
    responses[("python3", str(tools["preflight_script"]))] = (1, _scan(ok=False), "")
    report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).execute()
    assert report["status"] == "READY", report


def test_initial_commit_blocks_on_leftover_untracked_files(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _happy_execute(plan, tools)
    responses[("git", "status", "--porcelain", "--untracked-files=all")] = (0, "A  LICENSE\n?? src/app.py\n", "")
    runner = FakeRunner(responses)
    report = module.Bootstrapper(plan, runner, today=TODAY).execute()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "initial_commit"
    assert "src/app.py" in report["steps"][-1]["detail"] and not runner.called("git", "commit")


def test_execute_private_skips_lockdown_and_missing_wrapper_fails_closed(module, home, tools) -> None:
    plan = _plan(module, home, "private", **tools)
    report = module.Bootstrapper(plan, FakeRunner(_happy_execute(plan, tools, "private")), today=TODAY).execute()
    assert report["status"] == "READY", report
    assert {s["name"]: s for s in report["steps"]}["lockdown"]["status"] == "skipped"
    plan.push_wrapper = None
    report = module.Bootstrapper(plan, FakeRunner(_happy_execute(plan, tools, "private")), today=TODAY).execute()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "push"


def test_verify_requires_remote_main_matching_local_head(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _happy_execute(plan, tools)
    responses[("gh", "api", f"repos/{OWNER}/demo/branches/main")] = (1, "", "Not Found")
    report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).execute()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "verify" and "main が無い" in report["steps"][-1]["detail"]
    responses[("gh", "api", f"repos/{OWNER}/demo/branches/main")] = (0, "b" * 40 + "\n", "")
    report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).execute()
    assert report["steps"][-1]["status"] == "fail" and "一致しない" in report["steps"][-1]["detail"]


def test_resume_skip_push_completes_remaining_steps(module, home, tools) -> None:
    plan = _plan(module, home, "private", **tools)
    plan.repo_dir.mkdir(parents=True)
    responses = _happy_execute(plan, tools, "private")
    responses.update(_remote("private"))
    responses[("git", "remote", "get-url", "origin")] = (0, plan.remote_url + "\n", "")
    responses[("git", "rev-list", "--count", "HEAD")] = (0, "3\n", "")
    runner = FakeRunner(responses)
    report = module.Bootstrapper(plan, runner, today=TODAY, resume=True, skip_push=True).execute()
    assert report["status"] == "READY", report
    steps = {s["name"]: s for s in report["steps"]}
    assert steps["create_remote"]["status"] == "skipped" and steps["add_remote"]["status"] == "skipped"
    assert steps["push"]["status"] == "skipped" and steps["promote_main"]["status"] == "skipped"
    assert steps["initial_commit"]["status"] == "skipped" and steps["verify"]["status"] == "ok"
    assert not runner.called("gh", "repo", "create") and not runner.called("bash")


# ---------- CLI ----------

def _cli_tool_args(tools: dict) -> list[str]:
    return ["--registry-file", str(tools["registry_file"]), "--push-wrapper", str(tools["push_wrapper"]),
            "--preflight-script", str(tools["preflight_script"])]


def test_main_without_confirm_only_preflights(module, home, tools, capsys) -> None:
    plan = _plan(module, home, **tools)
    runner = FakeRunner(_fresh(plan.repo_dir))
    code = module.main(["--name", "demo", "--visibility", "public", "--description", "デモ", "--json", *_cli_tool_args(tools)],
                       runner=runner, home=home, env={}, today=TODAY)
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["mode"] == "preflight" and out["status"] == "READY"
    assert not runner.called("git", "init") and not runner.called("gh", "repo", "create")
    assert TOKEN not in json.dumps(out)


def test_main_confirm_executes(module, home, tools, capsys) -> None:
    plan = _plan(module, home, "private", **tools)
    runner = FakeRunner(_happy_execute(plan, tools, "private"))
    code = module.main(["--name", "demo", "--visibility", "private", "--description", "デモ", "--confirm", "--json", *_cli_tool_args(tools)],
                       runner=runner, home=home, env={}, today=TODAY)
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["mode"] == "execute" and out["status"] == "READY", out
    assert runner.called("gh", "repo", "create") and TOKEN not in json.dumps(out)
