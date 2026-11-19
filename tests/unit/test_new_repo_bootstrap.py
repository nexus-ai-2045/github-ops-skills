"""new-repo-bootstrap: 新規 repository の作成を 1 本の fail-closed 手順にまとめる script のテスト。

gh は runner を差し替えて検査する。token は出力へ出ない。
初期ブランチの push と台帳の登録は、一時ディレクトリの Git リポジトリで動作を確かめる。
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
import shutil
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
REGISTRY_TEXT = "| `repo` | `visibility` | 使う `account` | 根拠 |\n|---|---|---|---|\n| 公開協業 repo 全般 | - | x | y |\n"
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
OVERREACHING_FORMATTER = FAKE_FORMATTER.replace('.replace("（デモ）", "（デモ・整形済み）")', '.replace("使う", "誤り")')
FORMATTED_REGISTRY_TEXT = "| `repo` | `visibility` | 使う `account` | 根拠 |\n|---|---|---|---|\n| 公開協業 `repo` 全般 | - | **`x`** に統一 | y |\n"


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

    台帳用コマンドと real_repo で指定した初期ブランチのコマンドは、一時リポジトリで実行できる。
    """

    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str, str]], *, real_repo: Path | None = None) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[tuple[str, ...], dict]] = []
        self.real_repo = str(real_repo) if real_repo is not None else None

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
        bootstrap_tool = self.real_repo is not None and (
            (argv[0] == "git" and cwd == self.real_repo)
            or (argv[0] == "bash" and argv[2:4] == ("--repo", self.real_repo))
        )
        if argv[:2] == ("git", "-C") or workspace_tool or bootstrap_tool:
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
        ("git", "rev-parse", "--verify", "refs/heads/main"): (0, SHA + "\n", ""),
        ("git", "symbolic-ref"): (1, "", ""),
        ("git", "symbolic-ref", "--quiet", "--no-recurse", "HEAD"): (0, "refs/heads/main\n", ""),
        ("git", "for-each-ref"): (0, f"refs/heads/main\t{SHA}\tcommit\t\n", ""),
        ("git", "worktree", "list"): (0, f"worktree {repo_dir}\0HEAD {SHA}\0branch refs/heads/main\0\0", ""),
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
    checks.update({"ci_configuration": {"status": "pass"}, "origin": {"status": "unknown"}})
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

def test_default_local_root_uses_owner_and_respects_override(module, home) -> None:
    assert module.default_local_root(home, "public", {}) == home / "Projects/repos/nexus_ai"
    assert module.default_local_root(home, "private", {}) == home / "Projects/repos/nexus_ai"
    assert module.default_local_root(home, "public", {"GITHUB_OPS_REPO_ROOT": str(home / "x")}) == home / "x"


def test_other_owner_uses_organization_preflight(module, home):
    scanner = Path("repo-preflight/scripts/readiness_scan.py")
    expected = home / module.DEFAULT_LOCAL_ROOT / scanner
    other = home / module.REPOS_ROOT / "example-owner" / scanner
    for path in (expected, other):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    plan = module.build_plan(owner="example-owner", name="demo", visibility="public",
                             description="demo", home=home, env={},
                             commit_name="Test", commit_email="test@example.invalid")
    assert plan.preflight_script == expected
    assert plan.repo_dir.parent == other.parents[2]


def test_build_plan_identity_and_validation(module, home) -> None:
    plan = _plan(module, home)
    assert plan.repo_dir == home / "Projects/repos/nexus_ai/demo"
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
    assert module.registry_local_path(plan) == "repos/nexus_ai/demo"

    outside = _plan(module, home, repo_dir=tmp_path / "elsewhere" / "demo")
    assert module.registry_local_path(outside).startswith(("~/", "/"))


def test_registry_row_dedup_by_repository_key(module, home) -> None:
    plan = _plan(module, home)
    row = module.registry_row(plan, today=TODAY, include_visibility=True)
    assert row.startswith(f"| `{OWNER}/demo`（デモ） | `public` | **`{OWNER}`** |")
    assert "ローカル: `repos/nexus_ai/demo`" in row
    assert "~/" not in row and str(home) not in row
    text = REGISTRY_TEXT
    updated = module.insert_registry_row(text, plan, today=TODAY)
    assert updated is not None and updated.index(row) < updated.index("| 公開協業 repo 全般")
    assert module.insert_registry_row(updated, plan, today=TODAY) == updated
    assert module.insert_registry_row(updated, plan, today=date(2026, 9, 6)) == updated
    with pytest.raises(module.BootstrapError, match="registry_anchor_missing"):
        module.insert_registry_row("no anchor\n", plan, today=TODAY)


def test_registry_matching_ignores_inline_code_formatting(module, home) -> None:
    """台帳が日本語ゲート向けにコード表記へ整形されても、挿入位置の行と既存行を見失わない。"""
    plan = _plan(module, home)
    row = module.registry_row(plan, today=TODAY, include_visibility=True)
    formatted = FORMATTED_REGISTRY_TEXT
    updated = module.insert_registry_row(formatted, plan, today=TODAY)
    assert updated is not None and updated.index(row) < updated.index("| 公開協業 `repo` 全般")
    assert module.insert_registry_row(updated.replace(f"`{OWNER}/demo`", f"{OWNER}/demo"), plan, today=TODAY).count(f"{OWNER}/demo") == 1
    for other in ("demo.v2", "demo_x", "demo-x"):
        assert not module._is_registry_row_for(f"| `{OWNER}/{other}`（x） |\n", f"{OWNER}/demo")
    assert module._is_registry_row_for(f"| `{OWNER}/demo`の説明 |\n", f"{OWNER}/demo")


@pytest.mark.parametrize(("registry", "expected_cells"), [
    ("| `repo` | 使う `account` | 根拠 |\n|---|---|---|\n"
     "| 公開協業 `repo` 全般 | **`example`** に統一 | 既定の方針 |\n", [f"**`{OWNER}`**"]),
    (FORMATTED_REGISTRY_TEXT, ["`public`", f"**`{OWNER}`**"]),
])
def test_register_uses_the_target_table_header(module, home, tmp_path, tools, registry, expected_cells):
    checkout = _make_workspace(tmp_path / "columns", registry_text=registry)
    plan = _plan(module, home, **{**tools, "registry_file": checkout / REGISTRY_REL})
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    assert boot._register()[0] == "ok"
    result = _git(checkout, "show", f"{boot.registration['branch']}:{REGISTRY_REL}")
    row = next(line for line in result.splitlines() if f"`{plan.nwo}`" in line)
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[1:-1] == expected_cells
    assert result.replace(row + "\n", "") == registry.rstrip("\n")


@pytest.mark.parametrize("registry", [
    REGISTRY_TEXT.replace("使う `account`", "不明"),
    REGISTRY_TEXT.replace("|---|---|---|---|", "|---|---|"),
    REGISTRY_TEXT.replace("| - | x | y |", "| x | y |"),
    REGISTRY_TEXT + REGISTRY_TEXT,
])
def test_register_rejects_unknown_table_before_committing(module, home, tmp_path, tools, registry):
    checkout = _make_workspace(tmp_path / "unknown", registry_text=registry)
    plan = _plan(module, home, **{**tools, "registry_file": checkout / REGISTRY_REL})
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    assert boot._check_registry() == "registry_schema_unknown"
    assert boot._register() == ("fail", "registry_schema_unknown")
    assert not (checkout / ".worktrees").exists()


def test_register_preserves_malformed_existing_row_and_reports_failure(module, home, tmp_path, tools):
    original = ("| `repo` | 使う `account` | 根拠 |\n|---|---|---|\n"
                f"| `{OWNER}/demo` | `private` | **`{OWNER}`** | 既存の登録 |\n"
                "| 公開協業 `repo` 全般 | 既定の名義 | 方針 |\n")
    checkout = _make_workspace(tmp_path / "existing", registry_text=original)
    plan = _plan(module, home, **{**tools, "registry_file": checkout / REGISTRY_REL})
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY)
    assert boot._register() == ("fail", "registry_row_invalid")
    assert (checkout / REGISTRY_REL).read_text() == original
    assert not (checkout / ".worktrees").exists()


@pytest.mark.parametrize("fence", ["```", "~~~~"])
def test_registry_ignores_code_examples(module, home, fence):
    plan = _plan(module, home)
    example = f"{fence}markdown\n{REGISTRY_TEXT}{fence}\n"
    with pytest.raises(module.BootstrapError, match="registry_anchor_missing"):
        module.insert_registry_row(example, plan, today=TODAY)
    updated = module.insert_registry_row(example + REGISTRY_TEXT, plan, today=TODAY)
    assert updated.startswith(example)
    assert updated.removeprefix(example).count(plan.nwo) == 1


def test_registered_row_with_escaped_pipe_is_preserved(module, home):
    plan = _plan(module, home)
    registered = REGISTRY_TEXT.replace("| 公開協業", f"| `{plan.nwo}` | public | 登録名義 | 原文 A \\| B |\n| 公開協業")
    assert module.insert_registry_row(registered, plan, today=TODAY) == registered


def test_register_works_on_registry_already_formatted_for_japanese_gate(module, home, tmp_path, tools) -> None:
    checkout = _make_workspace(tmp_path / "formatted", registry_text=FORMATTED_REGISTRY_TEXT)
    plan = _plan(module, home, **{**tools, "registry_file": checkout / REGISTRY_REL})
    boot = module.Bootstrapper(plan, FakeRunner(_fresh(plan.repo_dir)), today=TODAY)
    assert boot.preflight()["checks"]["registry_file"] == "ok"
    status, detail = boot._register()
    assert status == "ok", detail
    shown = _git(checkout, "show", f"{boot.registration['branch']}:{REGISTRY_REL}")
    assert shown.index(module.registry_row(plan, today=TODAY, include_visibility=True)) < shown.index("| 公開協業 `repo` 全般")


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
    assert module.registry_row(plan, today=TODAY, include_visibility=True) in _git(checkout, "show", f"{branch}:{REGISTRY_REL}")
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
    registered = module.insert_registry_row(REGISTRY_TEXT, plan, today=TODAY)
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

@pytest.fixture
def bootstrap_git(module, home, tools, tmp_path):  # noqa: ANN201
    plan = _plan(module, home, **tools)
    remote = tmp_path / "bootstrap-remote.git"
    assert _run_real(["git", "init", "-q", "--bare", "-b", "main", str(remote)])[0] == 0
    plan.repo_dir.mkdir(parents=True)
    _git(plan.repo_dir, "init", "-q", "-b", "main")
    _git(plan.repo_dir, "config", "user.name", plan.commit_name)
    _git(plan.repo_dir, "config", "user.email", plan.commit_email)
    _git(plan.repo_dir, "commit", "-q", "--allow-empty", "-m", "initial")
    plan.push_wrapper.write_text(
        '#!/bin/sh\nset -eu\n'
        '[ "$1" = "--repo" ] && [ "$3" = "--branch" ]\n'
        '[ "$(git -C "$2" branch --show-current)" = "$4" ]\n'
        f'git -C "$2" push -q "{remote}" "$4"\n',
        encoding="utf-8",
    )
    responses = {args: result for args, result in _fresh(plan.repo_dir).items() if args[0] == "gh"}
    runner = FakeRunner(responses, real_repo=plan.repo_dir)
    return plan, remote, runner


@pytest.mark.parametrize("existing_init", ["absent", "available", "checked-out"])
def test_push_reuses_matching_init_and_returns_to_main(module, bootstrap_git, existing_init) -> None:
    plan, remote, runner = bootstrap_git
    repo = plan.repo_dir
    sha = _git(repo, "rev-parse", "HEAD")
    if existing_init != "absent":
        _git(repo, "branch", module.INIT_BRANCH)
    if existing_init == "checked-out":
        _git(repo, "switch", module.INIT_BRANCH)

    boot = module.Bootstrapper(plan, runner, today=TODAY, resume=existing_init != "absent")
    status, detail = boot._push()
    assert status == "ok", detail
    assert _git(remote, "rev-parse", module.INIT_REF) == sha
    assert _git(repo, "rev-parse", module.MAIN_REF, module.INIT_REF).splitlines() == [sha, sha]
    assert _git(repo, "branch", "--show-current") == "main"
    assert _git(repo, "status", "--porcelain") == ""
    assert not runner.called("git", "branch", "-f")


@pytest.mark.parametrize("state,reason", [
    ("detached", "チェックアウトしてください"),
    ("unrelated", "チェックアウトしてください"),
    ("diverged", "一致しません"),
    ("diverged-checked-out", "一致しません"),
    ("occupied-init", "別の作業ツリー"),
    ("occupied-main", "別の作業ツリー"),
    ("symbolic", "直接参照"),
    ("dangling-symbolic", "参照"),
    ("missing-main", "一致しません"),
    ("collision", "衝突"),
])
def test_invalid_initial_branches_block_before_writes(module, bootstrap_git, tmp_path, state, reason) -> None:
    plan, remote, runner = bootstrap_git
    repo = plan.repo_dir
    if state == "collision":
        _git(repo, "branch", f"{module.INIT_BRANCH}/child")
    elif state == "symbolic":
        _git(repo, "symbolic-ref", module.INIT_REF, module.MAIN_REF)
    elif state == "dangling-symbolic":
        _git(repo, "symbolic-ref", module.INIT_REF, "refs/heads/missing")
    else:
        _git(repo, "branch", module.INIT_BRANCH)
    if state == "detached":
        _git(repo, "switch", "--detach")
    elif state == "unrelated":
        _git(repo, "switch", "-c", "unrelated")
    elif state == "missing-main":
        _git(repo, "switch", module.INIT_BRANCH)
        _git(repo, "branch", "-d", "main")
    elif state.startswith("diverged"):
        _git(repo, "switch", module.INIT_BRANCH)
        _git(repo, "commit", "-q", "--allow-empty", "-m", "diverged")
        if state == "diverged":
            _git(repo, "switch", "main")
    elif state.startswith("occupied"):
        if state == "occupied-main":
            _git(repo, "switch", module.INIT_BRANCH)
        branch = "main" if state == "occupied-main" else module.INIT_BRANCH
        _git(repo, "worktree", "add", str(tmp_path / "other\nworktree"), branch)
    refs_before = _git(repo, "for-each-ref")
    worktrees_before = _git(repo, "worktree", "list", "--porcelain", "-z")

    boot = module.Bootstrapper(plan, runner, today=TODAY, resume=True)
    report = boot.execute()
    assert reason in report["preflight"]["initial_branches"]
    assert report["status"] == "BLOCKED"
    assert len(report["steps"]) == 1
    assert boot._push()[0] == "fail"
    assert not runner.called("git", "switch") and not runner.called("git", "config", "user.name")
    assert not runner.called("bash") and not runner.called("gh", "repo", "create")
    assert _git(repo, "for-each-ref") == refs_before
    assert _git(repo, "worktree", "list", "--porcelain", "-z") == worktrees_before
    assert _git(remote, "for-each-ref") == ""


def test_failed_wrapper_reports_known_reasons_without_replaying_outputs(module, bootstrap_git) -> None:
    plan, remote, runner = bootstrap_git
    repo = plan.repo_dir
    _git(repo, "switch", "-c", module.INIT_BRANCH)
    runner.responses[("bash", str(plan.push_wrapper))] = (
        7,
        f'{{"status":"blocked","code":"managed_public_readiness_unverified","secret":"{TOKEN}"}}',
        f"[cc-push-resolved] ERROR: canonical public readiness denied the operation {TOKEN}\n",
    )
    boot = module.Bootstrapper(plan, runner, today=TODAY, resume=True)
    status, detail = boot._push()
    assert status == "fail" and "rc=7" in detail
    assert "canonical public readiness denied the operation" in detail
    assert "managed_public_readiness_unverified" in detail
    assert TOKEN not in detail
    assert _git(repo, "branch", "--show-current") == "main"
    assert boot._promote_main()[0] == "fail"
    assert not runner.called("gh", "api", "-X", "POST")
    assert _git(remote, "for-each-ref") == ""


def test_wrapper_timeout_restores_main_without_reporting_subprocess_output(module, bootstrap_git, monkeypatch) -> None:
    plan, remote, runner = bootstrap_git
    run = runner.run

    def timeout_wrapper(argv, **kwargs):  # noqa: ANN001, ANN202
        if argv[:2] == ["bash", str(plan.push_wrapper)]:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=TOKEN, stderr=TOKEN)
        return run(argv, **kwargs)

    monkeypatch.setattr(runner, "run", timeout_wrapper)
    boot = module.Bootstrapper(plan, runner, today=TODAY)
    status, detail = boot._push()
    assert status == "fail" and "タイムアウト" in detail and TOKEN not in detail
    assert _git(plan.repo_dir, "branch", "--show-current") == "main"
    assert _git(remote, "for-each-ref") == ""


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


def _created_with_protection_pending(module, report) -> bool:  # noqa: ANN001
    """公開の新規作成は、保護の段だけが未適用で止まり、それ以外の段は通る。"""
    *done, last = report["steps"]
    return (report["status"] == "BLOCKED" and all(s["status"] in {"ok", "skipped"} for s in done)
            and last["name"] == "branch_protection" and module.PROTECTION_LATER in last["detail"])


def test_execute_order_lockdown_before_push_and_main_promotion(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    runner = FakeRunner(_happy_execute(plan, tools))
    report = module.Bootstrapper(plan, runner, today=TODAY).execute()
    assert _created_with_protection_pending(module, report), report
    names = [s["name"] for s in report["steps"]]
    assert names == ["preflight", *module.STEP_ORDER]
    assert names.index("lockdown") < names.index("push")
    assert names.index("create_remote") < names.index("repo_settings") < names.index("push")
    settings = runner.called("gh", "api", "-X", "PATCH", f"repos/{OWNER}/demo", "-F")
    assert settings and settings[0][0][6] == "delete_branch_on_merge=true" and settings[0][1]["scoped_env"]["GH_TOKEN"] == TOKEN
    assert all(s["status"] in {"ok", "skipped"} for s in report["steps"][:-1])
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
    assert _created_with_protection_pending(module, report), report


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


@pytest.mark.parametrize("post", [(0, "{}", ""), (1, "", "Reference already exists")])
@pytest.mark.parametrize("readback,reason", [
    ((0, SHA + "\n", ""), ""),
    ((0, "b" * 40 + "\n", ""), "一致しない"),
    ((1, SHA + "\n", "Not Found"), "取得できない"),
    ((0, "", ""), "取得できない"),
])
def test_main_promotion_checks_remote_sha_before_changing_default_or_deleting_init(
    module, home, tools, post, readback, reason,
) -> None:
    plan = _plan(module, home, **tools)
    responses = _happy_execute(plan, tools)
    create = ("gh", "api", "-X", "POST", f"repos/{plan.nwo}/git/refs")
    read = ("gh", "api", f"repos/{plan.nwo}/branches/main")
    default = ("gh", "api", "-X", "PATCH", f"repos/{plan.nwo}", "-f", "default_branch=main")
    delete = ("gh", "api", "-X", "DELETE", f"repos/{plan.nwo}/git/refs/heads/{module.INIT_BRANCH}")
    responses[create] = post
    responses[read] = readback
    runner = FakeRunner(responses)

    report = module.Bootstrapper(plan, runner, today=TODAY, resume=True).execute()
    calls = runner.calls
    assert calls.index(runner.called(*create)[0]) < calls.index(runner.called(*read)[0])
    if reason:
        assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "promote_main"
        assert reason in report["steps"][-1]["detail"]
        assert not runner.called(*default) and not runner.called(*delete)
        assert not runner.called("git", "branch", "-d") and not runner.called("git", "update-ref")
    else:
        assert _created_with_protection_pending(module, report), report
        assert calls.index(runner.called(*read)[0]) < calls.index(runner.called(*default)[0]) < calls.index(runner.called(*delete)[0])


def test_verify_requires_remote_main_matching_local_head(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _happy_execute(plan, tools)
    responses[("gh", "api", f"repos/{OWNER}/demo/branches/main")] = (1, "", "Not Found")
    report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY, resume=True, skip_push=True).execute()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "verify" and "取得できない" in report["steps"][-1]["detail"]
    responses[("gh", "api", f"repos/{OWNER}/demo/branches/main")] = (0, "b" * 40 + "\n", "")
    report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY, resume=True, skip_push=True).execute()
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

LOCKDOWN_SCANNING_QUERY = "[.security_and_analysis.secret_scanning.status, .security_and_analysis.secret_scanning_push_protection.status] | join(\" \")"


def _settings_responses(visibility: str = "public", readback: str = "true\n", lockdown_readback: str = "enabled enabled\n",
                        reporting_readback: str = "true\n") -> dict:
    return {
        ("gh", "auth", "token"): (0, TOKEN + "\n", ""),
        ("gh", "api", "user"): (0, OWNER + "\n", ""),
        **_remote(visibility),
        ("gh", "api", "-X", "PATCH", f"repos/{OWNER}/demo", "-F"): (0, readback, ""),
        ("gh", "api", f"repos/{OWNER}/demo", "--jq", LOCKDOWN_SCANNING_QUERY): (0, lockdown_readback, ""),
        ("gh", "api", f"repos/{OWNER}/demo/private-vulnerability-reporting", "--jq", ".enabled"): (0, reporting_readback, ""),
    }


def test_settings_only_applies_delete_branch_on_merge_to_existing_repo(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    runner = FakeRunner(_settings_responses())
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
    assert report["status"] == "READY", report
    assert [s["name"] for s in report["steps"]] == ["token_login", "remote_match", "repo_settings", "lockdown"]
    assert not runner.called("gh", "repo", "create") and not runner.called("git")
    assert not runner.called("bash") and not runner.called("python3")
    patches = runner.called("gh", "api", "-X", "PATCH")
    assert patches[0][0][4:7] == (f"repos/{OWNER}/demo", "-F", "delete_branch_on_merge=true")
    assert TOKEN not in json.dumps(report)


def test_settings_only_applies_public_lockdown_to_existing_public_repo(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    runner = FakeRunner(_settings_responses())
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
    assert report["status"] == "READY", report
    assert report["steps"][-1]["name"] == "lockdown" and report["steps"][-1]["status"] == "ok", report
    patches = [call[0] for call in runner.called("gh", "api", "-X", "PATCH")]
    assert len(patches) == 2
    assert patches[1][4:] == (
        f"repos/{OWNER}/demo",
        "-f", "security_and_analysis[secret_scanning][status]=enabled",
        "-f", "security_and_analysis[secret_scanning_push_protection][status]=enabled",
    )
    puts = [call[0] for call in runner.called("gh", "api", "-X", "PUT")]
    assert [put[4] for put in puts] == [f"repos/{OWNER}/demo/private-vulnerability-reporting"]
    order = [call[0] for call in runner.calls]
    readback = next(i for i, argv in enumerate(order) if argv[-1] == LOCKDOWN_SCANNING_QUERY)
    assert order.index(patches[1]) < order.index(puts[0]) < readback
    assert TOKEN not in json.dumps(report)
    assert all("visibility" not in " ".join(call[0]) for call in runner.called("gh", "api", "-X"))
    assert not runner.called("gh", "repo", "edit")


def test_settings_only_skips_lockdown_for_private_repo(module, home, tools) -> None:
    plan = _plan(module, home, visibility="private", **tools)
    runner = FakeRunner(_settings_responses("private"))
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
    assert report["status"] == "READY", report
    assert report["steps"][-1]["name"] == "lockdown" and report["steps"][-1]["status"] == "skipped"
    assert len(runner.called("gh", "api", "-X", "PATCH")) == 1
    assert not runner.called("gh", "api", "-X", "PUT")


def test_settings_only_blocks_when_lockdown_write_fails(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    for failing in [
        ("gh", "api", "-X", "PATCH", f"repos/{OWNER}/demo", "-f"),
        ("gh", "api", "-X", "PUT", f"repos/{OWNER}/demo/private-vulnerability-reporting"),
    ]:
        responses = _settings_responses()
        responses[failing] = (1, "", "HTTP 403")
        report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).apply_settings()
        assert report["status"] == "BLOCKED", (failing, report)
        assert report["steps"][-1]["name"] == "lockdown" and report["steps"][-1]["status"] == "fail"
        assert "HTTP 403" in report["steps"][-1]["detail"]
        assert TOKEN not in json.dumps(report)
    responses = _settings_responses()
    responses[("gh", "api", "-X", "PATCH", f"repos/{OWNER}/demo", "-f")] = (1, "", "HTTP 403")
    runner = FakeRunner(responses)
    module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
    assert not runner.called("gh", "api", "-X", "PUT")


def test_settings_only_blocks_when_lockdown_readback_is_not_enabled(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    for kwargs in [
        {"lockdown_readback": "enabled disabled\n"},
        {"lockdown_readback": "disabled enabled\n"},
        {"lockdown_readback": "\n"},
        {"reporting_readback": "false\n"},
        {"reporting_readback": "\n"},
        {"reporting_readback": "null\n"},
    ]:
        report = module.Bootstrapper(plan, FakeRunner(_settings_responses(**kwargs)), today=TODAY).apply_settings()
        assert report["status"] == "BLOCKED", (kwargs, report)
        assert report["steps"][-1]["name"] == "lockdown" and report["steps"][-1]["status"] == "fail"
    responses = _settings_responses()
    responses[("gh", "api", f"repos/{OWNER}/demo", "--jq", LOCKDOWN_SCANNING_QUERY)] = (1, "", "HTTP 502")
    report = module.Bootstrapper(plan, FakeRunner(responses), today=TODAY).apply_settings()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["status"] == "fail"


def test_settings_only_does_not_start_lockdown_when_repo_settings_fail(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _settings_responses()
    responses[("gh", "api", "-X", "PATCH", f"repos/{OWNER}/demo", "-F")] = (1, "", "HTTP 403")
    runner = FakeRunner(responses)
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "repo_settings"
    assert not runner.called("gh", "api", "-X", "PUT")


def test_settings_only_blocks_on_visibility_mismatch_or_failed_readback(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    runner = FakeRunner(_settings_responses("private"))
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "remote_match"
    assert not runner.called("gh", "api", "-X")
    report = module.Bootstrapper(plan, FakeRunner(_settings_responses(readback="false\n")), today=TODAY).apply_settings()
    assert report["status"] == "BLOCKED" and report["steps"][-1]["status"] == "fail"


def test_cli_settings_only_requires_confirm_and_skips_description(module, home, tools, capsys) -> None:
    args = ["--name", "demo", "--visibility", "public", "--settings-only", *_cli_tool_args(tools)]
    runner = FakeRunner(_settings_responses())
    assert module.main(args, runner=runner, home=home, env={}, today=TODAY) == 1
    assert not runner.called("gh", "api", "-X")
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
        assert not runner.called("gh", "api", "-X")


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
    assert not runner.called("gh", "api", "-X")


def test_execute_creates_new_repository_when_old_name_only_redirects(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    responses = _happy_execute(plan, tools)
    responses[("gh", "repo", "view")] = (0, json.dumps({"nameWithOwner": f"{OWNER}/demo-archive", "visibility": "PRIVATE"}), "")
    runner = FakeRunner(responses)
    report = module.Bootstrapper(plan, runner, today=TODAY, resume=True).execute()
    steps = {s["name"]: s for s in report["steps"]}
    assert _created_with_protection_pending(module, report), report
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


# ---------- 既定の枝の保護: repo-preflight の関門の計画を当てる ----------

PROTECT_CHECKS = ("verify", "gate / preflight", "validate")
PROTECTION_PATH = f"repos/{OWNER}/demo/branches/main/protection"
READBACK_JQ = "[.enforce_admins.enabled] | tojson"
FAKE_GATE = "print('fake gate')\n"
EXISTING = {"enforce_admins": {"enabled": False}, "allow_force_pushes": {"enabled": False}}


def _gate_plan(state: str, checks=PROTECT_CHECKS, *, basis_state="absent", basis_sha=None, reasons=()) -> dict:  # noqa: ANN001
    expected = [True, 0, True, False, False, sorted(checks)]
    body = {"enforce_admins": True, "required_status_checks": {"strict": False, "checks": [{"context": c} for c in checks]}}
    return {
        "schema_version": "repo-preflight.branch-protection-plan/v1",
        "repository": f"{OWNER}/demo",
        "required_checks": list(checks),
        "default_branch": "main",
        "state": state,
        "blocked_reasons": list(reasons),
        "basis": None if state == "blocked" else {"endpoint": PROTECTION_PATH, "state": basis_state, "sha256": basis_sha},
        "operation": {"method": "PUT", "endpoint": PROTECTION_PATH, "body": body} if state in {"create", "overlay"} else None,
        "readback": None if state == "blocked" else {"endpoint": PROTECTION_PATH, "jq": READBACK_JQ, "expected": expected},
    }


class GateRunner(FakeRunner):
    """関門の実行を横取りし、PUT の本文と書き込みの前後の読み戻しを扱う。"""

    def __init__(self, responses, gate_plan, *, readback=None, gate_root=None):  # noqa: ANN001
        super().__init__(responses)
        self.gate_plan = gate_plan
        self.readback = readback
        self.gate_root = gate_root
        self.gate_calls: list[tuple[tuple[str, ...], dict]] = []
        self.bodies: list[dict] = []

    def run(self, argv, *, cwd=None, scoped_env=None, timeout=30):  # noqa: ANN001
        argv = tuple(argv)
        if argv[:1] == ("python3",) and len(argv) > 2 and argv[2] == "protection-plan":
            self.gate_calls.append((argv, dict(scoped_env or {})))
            return (0 if self.gate_plan["state"] != "blocked" else 1, json.dumps(self.gate_plan, ensure_ascii=False), "")
        if argv[:5] == ("gh", "api", "-X", "PUT", PROTECTION_PATH):
            self.bodies.append(json.loads(Path(argv[argv.index("--input") + 1]).read_text(encoding="utf-8")))
        if argv == ("gh", "api", PROTECTION_PATH, "--jq", READBACK_JQ):
            self.calls.append((argv, {"cwd": cwd, "scoped_env": dict(scoped_env or {})}))
            readback = self.readback if self.readback is not None else json.dumps(self.gate_plan["readback"]["expected"], ensure_ascii=False)
            return (0, readback + "\n", "")
        return super().run(argv, cwd=cwd, scoped_env=scoped_env, timeout=timeout)


@pytest.fixture
def pinned_gate(module, monkeypatch, tools):  # noqa: ANN001, ANN201
    monkeypatch.setattr(module, "GATE_SCRIPT_BLOB", module.git_blob_id(FAKE_GATE.encode("utf-8")))
    root = str(tools["preflight_script"].parents[1])
    return {("git", "-C", root, "cat-file", "blob", module.GATE_SCRIPT_BLOB): (0, FAKE_GATE, "")}


def _protect_responses(pinned_gate, *, current=(1, "", "gh: Branch not protected (HTTP 404)")) -> dict:  # noqa: ANN001
    return {
        **_settings_responses(),
        **pinned_gate,
        ("gh", "api", PROTECTION_PATH): current,
        ("gh", "api", "-X", "PUT", PROTECTION_PATH): (0, "{}", ""),
    }


def test_git_blob_id_matches_git(module, tmp_path) -> None:
    path = tmp_path / "gate.py"
    path.write_bytes(FAKE_GATE.encode("utf-8"))
    assert module.git_blob_id(FAKE_GATE.encode("utf-8")) == _run_real(["git", "hash-object", str(path)])[1].strip()


def test_settings_only_applies_gate_create_plan_and_reads_back(module, home, tools, pinned_gate) -> None:
    plan = _plan(module, home, **tools)
    gate_plan = _gate_plan("create")
    runner = GateRunner(_protect_responses(pinned_gate), gate_plan)
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings(protect_checks=PROTECT_CHECKS)
    assert report["status"] == "READY", report
    assert [s["name"] for s in report["steps"]][-2:] == ["lockdown", "branch_protection"]
    assert runner.bodies == [gate_plan["operation"]["body"]]
    gate_argv, gate_env = runner.gate_calls[0]
    assert gate_argv[3:] == ("--repository", f"{OWNER}/demo", "--profile", "solo_public", "--expected-login", OWNER,
                             "--require-check", "verify", "--require-check", "gate / preflight", "--require-check", "validate")
    assert gate_env["GH_TOKEN"] == TOKEN
    assert not Path(gate_argv[1]).exists()
    order = [call[0] for call in runner.calls]
    lockdown_put = next(i for i, a in enumerate(order) if a[:4] == ("gh", "api", "-X", "PUT") and a[4].endswith("private-vulnerability-reporting"))
    protect_put = next(i for i, a in enumerate(order) if a[:5] == ("gh", "api", "-X", "PUT", PROTECTION_PATH))
    assert lockdown_put < protect_put
    assert "新しく当てた" in report["steps"][-1]["detail"] and "管理者も対象=True" in report["steps"][-1]["detail"]
    assert TOKEN not in json.dumps(report)


def test_overlay_plan_is_written_only_when_current_protection_matches_its_basis(module, home, tools, pinned_gate) -> None:
    plan = _plan(module, home, **tools)
    current = (0, json.dumps(EXISTING), "")
    gate_plan = _gate_plan("overlay", basis_state="present", basis_sha=module.protection_digest(EXISTING))
    runner = GateRunner(_protect_responses(pinned_gate, current=current), gate_plan)
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings(protect_checks=PROTECT_CHECKS)
    assert report["status"] == "READY", report
    assert "既存の保護に重ねた" in report["steps"][-1]["detail"]
    changed = (0, json.dumps({**EXISTING, "allow_deletions": {"enabled": True}}), "")
    runner = GateRunner(_protect_responses(pinned_gate, current=changed), gate_plan)
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings(protect_checks=PROTECT_CHECKS)
    assert report["status"] == "BLOCKED" and "計画を取り直す" in report["steps"][-1]["detail"]
    assert not runner.called("gh", "api", "-X", "PUT", PROTECTION_PATH)


def test_create_plan_is_not_written_when_protection_appeared_meanwhile(module, home, tools, pinned_gate) -> None:
    plan = _plan(module, home, **tools)
    runner = GateRunner(_protect_responses(pinned_gate, current=(0, json.dumps(EXISTING), "")), _gate_plan("create"))
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings(protect_checks=PROTECT_CHECKS)
    assert report["status"] == "BLOCKED"
    assert not runner.called("gh", "api", "-X", "PUT", PROTECTION_PATH)


def test_noop_plan_reads_back_without_writing(module, home, tools, pinned_gate) -> None:
    plan = _plan(module, home, **tools)
    runner = GateRunner(_protect_responses(pinned_gate), _gate_plan("noop", basis_state="present", basis_sha="x"))
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings(protect_checks=PROTECT_CHECKS)
    assert report["status"] == "READY" and "書き込みなし" in report["steps"][-1]["detail"], report
    assert not runner.called("gh", "api", "-X", "PUT", PROTECTION_PATH)
    assert runner.called("gh", "api", PROTECTION_PATH, "--jq", READBACK_JQ)


def test_blocked_plan_writes_nothing_and_reports_gate_reasons(module, home, tools, pinned_gate) -> None:
    plan = _plan(module, home, **tools)
    reason = "checks_not_observed_on_recent_merged_pr_heads:validate"
    runner = GateRunner(_protect_responses(pinned_gate), _gate_plan("blocked", reasons=(reason,)))
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings(protect_checks=PROTECT_CHECKS)
    assert report["status"] == "BLOCKED" and reason in report["steps"][-1]["detail"]
    assert not runner.called("gh", "api", "-X", "PUT", PROTECTION_PATH)


@pytest.mark.parametrize("readback", ['[false, 0, true, false, false, ["gate / preflight", "validate", "verify"]]', "not json"])
def test_readback_mismatch_blocks(module, home, tools, pinned_gate, readback) -> None:
    plan = _plan(module, home, **tools)
    runner = GateRunner(_protect_responses(pinned_gate), _gate_plan("create"), readback=readback)
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings(protect_checks=PROTECT_CHECKS)
    assert report["status"] == "BLOCKED" and "読み戻し" in report["steps"][-1]["detail"]


def test_non_ascii_check_names_round_trip_through_plan_and_readback(module, home, tools, pinned_gate) -> None:
    plan = _plan(module, home, **tools)
    checks = ("題の検査", "verify")
    runner = GateRunner(_protect_responses(pinned_gate), _gate_plan("create", checks))
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings(protect_checks=checks)
    assert report["status"] == "READY", report


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(schema_version="other/v1"),
        lambda p: p.update(repository="someone/else"),
        lambda p: p.update(required_checks=["verify"]),
        lambda p: p.update(state="maybe"),
        lambda p: p["operation"].update(endpoint=f"repos/{OWNER}/other/branches/main/protection"),
        lambda p: p["operation"].update(endpoint=f"repos/{OWNER}/demo/rulesets"),
        lambda p: p.update(operation=None),
    ],
)
def test_malformed_or_foreign_plan_is_refused(module, home, tools, pinned_gate, mutate) -> None:
    plan = _plan(module, home, **tools)
    gate_plan = _gate_plan("create")
    mutate(gate_plan)
    runner = GateRunner(_protect_responses(pinned_gate), gate_plan)
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings(protect_checks=PROTECT_CHECKS)
    assert report["status"] == "BLOCKED" and report["steps"][-1]["name"] == "branch_protection"
    assert not runner.called("gh", "api", "-X", "PUT")[-1:] or runner.called("gh", "api", "-X", "PUT")[-1][0][4] != PROTECTION_PATH


def test_gate_must_match_the_pinned_blob(module, home, tools, pinned_gate) -> None:
    plan = _plan(module, home, **tools)
    responses = _protect_responses(pinned_gate)
    responses[next(iter(pinned_gate))] = (0, FAKE_GATE + "# changed\n", "")
    runner = GateRunner(responses, _gate_plan("create"))
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings(protect_checks=PROTECT_CHECKS)
    assert report["status"] == "BLOCKED" and "固定した版の関門" in report["steps"][-1]["detail"]
    assert not runner.gate_calls


def test_settings_only_without_protect_flag_does_not_touch_protection(module, home, tools, pinned_gate) -> None:
    plan = _plan(module, home, **tools)
    runner = GateRunner(_protect_responses(pinned_gate), _gate_plan("create"))
    report = module.Bootstrapper(plan, runner, today=TODAY).apply_settings()
    assert report["status"] == "READY"
    assert "branch_protection" not in [s["name"] for s in report["steps"]]
    assert not runner.gate_calls and not any("/branches/" in " ".join(call[0]) for call in runner.calls)


def test_execute_public_without_checks_registers_but_reports_protection_pending(module, home, tools) -> None:
    plan = _plan(module, home, **tools)
    runner = FakeRunner(_happy_execute(plan, tools))
    report = module.Bootstrapper(plan, runner, today=TODAY).execute()
    assert report["status"] == "BLOCKED"
    assert [s["name"] for s in report["steps"]] == ["preflight", *module.STEP_ORDER]
    assert all(s["status"] in {"ok", "skipped"} for s in report["steps"][:-1])
    assert report["steps"][-1]["status"] == "fail" and "--protect-main" in report["steps"][-1]["detail"]
    assert report["registration"] and report["next"] == module.REGISTRATION_NEXT


def test_execute_public_uses_the_same_gate_plan(module, home, tools, pinned_gate) -> None:
    plan = _plan(module, home, **tools)
    responses = {**_happy_execute(plan, tools), **pinned_gate,
                 ("gh", "api", PROTECTION_PATH): (1, "", "gh: Branch not protected (HTTP 404)")}
    runner = GateRunner(responses, _gate_plan("create"))
    report = module.Bootstrapper(plan, runner, today=TODAY, protect_checks=PROTECT_CHECKS).execute()
    assert report["status"] == "READY", report
    assert report["steps"][-1]["name"] == "branch_protection" and runner.bodies


def test_execute_public_new_repository_is_blocked_by_gate_until_a_pr_merges(module, home, tools, pinned_gate) -> None:
    plan = _plan(module, home, **tools)
    reason = "check_evidence_unavailable:no_recent_merged_pull_request"
    runner = GateRunner({**_happy_execute(plan, tools), **pinned_gate}, _gate_plan("blocked", reasons=(reason,)))
    report = module.Bootstrapper(plan, runner, today=TODAY, protect_checks=PROTECT_CHECKS).execute()
    assert report["status"] == "BLOCKED" and reason in report["steps"][-1]["detail"]
    assert "--settings-only" in report["steps"][-1]["detail"]
    assert report["registration"]
    assert not runner.called("gh", "api", "-X", "PUT", PROTECTION_PATH)


def test_execute_private_skips_protection(module, home, tools) -> None:
    plan = _plan(module, home, visibility="private", **tools)
    boot = module.Bootstrapper(plan, FakeRunner({}), today=TODAY, protect_checks=PROTECT_CHECKS)
    assert boot._execute_protection()[0] == "skipped"


def test_cli_protect_main_needs_checks_and_a_write_mode(module, home, tools) -> None:
    base = ["--name", "demo", "--visibility", "public", *_cli_tool_args(tools)]
    runner = FakeRunner(_settings_responses())
    with pytest.raises(SystemExit):
        module.main([*base, "--description", "デモ", "--protect-main", "--require-check", "verify"], runner=runner, home=home, env={}, today=TODAY)
    with pytest.raises(SystemExit):
        module.main([*base, "--settings-only", "--confirm", "--protect-main"], runner=runner, home=home, env={}, today=TODAY)
    with pytest.raises(SystemExit):
        module.main([*base, "--settings-only", "--confirm", "--require-check", "verify"], runner=runner, home=home, env={}, today=TODAY)
    assert not runner.called("gh", "api", "-X")


def test_cli_rejects_empty_or_duplicate_check_names(module, home, tools) -> None:
    base = ["--name", "demo", "--visibility", "public", "--settings-only", "--confirm", "--protect-main", *_cli_tool_args(tools)]
    runner = FakeRunner(_settings_responses())
    for extra in (["--require-check", ""], ["--require-check", " verify"], ["--require-check", "verify", "--require-check", "verify"]):
        with pytest.raises(SystemExit):
            module.main([*base, *extra], runner=runner, home=home, env={}, today=TODAY)
    assert not runner.called("gh", "api", "-X")
