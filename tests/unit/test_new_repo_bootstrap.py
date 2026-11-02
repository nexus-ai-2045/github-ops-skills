"""new-repo-bootstrap: 新規 repository の作成を 1 本の fail-closed 手順にまとめる script のテスト。

runner を差し替えて gh と新 repository 側の git を呼ばずに検査する。token は出力へ出ない。
台帳の登録だけは、台帳を持つ workspace repository を tmp に本物の git で作り、
main checkout が汚れないことと、差分が origin/main から切った branch に乗ることを実物で確かめる。
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "skills/new-repo-bootstrap/scripts/bootstrap_repo.py"
SKILL_DOC = SCRIPT.parents[1] / "SKILL.md"
TOKEN = "gho_" + "x" * 36
OWNER = "nexus-ai-2045"
NEXUS_EMAIL = "273569186+nexus-ai-2045@users.noreply.github.com"
NEXUS = f"nexus_ai|{NEXUS_EMAIL}"
SHA = "a" * 40
TODAY = date(2026, 9, 5)
REGISTRY_REL = "Documents/references/github-account-repo-map.md"
REGISTRY_TEXT = "| a | b | c | d |\n| 公開協業 repo 全般 | - | x | y |\n"
# workspace の commit wrapper (cc-commit.sh) の最小 fake: CC_COMMIT_PROJECTS_DIR の worktree で --only の path だけを commit する
FAKE_COMMIT_WRAPPER = """#!/bin/sh
set -eu
[ "$1" = "projects" ]
dir="${CC_COMMIT_PROJECTS_DIR:?}"
msg="$2"
shift 2
[ "$1" = "--only" ]
shift
git -C "$dir" add -- "$@"
git -C "$dir" -c user.name=ws -c user.email=ws@example.invalid commit -q -m "$msg"
"""
STRAY_COMMIT_WRAPPER = FAKE_COMMIT_WRAPPER.replace(
    'git -C "$dir" add -- "$@"', 'echo stray > "$dir/stray.txt"\ngit -C "$dir" add -- "$@" stray.txt'
)
# worktree の外 (台帳 repo の main checkout) に書いてしまう commit 入口
ROGUE_COMMIT_WRAPPER = FAKE_COMMIT_WRAPPER.replace(
    'git -C "$dir" add -- "$@"',
    'main="$(dirname "$(git -C "$dir" rev-parse --path-format=absolute --git-common-dir)")"\n'
    f'echo rogue >> "$main/{REGISTRY_REL}"\n'
    'git -C "$dir" add -- "$@"',
)

# workspace の日本語ゲート整形 (japanese_gate_autoformat.py) の fake: 整形した印を行に残す
FAKE_FORMATTER = """import sys
from pathlib import Path
assert sys.argv[1] == "--apply"
path = Path(sys.argv[2])
path.write_text(path.read_text(encoding="utf-8").replace("（デモ）", "（デモ・整形済み）"), encoding="utf-8")
"""
FAILING_FORMATTER = "import sys\nsys.exit(3)\n"
OVERREACHING_FORMATTER = FAKE_FORMATTER.replace('.replace("（デモ）", "（デモ・整形済み）")', '.replace("| a |", "| A |")')
FORMATTED_REGISTRY_TEXT = "| a | b | c | d |\n| 公開協業 `repo` 全般 | - | **`x`** に統一 | y |\n"


def _isolated_env(scoped_env: dict | None = None) -> dict[str, str]:
    """外側の repo / hook / global config を拾わない git 用 env (受け継いだ GIT_* を落とす)。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    env.update(scoped_env or {})
    return env


def _run_real(argv, *, cwd=None, scoped_env=None, timeout=30):  # noqa: ANN001, ANN202
    done = subprocess.run(list(argv), cwd=cwd, env=_isolated_env(scoped_env), capture_output=True,
                          text=True, check=False, timeout=timeout)
    return done.returncode, done.stdout, done.stderr


def _git(cwd: Path, *args: str) -> str:
    rc, out, err = _run_real(["git", "-C", str(cwd), *args])
    assert rc == 0, (args, err)
    return out.strip()


def _make_workspace(root: Path, *, registry_text: str = REGISTRY_TEXT, commit_wrapper: str | None = FAKE_COMMIT_WRAPPER,
                    ignore_worktrees: bool = True, formatter: str | None = None) -> Path:
    """台帳を持つ workspace repository の main checkout を作る (bare remote + clone)。"""
    remote, seed, checkout = root / "remote.git", root / "seed", root / "ws"
    root.mkdir(parents=True)
    assert _run_real(["git", "init", "-q", "--bare", "-b", "main", str(remote)])[0] == 0
    assert _run_real(["git", "init", "-q", "-b", "main", str(seed)])[0] == 0
    (seed / REGISTRY_REL).parent.mkdir(parents=True)
    (seed / REGISTRY_REL).write_text(registry_text, encoding="utf-8")
    if commit_wrapper is not None:
        (seed / "shared/scripts").mkdir(parents=True)
        (seed / "shared/scripts/cc-commit.sh").write_text(commit_wrapper, encoding="utf-8")
    if formatter is not None:
        (seed / "shared/scripts").mkdir(parents=True, exist_ok=True)
        (seed / "shared/scripts/japanese_gate_autoformat.py").write_text(formatter, encoding="utf-8")
    (seed / ".gitignore").write_text(".worktrees/\n" if ignore_worktrees else "*.pyc\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "-c", "user.name=seed", "-c", "user.email=seed@example.invalid", "commit", "-q", "-m", "seed")
    _git(seed, "push", "-q", str(remote), "main")
    assert _run_real(["git", "clone", "-q", str(remote), str(checkout)])[0] == 0
    return checkout


def _load_module():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("new_repo_bootstrap", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass の遅延 annotation 解決に必要
    spec.loader.exec_module(module)
    return module


class FakeRunner:
    """argv の最長一致 prefix で応答を返す。呼び出しと scoped_env を記録する。

    台帳 workspace への `git -C` と commit wrapper (cc-commit.sh) だけは、応答が無ければ tmp の実 repository で実行する。
    """

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
        if best:
            return best[1]
        workspace_tool = argv[:1] in {("bash",), ("python3",)} and argv[1].endswith(("cc-commit.sh", "japanese_gate_autoformat.py"))
        if argv[:2] == ("git", "-C") or workspace_tool:
            return _run_real(argv, cwd=cwd, scoped_env=scoped_env, timeout=timeout)
        return (0, "", "")

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
    registry = _make_workspace(tmp_path / "workspace") / REGISTRY_REL
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


def test_registry_local_path_is_workspace_relative_and_falls_back(module, home, tmp_path) -> None:
    """台帳の local: は workspace 相対。workspace の外なら ~ 表記へ落とす。"""
    plan = _plan(module, home)
    assert module.registry_local_path(plan) == "Documents/.repos/nexus_ai/demo"

    outside = _plan(module, home, repo_dir=tmp_path / "elsewhere" / "demo")
    assert module.registry_local_path(outside).startswith(("~/", "/"))


def test_registry_row_dedup_by_repository_key(module, home) -> None:
    plan = _plan(module, home)
    row = module.registry_row(plan, today=TODAY)
    assert row.startswith(f"| `{OWNER}/demo`（デモ） | `public` | **`{OWNER}`** |")
    assert "ローカル: `Documents/.repos/nexus_ai/demo`" in row
    assert "~/" not in row and str(home) not in row
    text = "| a | b | c | d |\n| 公開協業 repo 全般 | - | x | y |\n"
    updated = module.insert_registry_row(text, row, key=f"{OWNER}/demo")
    assert updated is not None and updated.index(row) < updated.index("| 公開協業 repo 全般")
    assert module.insert_registry_row(updated, row, key=f"{OWNER}/demo") == updated
    later = module.registry_row(plan, today=date(2026, 9, 6))
    again = module.insert_registry_row(updated, later, key=f"{OWNER}/demo")
    assert again.count(f"| `{OWNER}/demo`") == 1 and "2026-09-06" in again
    assert module.insert_registry_row("no anchor\n", row, key=f"{OWNER}/demo") is None


def test_registry_matching_ignores_inline_code_formatting(module, home) -> None:
    """台帳が日本語ゲート向けにコード表記へ整形されても、挿入位置の行と既存行を見失わない。"""
    plan = _plan(module, home)
    row = module.registry_row(plan, today=TODAY)
    formatted = "| a | b | c | d |\n| 公開協業 `repo` 全般 | - | **`x`** に統一 | y |\n"
    updated = module.insert_registry_row(formatted, row, key=f"{OWNER}/demo")
    assert updated is not None and updated.index(row) < updated.index("| 公開協業 `repo` 全般")
    assert module.registry_has_key(updated.replace(f"`{OWNER}/demo`", f"{OWNER}/demo"), f"{OWNER}/demo")
    for other in ("demo.v2", "demo_x", "demo-x"):
        assert not module.registry_has_key(f"| `{OWNER}/{other}`（x） |\n", f"{OWNER}/demo")
    assert module.registry_has_key(f"| `{OWNER}/demo`の説明 |\n", f"{OWNER}/demo")


def test_register_works_on_registry_already_formatted_for_japanese_gate(module, home, tmp_path, tools) -> None:
    checkout = _make_workspace(tmp_path / "formatted", registry_text=FORMATTED_REGISTRY_TEXT)
    plan = _plan(module, home, **{**tools, "registry_file": checkout / REGISTRY_REL})
    boot = module.Bootstrapper(plan, FakeRunner(_fresh(plan.repo_dir)), today=TODAY)
    assert boot.preflight()["checks"]["registry_file"] == "ok"
    status, detail = boot._register()
    assert status == "ok", detail
    shown = _git(checkout, "show", f"{boot.registration['branch']}:{REGISTRY_REL}")
    assert shown.index(module.registry_row(plan, today=TODAY)) < shown.index("| 公開協業 `repo` 全般")


def test_register_commits_on_branch_from_origin_main_and_keeps_main_checkout_clean(module, home, tools) -> None:
    """登録は台帳の main checkout に書かない。origin/main から切った専用 worktree の branch に 1 commit で載せる。"""
    plan = _plan(module, home, **tools)
    checkout = tools["registry_file"].parents[2]
    head_before = _git(checkout, "rev-parse", "HEAD")
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    status, detail = boot._register()
    assert status == "ok", detail
    assert _git(checkout, "status", "--porcelain", "--untracked-files=all") == ""
    assert tools["registry_file"].read_text(encoding="utf-8") == REGISTRY_TEXT
    assert _git(checkout, "rev-parse", "HEAD") == head_before
    registration = boot.registration
    branch = registration["branch"]
    assert branch == module.register_names(plan)[1] == f"{module.REGISTER_BRANCH_PREFIX}{OWNER}-demo"
    assert _git(checkout, "rev-parse", f"{branch}~1") == _git(checkout, "rev-parse", "origin/main")
    assert _git(checkout, "diff", "--name-only", f"origin/main...{branch}").splitlines() == [REGISTRY_REL]
    assert module.registry_row(plan, today=TODAY) in _git(checkout, "show", f"{branch}:{REGISTRY_REL}")
    assert registration["commit"] == _git(checkout, "rev-parse", branch)
    assert registration["file"] == REGISTRY_REL and str(home) not in json.dumps(registration)
    skill_text = SKILL_DOC.read_text(encoding="utf-8")
    assert all(f"`{key}`" in skill_text for key in registration), "SKILL.md が registration の項目を全部書いていない"
    # 途中で止まった後の再実行は、日付が変わっても同じ branch に重ねて commit しない
    again = module.Bootstrapper(plan, FakeRunner({}), today=date(2026, 9, 6))
    assert again._register()[0] == "ok"
    assert _git(checkout, "rev-parse", branch) == registration["commit"]
    assert _git(checkout, "status", "--porcelain", "--untracked-files=all") == ""


def test_register_formats_row_with_workspace_formatter_before_commit(module, home, tmp_path, tools) -> None:
    """台帳 repo に日本語ゲートの整形入口があれば、commit 前に行を整形する。整形に失敗したら commit しない。"""
    checkout = _make_workspace(tmp_path / "fmt", formatter=FAKE_FORMATTER)
    plan = _plan(module, home, **{**tools, "registry_file": checkout / REGISTRY_REL})
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    status, detail = boot._register()
    assert status == "ok", detail
    assert "（デモ・整形済み）" in _git(checkout, "show", f"{boot.registration['branch']}:{REGISTRY_REL}")
    failing = _make_workspace(tmp_path / "fmtfail", formatter=FAILING_FORMATTER)
    plan = _plan(module, home, **{**tools, "registry_file": failing / REGISTRY_REL})
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    status, detail = boot._register()
    assert status == "fail" and "整形" in detail and boot.registration is None
    assert _git(failing, "branch", "--list", f"{module.REGISTER_BRANCH_PREFIX}*") != "" and _git(
        failing, "rev-parse", module.register_names(plan)[1]) == _git(failing, "rev-parse", "origin/main")
    # 再実行は前回の未 commit の行を捨て、今の引数で行を作り直す
    retry = module.build_plan(owner=OWNER, name="demo", visibility="public", description="デモ2", home=home, env={},
                              **{**tools, "registry_file": failing / REGISTRY_REL})
    assert module.Bootstrapper(retry, FakeRunner({}), today=TODAY)._register()[0] == "fail"
    left = (failing / module.REGISTER_WORKTREE_DIR / module.register_names(retry)[0] / REGISTRY_REL).read_text(encoding="utf-8")
    assert "（デモ2）" in left and "（デモ）" not in left
    overreach = _make_workspace(tmp_path / "fmtover", formatter=OVERREACHING_FORMATTER)
    plan = _plan(module, home, **{**tools, "registry_file": overreach / REGISTRY_REL})
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    status, detail = boot._register()
    assert status == "fail" and "整形" in detail and boot.registration is None


def test_register_reattaches_branch_when_worktree_was_removed(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    checkout = tools["registry_file"].parents[2]
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    assert boot._register()[0] == "ok"
    worktree = checkout / module.REGISTER_WORKTREE_DIR / module.register_names(plan)[0]
    _git(checkout, "worktree", "remove", "--force", str(worktree))
    again = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    status, detail = again._register()
    assert status == "ok", detail
    assert worktree.exists() and again.registration["commit"] == boot.registration["commit"]


def test_register_skips_repository_already_on_origin_main(module, home, tmp_path, tools) -> None:
    plan = _plan(module, home, **tools)
    registered = module.insert_registry_row(REGISTRY_TEXT, module.registry_row(plan, today=TODAY), key=f"{OWNER}/demo")
    checkout = _make_workspace(tmp_path / "registered", registry_text=registered)
    plan.registry_file = checkout / REGISTRY_REL
    status, detail = module.Bootstrapper(plan, FakeRunner({}), today=date(2026, 9, 6))._register()
    assert status == "skipped", detail
    assert not (checkout / ".worktrees").exists()
    assert _git(checkout, "branch", "--list", f"{module.REGISTER_BRANCH_PREFIX}*") == ""


def test_register_fails_closed_when_commit_wrapper_adds_other_paths(module, home, tmp_path, tools) -> None:
    checkout = _make_workspace(tmp_path / "stray", commit_wrapper=STRAY_COMMIT_WRAPPER)
    plan = _plan(module, home, **{**tools, "registry_file": checkout / REGISTRY_REL})
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    status, detail = boot._register()
    assert status == "fail" and "stray.txt" in detail and boot.registration is None
    assert _git(checkout, "status", "--porcelain", "--untracked-files=all") == ""


def test_register_fails_closed_when_commit_wrapper_writes_main_checkout(module, home, tmp_path, tools) -> None:
    """commit 入口が worktree の指定を守らず main checkout に書いたら、登録 branch を出さずに止める。"""
    checkout = _make_workspace(tmp_path / "rogue", commit_wrapper=ROGUE_COMMIT_WRAPPER)
    plan = _plan(module, home, **{**tools, "registry_file": checkout / REGISTRY_REL})
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    status, detail = boot._register()
    assert status == "fail" and "main checkout" in detail and boot.registration is None


def test_preflight_blocks_registry_that_cannot_be_committed_through_a_branch(module, home, tmp_path, tools) -> None:
    """作成してから register で止まらないよう、台帳を branch で commit できない状態は preflight で止める。"""
    loose = tmp_path / "loose.md"
    loose.write_text(REGISTRY_TEXT, encoding="utf-8")
    local_only = tmp_path / "local-only"
    assert _run_real(["git", "init", "-q", "-b", "main", str(local_only)])[0] == 0
    (local_only / "map.md").write_text(REGISTRY_TEXT, encoding="utf-8")
    untracked = _make_workspace(tmp_path / "untracked") / "Documents/references/untracked.md"
    untracked.write_text(REGISTRY_TEXT, encoding="utf-8")
    cases = {
        "not_git": loose,
        "no_origin_main": local_only / "map.md",
        "registry_not_on_origin_main": untracked,
        "registry_anchor_missing": _make_workspace(tmp_path / "noanchor", registry_text="| a | b |\n") / REGISTRY_REL,
        "commit_wrapper_missing": _make_workspace(tmp_path / "nowrap", commit_wrapper=None) / REGISTRY_REL,
        "worktree_dir_not_ignored": _make_workspace(tmp_path / "noignore", ignore_worktrees=False) / REGISTRY_REL,
    }
    for expected, registry in cases.items():
        plan = _plan(module, home, **{**tools, "registry_file": registry})
        result = module.Bootstrapper(plan, FakeRunner(_fresh(plan.repo_dir)), today=TODAY).preflight()
        assert result["status"] == "BLOCKED" and result["checks"]["registry_file"] == expected, (expected, result)
    plan = _plan(module, home, **tools)
    assert module.Bootstrapper(plan, FakeRunner(_fresh(plan.repo_dir)), today=TODAY).preflight()["checks"]["registry_file"] == "ok"


# ---------- execute ----------

def _happy_execute(plan, tools, visibility="public"):  # noqa: ANN001, ANN202
    responses = _fresh(plan.repo_dir)
    responses[("python3", str(tools["preflight_script"]))] = (0, _scan(), "")
    responses[("gh", "repo", "create")] = (0, "", "")
    responses[("bash", str(tools["push_wrapper"]))] = (0, "pushed\n", "")
    responses[("gh", "api", "-X", "PATCH")] = (0, "{}", "")
    responses[("gh", "api", "-X", "PATCH", f"repos/{OWNER}/demo", "-F")] = (0, "true\n", "")
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
    assert names.index("create_remote") < names.index("repo_settings") < names.index("push")
    settings = runner.called("gh", "api", "-X", "PATCH", f"repos/{OWNER}/demo", "-F")
    assert settings and settings[0][0][6] == "delete_branch_on_merge=true" and settings[0][1]["scoped_env"]["GH_TOKEN"] == TOKEN
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
    assert runner.called("git", "config", "branch.main.remote", "origin") and not runner.called("git", "fetch")
    assert runner.called("git", "update-ref", "refs/remotes/origin/main", SHA)
    assert tools["registry_file"].read_text(encoding="utf-8") == REGISTRY_TEXT   # main checkout には書かない
    registration = report["registration"]
    assert registration["branch"] == module.register_names(plan)[1] and report["next"] == module.REGISTRATION_NEXT
    assert f"`{OWNER}/demo`" in _git(tools["registry_file"].parents[2], "show", f"{registration['branch']}:{REGISTRY_REL}")
    worktree = tools["registry_file"].parents[2] / module.REGISTER_WORKTREE_DIR / module.register_names(plan)[0]
    commit = runner.called("bash", str(worktree / module.REGISTRY_COMMIT_WRAPPER))
    assert commit and "GH_TOKEN" not in commit[0][1]["scoped_env"]
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
    assert {s["name"]: s for s in report["steps"]}["repo_settings"]["status"] == "ok"
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
    assert not runner.called("gh", "repo", "create") and not runner.called("bash", str(tools["push_wrapper"]))
    assert steps["repo_settings"]["status"] == "ok"
    assert len(runner.called("gh", "api", "-X", "PATCH", f"repos/{OWNER}/demo", "-F")) == 1


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


# ---------- SKILL.md と script の一致 ----------

def test_skill_document_matches_script_step_order_and_registry_checks(module) -> None:
    """SKILL.md の手順と preflight の止まり方は script から外れない (中断した編集で食い違ったまま merge された再発防止)。"""
    text = SKILL_DOC.read_text(encoding="utf-8")
    match = re.search(r"step は `(preflight →.+?)` の順", text, flags=re.DOTALL)
    assert match, "SKILL.md に step の順序の行が無い"
    steps = [re.sub(r"\(.*?\)", "", step).strip() for step in match.group(1).split("→")]
    assert steps == ["preflight", *module.STEP_ORDER]
    failures = set(re.findall(r'return "(\w+)"', inspect.getsource(module.Bootstrapper._check_registry))) - {"ok", "skipped"}
    undocumented = {value for value in failures if not re.search(rf"(?<![\w]){value}(?![\w])", text)}
    assert failures and not undocumented, undocumented


# ---------- settings-only ----------

def _settings_responses(visibility: str = "public", readback: str = "true\n") -> dict:
    return {
        ("gh", "auth", "token"): (0, TOKEN + "\n", ""),
        ("gh", "api", "user"): (0, OWNER + "\n", ""),
        **_remote(visibility),
        ("gh", "api", "-X", "PATCH", f"repos/{OWNER}/demo", "-F"): (0, readback, ""),
    }


def test_settings_only_applies_delete_branch_on_merge_to_existing_repo(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    runner = FakeRunner(_settings_responses())
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
    assert report["status"] == "READY", report
    assert [s["name"] for s in report["steps"]] == ["token_login", "remote_match", "repo_settings"]
    assert not runner.called("gh", "repo", "create") and not runner.called("git")
    assert not runner.called("bash") and not runner.called("python3")
    patches = runner.called("gh", "api", "-X", "PATCH")
    assert len(patches) == 1 and patches[0][0][4:7] == (f"repos/{OWNER}/demo", "-F", "delete_branch_on_merge=true")
    assert TOKEN not in json.dumps(report)


def test_settings_only_blocks_on_visibility_mismatch_or_failed_readback(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    runner = FakeRunner(_settings_responses("private"))
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "remote_match"
    assert not runner.called("gh", "api", "-X", "PATCH")
    report = module.Bootstrapper(plan, FakeRunner(_settings_responses(readback="false\n")), today=TODAY).apply_settings()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["status"] == "fail"


def test_cli_settings_only_requires_confirm_and_skips_description(module, home, tools, capsys) -> None:
    args = ["--name", "demo", "--visibility", "public", "--settings-only", *_cli_tool_args(tools)]
    runner = FakeRunner(_settings_responses())
    assert module.main(args, runner=runner, home=home, env={}, today=TODAY) == 1
    assert not runner.called("gh", "api", "-X", "PATCH")
    capsys.readouterr()
    assert module.main([*args, "--confirm", "--json"], runner=runner, home=home, env={}, today=TODAY) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "settings"
    with pytest.raises(SystemExit):
        module.main(["--name", "demo", "--visibility", "public", *_cli_tool_args(tools)], runner=runner, home=home, env={}, today=TODAY)


def test_settings_only_blocks_without_writing_when_repo_view_fails_or_is_unreadable(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    for view in [(1, "", "HTTP 502"), (0, "[1]", ""), (0, "not json", "")]:
        responses = _settings_responses()
        responses[("gh", "repo", "view")] = view
        runner = FakeRunner(responses)
        report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
        assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "remote_match", (view, report)
        assert not runner.called("gh", "api", "-X", "PATCH")


def test_settings_only_blocks_when_patch_fails(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _settings_responses()
    responses[("gh", "api", "-X", "PATCH", f"repos/{OWNER}/demo", "-F")] = (1, "", "HTTP 403")
    report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).apply_settings()
    assert report["status"] == "BLOCKED" and report["steps"][-1] == {"name": "repo_settings", "status": "fail", "detail": "delete_branch_on_merge: HTTP 403"}


def test_preflight_treats_renamed_away_repository_as_absent(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _fresh(plan.repo_dir)
    responses[("gh", "repo", "view")] = (0, json.dumps({"nameWithOwner": f"{OWNER}/demo-archive", "visibility": "PRIVATE"}), "")
    boot = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY)
    result = boot.preflight()
    assert result["checks"]["remote_absent"] == "ok_renamed_away" and result["status"] == "READY", result
    assert boot._remote is None


def test_preflight_still_blocks_same_name_repository_case_insensitively(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _fresh(plan.repo_dir)
    responses[("gh", "repo", "view")] = (0, json.dumps({"nameWithOwner": f"{OWNER}/DEMO", "visibility": "PUBLIC"}), "")
    result = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).preflight()
    assert result["checks"]["remote_absent"] == "exists" and result["status"] == "BLOCKED"


def test_settings_only_refuses_repository_served_by_redirect(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _settings_responses()
    responses[("gh", "repo", "view")] = (0, json.dumps({"nameWithOwner": f"{OWNER}/demo-archive", "visibility": "PUBLIC"}), "")
    runner = FakeRunner(responses)
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
    assert report["status"] == "BLOCKED" and "転送" in report["steps"][-1]["detail"]
    assert not runner.called("gh", "api", "-X", "PATCH")


def test_execute_creates_new_repository_when_old_name_only_redirects(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _happy_execute(plan, tools)
    responses[("gh", "repo", "view")] = (0, json.dumps({"nameWithOwner": f"{OWNER}/demo-archive", "visibility": "PRIVATE"}), "")
    runner = FakeRunner(responses)
    report = module.Bootstrapper(plan, runner, today=TODAY, resume=True).execute()
    steps = {s["name"]: s for s in report["steps"]}
    assert report["status"] == "READY", report
    assert steps["create_remote"]["status"] == "ok"
    assert runner.called("gh", "repo", "create", f"{OWNER}/demo")


def test_missing_name_with_owner_is_judged_the_same_in_preflight_and_settings(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _fresh(plan.repo_dir)
    responses[("gh", "repo", "view")] = (0, json.dumps({"visibility": "PUBLIC"}), "")
    assert module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).preflight()["checks"]["remote_absent"] == "exists"
    settings = _settings_responses()
    settings[("gh", "repo", "view")] = (0, json.dumps({"visibility": "PUBLIC"}), "")
    assert module.Bootstrapper(plan, FakeRunner(settings), today=TODAY).apply_settings()["status"] == "READY"
