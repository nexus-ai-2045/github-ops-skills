#!/usr/bin/env python3
"""新規 GitHub repository の作成を 1 本の fail-closed 手順にまとめる。

置き場所の固定、commit 名義の設定、公開前文書の雛形、repo-preflight 検査、
owner の token だけを使った GitHub 作成、公開直後の lockdown、canonical wrapper 経由の
作業 branch push と API による main 昇格、作成結果の read-back、台帳登録 branch の commit を順番に行う。

- 既定は preflight のみ (read-only)。`--confirm` が無い限り何も書かない。
- 台帳を持つ repository の main checkout には書かない。origin/main から切った専用 worktree の branch に
  commit するところまでを行い、その branch の push と PR は SKILL の手順で canonical wrapper から出す。
- global の `gh` active account は切り替えない。owner の token を対象 process の env にだけ渡す。
- token を file・引数・出力へ残さない。
- main へ直接 push しない。`bootstrap/init` branch を push し、GitHub API でその commit から main を作る
  (push 側の 2 つの guard は branch push しか許可しないため。空 remote に main を置く唯一の経路)。
- どこかで止まったら、それ以降の step は実行しない (fail-closed)。
- 標準ライブラリだけで動く (runtime copy 単体で実行できる)。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

KNOWN_IDENTITIES: dict[str, tuple[str, str]] = {
    "nexus-ai-2045": ("nexus_ai", "273569186+nexus-ai-2045@users.noreply.github.com"),
}
WORKSPACE_ROOT = Path("Projects")
DEFAULT_LOCAL_ROOT = WORKSPACE_ROOT / "Documents/.repos/nexus_ai"
DEFAULT_REGISTRY = Path("Projects/Documents/references/github-account-repo-map.md")
DEFAULT_PUSH_WRAPPER = Path("Projects/shared/scripts/cc-push-resolved.sh")
REGISTRY_ANCHOR = "| 公開協業 repo 全般"
# 台帳を持つ workspace repository 側の約束。登録は origin/main から切った専用 worktree の branch に commit する
REGISTER_BRANCH_PREFIX = "bootstrap/register-"
REGISTER_WORKTREE_DIR = ".worktrees"                     # main checkout 直下。.gitignore 済みであること
REGISTRY_COMMIT_WRAPPER = "shared/scripts/cc-commit.sh"  # commit 入口。登録用 worktree にある版を使う
REGISTRY_COMMIT_TARGET = "projects"                      # commit 入口の第 1 引数
REGISTRY_COMMIT_DIR_ENV = "CC_COMMIT_PROJECTS_DIR"       # commit 入口に worktree を指定する env
REGISTRATION_NEXT = "台帳登録の branch を canonical wrapper で push し、PR を作る (SKILL の「台帳登録を PR にして」)"
INIT_BRANCH = "bootstrap/init"
SCAN_REQUIRED_CHECKS = ("required_documents", "secret_scan", "personal_path_scan", "commit_identity")
SCAN_ACCEPTED = {"pass", "not_applicable"}
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SCAFFOLD_ORDER = ("LICENSE", "README.md", "SECURITY.md", "PREFLIGHT.md", "CONTRIBUTING.md", ".gitignore")
STEP_ORDER = (
    "prepare_local", "set_identity", "scaffold_docs", "initial_commit", "readiness_scan",
    "create_remote", "lockdown", "add_remote", "push", "promote_main", "verify", "register",
)


class BootstrapError(ValueError):
    """plan を組めない (入力が足りない / 危険)。"""


@dataclass
class Plan:
    owner: str
    name: str
    visibility: str
    description: str
    repo_dir: Path
    commit_name: str
    commit_email: str
    home: Path
    registry_file: Path | None = None
    push_wrapper: Path | None = None
    preflight_script: Path | None = None

    @property
    def nwo(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def remote_url(self) -> str:
        return f"https://github.com/{self.nwo}.git"

    def tilde(self, path: Path) -> str:
        try:
            return "~/" + path.resolve().relative_to(self.home.resolve()).as_posix()
        except ValueError:
            return path.as_posix()


class SubprocessRunner:
    def run(self, argv, *, cwd=None, scoped_env=None, timeout=60):  # noqa: ANN001
        env = os.environ.copy()
        env.update(scoped_env or {})
        completed = subprocess.run(
            list(argv), cwd=cwd, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, timeout=timeout,
        )
        return completed.returncode, completed.stdout or "", completed.stderr or ""


# ---------- plan ----------

def default_local_root(home: Path, visibility: str, env: dict[str, str]) -> Path:
    override = env.get("GITHUB_OPS_REPO_ROOT")
    if override:
        return Path(override).expanduser()
    root = home / DEFAULT_LOCAL_ROOT
    return root / "private" if visibility == "private" else root


def _optional_default(home: Path, relative: Path) -> Path | None:
    candidate = home / relative
    return candidate if candidate.exists() else None


def _default_preflight_script(local_root: Path) -> Path | None:
    for base in (local_root, local_root.parent):
        candidate = base / "repo-preflight" / "scripts" / "readiness_scan.py"
        if candidate.exists():
            return candidate
    return None


def build_plan(
    *, owner: str, name: str, visibility: str, description: str, home: Path, env: dict[str, str],
    local_root: Path | None = None, repo_dir: Path | None = None,
    commit_name: str | None = None, commit_email: str | None = None,
    registry_file: Path | None = None, push_wrapper: Path | None = None,
    preflight_script: Path | None = None,
) -> Plan:
    if visibility not in {"public", "private"}:
        raise BootstrapError(f"visibility は public か private: {visibility}")
    if not NAME_PATTERN.match(name or "") or ".." in name:
        raise BootstrapError(f"repository 名が不正: {name!r}")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$", owner or ""):
        raise BootstrapError(f"owner が不正: {owner!r}")
    identity = KNOWN_IDENTITIES.get(owner)
    if commit_name is None or commit_email is None:
        if identity is None:
            raise BootstrapError(f"owner {owner} の commit 名義が未登録。--commit-name と --commit-email を指定する")
        commit_name, commit_email = identity
    root = local_root or default_local_root(home, visibility, env)
    directory = repo_dir or (root / name)
    return Plan(
        owner=owner, name=name, visibility=visibility, description=description,
        repo_dir=directory, commit_name=commit_name, commit_email=commit_email, home=home,
        registry_file=registry_file if registry_file is not None else _optional_default(home, DEFAULT_REGISTRY),
        push_wrapper=push_wrapper if push_wrapper is not None else _optional_default(home, DEFAULT_PUSH_WRAPPER),
        preflight_script=preflight_script if preflight_script is not None else _default_preflight_script(root),
    )


# ---------- templates ----------

def visibility_claim_line(visibility: str) -> str:
    """check_visibility_claim.py が読む「状態:」行。公開は「公開済み」、非公開は「非公開」を含める。"""
    return "状態: 公開済み" if visibility == "public" else "状態: 非公開（公開済みではない）"


def render_templates(plan: Plan, *, today: date) -> dict[str, str]:
    year = today.year
    return {
        "LICENSE": (
            "MIT License\n\n"
            f"Copyright (c) {year} nexus_ai\n\n"
            "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
            "of this software and associated documentation files (the \"Software\"), to deal\n"
            "in the Software without restriction, including without limitation the rights\n"
            "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
            "copies of the Software, and to permit persons to whom the Software is\n"
            "furnished to do so, subject to the following conditions:\n\n"
            "The above copyright notice and this permission notice shall be included in all\n"
            "copies or substantial portions of the Software.\n\n"
            "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR\n"
            "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,\n"
            "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE\n"
            "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER\n"
            "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,\n"
            "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n"
            "SOFTWARE.\n"
        ),
        "README.md": (
            f"# {plan.name}\n\n{plan.description}\n\n"
            "## ライセンスと出典\n\n- コード・文書: MIT (`LICENSE`)。名義は nexus_ai\n"
        ),
        "SECURITY.md": (
            "# Security\n\n"
            "## データ境界\n\n- secret / token / 個人の絶対 path を repository に入れない。\n\n"
            "## 報告経路\n\n"
            "脆弱性や個人情報の混入は GitHub の Private vulnerability reporting (public 化後に有効) か、"
            "機微情報を含めない Issue で知らせてください。\n"
        ),
        "PREFLIGHT.md": (
            "<!-- repo-preflight:review-record -->\n\n"
            "# 公開範囲とレビュー条件\n\n"
            f"{visibility_claim_line(plan.visibility)}\n\n"
            f"このリポジトリは {plan.description} を対象とします。\n\n"
            "## 公開対象\n\n- (実装後に記入)\n\n"
            "## 公開対象外\n\n- secret / token / 個人の絶対 path / アカウント情報\n"
            "- 公開・push・merge・visibility 変更を自動実行する機能\n\n"
            "## 判定上の停止線\n\n"
            "`readiness_scan.py` の `status: pass` はローカルで機械検査できた範囲だけを示す。"
            "公開・push・merge・visibility 変更は人が別に判断する。\n\n"
            f"## レビュー記録 ({today.isoformat()})\n\n- bootstrap_repo.py で作成。repo-preflight の検査結果は作成時の report を参照。\n"
        ),
        "CONTRIBUTING.md": (
            "# コントリビューション\n\n"
            "- 挙動を変える時は失敗する test を先に追加する。\n"
            "- secret / token / 個人の絶対 path を commit しない。\n"
            "- main へ直接 push しない。branch を切って PR を出す。\n"
        ),
        ".gitignore": "__pycache__/\n*.pyc\n.pytest_cache/\n.DS_Store\n.env\n.env.*\n",
    }


def scaffold_docs(plan: Plan, *, today: date) -> list[str]:
    written: list[str] = []
    plan.repo_dir.mkdir(parents=True, exist_ok=True)
    templates = render_templates(plan, today=today)
    for filename in SCAFFOLD_ORDER:
        target = plan.repo_dir / filename
        if target.exists():
            continue
        target.write_text(templates[filename], encoding="utf-8")
        written.append(filename)
    return written


# ---------- registry ----------

def registry_local_path(plan: Plan) -> str:
    """台帳の `local:` 表記。workspace root からの相対にする。

    `~/Projects/...` のような home 起点の表記は、台帳を持つ workspace 側の
    pre-commit `no_full_path_guard` に抵触して commit できない (2026-09-06 実測)。
    既存行も `Documents/.repos/...` の相対表記で揃っている。
    """
    try:
        return plan.repo_dir.resolve().relative_to((plan.home / WORKSPACE_ROOT).resolve()).as_posix()
    except ValueError:
        return plan.tilde(plan.repo_dir)


def registry_row(plan: Plan, *, today: date) -> str:
    local = registry_local_path(plan)
    return (
        f"| `{plan.nwo}`（{plan.description}） | {plan.visibility} | **{plan.owner}** | "
        f"{today.isoformat()} bootstrap_repo.py で作成と同時登録。local: `{local}` |"
    )


def _registry_marker(key: str) -> str:
    return f"| `{key}`"


def registry_has_key(text: str, key: str) -> bool:
    return any(line.startswith(_registry_marker(key)) for line in text.splitlines())


def register_names(plan: Plan) -> tuple[str, str]:
    """登録用 worktree の directory 名と branch 名。owner を含め、別 owner の同名 repo と混ざらないようにする。"""
    slug = f"{plan.owner}-{plan.name}"
    return f"register-{slug}", REGISTER_BRANCH_PREFIX + slug


def insert_registry_row(text: str, row: str, *, key: str) -> str | None:
    """`key` (owner/name) の行があれば置き換え、無ければ anchor の直前に入れる。anchor が無ければ None。"""
    marker = _registry_marker(key)
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith(marker):
            if line.rstrip("\n") == row:
                return text
            lines[index] = row + "\n"
            return "".join(lines)
    for index, line in enumerate(lines):
        if line.startswith(REGISTRY_ANCHOR):
            lines.insert(index, row + "\n")
            return "".join(lines)
    return None


# ---------- bootstrap ----------

class Bootstrapper:
    def __init__(self, plan: Plan, runner, *, today: date, allow_no_preflight: bool = False,  # noqa: ANN001
                 resume: bool = False, skip_push: bool = False) -> None:
        self.plan = plan
        self.runner = runner
        self.today = today
        self.allow_no_preflight = allow_no_preflight
        self.resume = resume          # 途中で止まった後の再実行 (remote / origin が既にあっても一致すれば続ける)
        self.skip_push = skip_push    # push を別経路で済ませた時だけ。verify が main の実在と sha を確認する
        self._token: str | None = None
        self._remote: dict[str, Any] | None = None   # gh repo view の結果 (存在する時)
        self.registration: dict[str, Any] | None = None   # 台帳の登録 branch (push と PR はまだ)

    # -- helpers --
    def _git(self, *args: str) -> tuple[int, str, str]:
        return self.runner.run(["git", *args], cwd=str(self.plan.repo_dir))

    def _git_at(self, directory: Path, *args: str, timeout: int = 60) -> tuple[int, str, str]:
        return self.runner.run(["git", "-C", str(directory), *args], timeout=timeout)

    def _registry_layout(self) -> tuple[Path | None, str]:
        """台帳 file を持つ repository の main checkout root と、その中での相対 path。分からなければ (None, "")。"""
        registry = self.plan.registry_file
        assert registry is not None
        rc, top, _ = self._git_at(registry.parent, "rev-parse", "--show-toplevel")
        rc_common, common, _ = self._git_at(registry.parent, "rev-parse", "--path-format=absolute", "--git-common-dir")
        common_dir = Path(common.strip())
        # main checkout の root は <root>/.git の親。submodule / separate-git-dir / bare は対象外にする
        if rc != 0 or rc_common != 0 or not top.strip() or common_dir.name != ".git":
            return None, ""
        try:
            rel = registry.resolve().relative_to(Path(top.strip()).resolve()).as_posix()
        except ValueError:
            return None, ""
        return common_dir.parent, rel

    def _register_target(self, root: Path) -> tuple[Path, str]:
        directory, branch = register_names(self.plan)
        return root / REGISTER_WORKTREE_DIR / directory, branch

    def _check_registry(self) -> str:
        """台帳を origin/main から切った branch で commit できるか。repo を作ってから register で止まる主な原因を先に見る。"""
        if self.plan.registry_file is None:
            return "skipped"
        root, rel = self._registry_layout()
        if root is None:
            return "not_git"
        if self._git_at(root, "rev-parse", "--verify", "-q", "origin/main")[0] != 0:
            return "no_origin_main"
        rc, text, _ = self._git_at(root, "show", f"origin/main:{rel}")
        if rc != 0:
            return "registry_not_on_origin_main"
        if REGISTRY_ANCHOR not in text and not registry_has_key(text, self.plan.nwo):
            return "registry_anchor_missing"
        if self._git_at(root, "cat-file", "-e", f"origin/main:{REGISTRY_COMMIT_WRAPPER}")[0] != 0:
            return "commit_wrapper_missing"
        worktree, _ = self._register_target(root)
        if self._git_at(root, "check-ignore", "-q", worktree.relative_to(root).as_posix())[0] != 0:
            return "worktree_dir_not_ignored"
        return "ok"

    def _main_checkout_state(self, root: Path, rel: str) -> tuple[str, str]:
        """main checkout の HEAD と台帳 file の状態。登録の前後で変わってはいけない。"""
        return self._git_at(root, "rev-parse", "HEAD")[1], self._git_at(root, "status", "--porcelain", "--", rel)[1]

    def _gh(self, *args: str) -> tuple[int, str, str]:
        assert self._token, "token を先に解決する"
        return self.runner.run(["gh", *args], scoped_env={"GH_TOKEN": self._token, "GH_HOST": "github.com"})

    def _head_sha(self) -> str | None:
        rc, out, _ = self._git("rev-parse", "HEAD")
        return out.strip() if rc == 0 and out.strip() else None

    def _resolve_token(self) -> str:
        rc, out, _ = self.runner.run(["gh", "auth", "token", "--hostname", "github.com", "--user", self.plan.owner])
        token = out.strip()
        if rc != 0 or not token:
            return "missing"
        self._token = token
        rc, login, _ = self._gh("api", "user", "--jq", ".login")
        if rc != 0:
            self._token = None
            return "unverified"
        if login.strip() != self.plan.owner:
            self._token = None
            return "mismatch"
        return "ok"

    # -- preflight (read-only) --
    def preflight(self) -> dict[str, Any]:
        checks: dict[str, str] = {}
        checks["token_login"] = self._resolve_token()
        self._remote = None
        if checks["token_login"] == "ok":
            rc, out, _ = self._gh("repo", "view", self.plan.nwo, "--json", "nameWithOwner,visibility")
            if rc != 0:
                checks["remote_absent"] = "ok"
            else:
                try:
                    self._remote = json.loads(out or "{}")
                except json.JSONDecodeError:
                    self._remote = {}
                remote_vis = str(self._remote.get("visibility", "")).lower()
                if not self.resume:
                    checks["remote_absent"] = "exists"
                elif remote_vis and remote_vis != self.plan.visibility:
                    checks["remote_absent"] = f"exists_visibility_{remote_vis}"
                else:
                    checks["remote_absent"] = "exists_resume"
        else:
            checks["remote_absent"] = "unknown"

        repo_dir = self.plan.repo_dir
        if not repo_dir.exists():
            checks["local_dir"] = "absent"
            checks["commit_identity"] = "n/a"
        else:
            rc, top, _ = self._git("rev-parse", "--show-toplevel")
            if rc != 0 or not top.strip():
                checks["local_dir"] = "not_git"
            elif Path(top.strip()).resolve() != repo_dir.resolve():
                checks["local_dir"] = "nested_in_other_repo"
            else:
                rc, url, _ = self._git("remote", "get-url", "origin")
                if rc != 0:
                    checks["local_dir"] = "git_no_origin"
                elif self.resume and url.strip() == self.plan.remote_url:
                    checks["local_dir"] = "origin_matches"
                else:
                    checks["local_dir"] = "has_origin"
            rc, log, _ = self._git("log", "--format=%an|%ae|%cn|%ce")
            expected = "|".join([self.plan.commit_name, self.plan.commit_email] * 2)
            identities = {line.strip() for line in log.splitlines() if line.strip()} if rc == 0 else set()
            checks["commit_identity"] = "ok" if not identities or identities == {expected} else "mismatch"

        checks["preflight_script"] = "ok" if self.plan.preflight_script else ("skipped" if self.allow_no_preflight else "missing")
        checks["push_wrapper"] = "ok" if self.plan.push_wrapper else "missing"
        checks["registry_file"] = self._check_registry()

        blocking = (
            checks["token_login"] != "ok"
            or checks["remote_absent"] not in {"ok", "exists_resume"}
            or checks["local_dir"] in {"not_git", "has_origin", "nested_in_other_repo"}
            or (checks["remote_absent"] == "exists_resume" and checks["local_dir"] != "origin_matches")
            or checks["commit_identity"] == "mismatch"
            or checks["preflight_script"] == "missing"
            or checks["registry_file"] not in {"ok", "skipped"}
        )
        return {"status": "BLOCKED" if blocking else "READY", "checks": checks, "plan": self._plan_view()}

    def _plan_view(self) -> dict[str, Any]:
        p = self.plan
        return {
            "repository": p.nwo, "visibility": p.visibility, "description": p.description,
            "repo_dir": p.tilde(p.repo_dir), "commit_name": p.commit_name, "commit_email": p.commit_email,
            "registry_file": p.tilde(p.registry_file) if p.registry_file else None,
            "push_wrapper": p.tilde(p.push_wrapper) if p.push_wrapper else None,
            "preflight_script": p.tilde(p.preflight_script) if p.preflight_script else None,
            "push_strategy": f"{INIT_BRANCH} を wrapper で push → API で main を作成・既定化 → {INIT_BRANCH} を削除",
            "registration_strategy": (
                f"台帳 repo の origin/main から {REGISTER_WORKTREE_DIR}/{register_names(p)[0]} を作り、"
                f"{register_names(p)[1]} に行を commit する (main checkout には書かない)。{REGISTRATION_NEXT}"
            ),
        }

    # -- execute (writes; fail-closed) --
    def execute(self) -> dict[str, Any]:
        steps: list[dict[str, str]] = []
        report: dict[str, Any] = {"status": "BLOCKED", "steps": steps, "plan": self._plan_view()}

        def record(name: str, status: str, detail: str = "") -> bool:
            steps.append({"name": name, "status": status, "detail": detail})
            return status in {"ok", "skipped"}

        pre = self.preflight()
        report["preflight"] = pre["checks"]
        if not record("preflight", "ok" if pre["status"] == "READY" else "fail", json.dumps(pre["checks"], ensure_ascii=False)):
            return report
        actions = {
            "prepare_local": self._prepare_local, "set_identity": self._set_identity, "scaffold_docs": self._scaffold,
            "initial_commit": self._initial_commit, "readiness_scan": self._readiness_scan,
            "create_remote": self._create_remote, "lockdown": self._lockdown, "add_remote": self._add_remote,
            "push": self._push, "promote_main": self._promote_main, "register": self._register, "verify": self._verify,
        }
        for name in STEP_ORDER:
            try:
                status, detail = actions[name]()
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                status, detail = "fail", f"{type(exc).__name__}: {exc}"
            if not record(name, status, detail):
                return report
        report["status"] = "READY"
        if self.registration is not None:
            report["registration"] = self.registration
            report["next"] = REGISTRATION_NEXT
        return report

    def _prepare_local(self) -> tuple[str, str]:
        if self.plan.repo_dir.exists():
            return "ok", "既存 directory を使う"
        self.plan.repo_dir.mkdir(parents=True)
        rc, _, err = self._git("init", "-b", "main")
        return ("ok", "git init -b main") if rc == 0 else ("fail", err.strip())

    def _set_identity(self) -> tuple[str, str]:
        for key, value in (("user.name", self.plan.commit_name), ("user.email", self.plan.commit_email)):
            rc, _, err = self._git("config", key, value)
            if rc != 0:
                return "fail", err.strip()
        return "ok", f"{self.plan.commit_name} <{self.plan.commit_email}> (repository-local)"

    def _scaffold(self) -> tuple[str, str]:
        written = scaffold_docs(self.plan, today=self.today)
        return "ok", ("wrote " + ", ".join(written)) if written else "all present"

    def _initial_commit(self) -> tuple[str, str]:
        rc, _, _ = self._git("rev-list", "--count", "HEAD")
        _, status, _ = self._git("status", "--porcelain", "--untracked-files=all")
        if rc == 0:
            if status.strip():
                return "fail", "既存 commit があり worktree が dirty。先に commit するか片付ける: " + status.strip()[:300]
            return "skipped", "既存 commit あり"
        rc, _, err = self._git("add", "--", *SCAFFOLD_ORDER)
        if rc != 0:
            return "fail", err.strip()
        _, status, _ = self._git("status", "--porcelain", "--untracked-files=all")
        leftovers = [line for line in status.splitlines() if line.strip() and not line.startswith(("A ", "AM"))]
        if leftovers:
            return "fail", ("雛形以外の file が未追跡のまま (push から漏れる)。先に自分で commit する: "
                            + " / ".join(line.strip() for line in leftovers[:10]))
        rc, _, err = self._git("commit", "-q", "-m", f"chore: {self.plan.name} を初期化 (bootstrap_repo.py)")
        return ("ok", "initial commit") if rc == 0 else ("fail", err.strip())

    def _readiness_scan(self) -> tuple[str, str]:
        script = self.plan.preflight_script
        if script is None:
            return ("skipped", "repo-preflight 不在 (--allow-no-preflight)") if self.allow_no_preflight else ("fail", "repo-preflight が見つからない")
        rc, out, err = self.runner.run(["python3", str(script), "--repo", str(self.plan.repo_dir)])
        try:
            payload = json.loads(out or "{}")
        except json.JSONDecodeError:
            return "fail", f"readiness_scan の出力を解釈できない (rc={rc})"
        top = str(payload.get("status", ""))
        # scanner の status: pass / blocked (fail か unknown あり) / tool_error。remote 未作成の時点では
        # origin / CI が unknown なので blocked は正常。tool_error と個別 check の fail だけを止める。
        if top == "tool_error" or top not in {"pass", "blocked"}:
            return "fail", f"readiness_scan が異常終了 (rc={rc}, status={top or 'missing'}, issues={payload.get('issues')})"
        checks = payload.get("checks") or {}
        failed = {name: item.get("status") for name, item in checks.items()
                  if isinstance(item, dict) and item.get("status") == "fail"}
        bad = {name: (checks.get(name) or {}).get("status", "missing") for name in SCAN_REQUIRED_CHECKS
               if (checks.get(name) or {}).get("status") not in SCAN_ACCEPTED}
        if failed or bad:
            return "fail", "readiness_scan: " + json.dumps({**failed, **bad}, ensure_ascii=False)
        return "ok", f"status={top}; fail 0; required_documents / secret / personal_path / identity pass (unknown は remote 未作成のため許容)"

    def _create_remote(self) -> tuple[str, str]:
        if self.resume and self._remote is not None:
            return "skipped", "remote は作成済み (resume)"
        rc, _, err = self._gh("repo", "create", self.plan.nwo, f"--{self.plan.visibility}", "--description", self.plan.description)
        if rc != 0:
            return "fail", err.strip()
        self._remote = {"nameWithOwner": self.plan.nwo, "visibility": self.plan.visibility}
        return "ok", self.plan.nwo

    def _lockdown(self) -> tuple[str, str]:
        if self.plan.visibility != "public":
            return "skipped", "private は lockdown 対象外"
        rc, _, err = self._gh(
            "api", "-X", "PATCH", f"repos/{self.plan.nwo}",
            "-f", "security_and_analysis[secret_scanning][status]=enabled",
            "-f", "security_and_analysis[secret_scanning_push_protection][status]=enabled",
        )
        if rc != 0:
            return "fail", "secret scanning: " + err.strip()
        rc, _, err = self._gh("api", "-X", "PUT", f"repos/{self.plan.nwo}/private-vulnerability-reporting")
        if rc != 0:
            return "fail", "private vulnerability reporting: " + err.strip()
        return "ok", "secret scanning + push protection + private vulnerability reporting (push より前に適用)"

    def _add_remote(self) -> tuple[str, str]:
        rc, url, _ = self._git("remote", "get-url", "origin")
        if rc == 0 and url.strip() == self.plan.remote_url:
            return "skipped", "origin は設定済み"
        rc, _, err = self._git("remote", "add", "origin", self.plan.remote_url)
        return ("ok", self.plan.remote_url) if rc == 0 else ("fail", err.strip())

    def _push(self) -> tuple[str, str]:
        if self.skip_push:
            return "skipped", "--skip-push (push は別経路で済ませた前提。verify が main の実在と sha を確認する)"
        wrapper = self.plan.push_wrapper
        if wrapper is None:
            return "fail", f"push wrapper (cc-push-resolved.sh) が見つからない。{INIT_BRANCH} の push を手で行い --resume --skip-push で再実行する"
        rc, _, err = self._git("branch", "-f", INIT_BRANCH, "HEAD")
        if rc != 0:
            return "fail", err.strip()
        rc, _, err = self._git("switch", INIT_BRANCH)
        if rc != 0:
            return "fail", err.strip()
        rc, out, err = self.runner.run(["bash", str(wrapper), "--repo", str(self.plan.repo_dir), "--branch", INIT_BRANCH], timeout=300)
        rc_back, _, err_back = self._git("switch", "main")
        if rc != 0:
            return "fail", (err or out).strip()[-800:]
        if rc_back != 0:
            return "fail", "main へ戻れない: " + err_back.strip()
        return "ok", f"pushed {INIT_BRANCH} via wrapper"

    def _promote_main(self) -> tuple[str, str]:
        if self.skip_push:
            return "skipped", "--skip-push"
        sha = self._head_sha()
        if not sha:
            return "fail", "HEAD sha を取れない"
        rc, _, err = self._gh("api", "-X", "POST", f"repos/{self.plan.nwo}/git/refs", "-f", "ref=refs/heads/main", "-f", f"sha={sha}")
        if rc != 0 and "already exists" not in err:
            return "fail", "main ref の作成: " + err.strip()
        rc, _, err = self._gh("api", "-X", "PATCH", f"repos/{self.plan.nwo}", "-f", "default_branch=main")
        if rc != 0:
            return "fail", "default branch: " + err.strip()
        rc, _, err = self._gh("api", "-X", "DELETE", f"repos/{self.plan.nwo}/git/refs/heads/{INIT_BRANCH}")
        if rc != 0:
            return "fail", f"{INIT_BRANCH} の削除: " + err.strip()
        self._git("branch", "-d", INIT_BRANCH)
        # 追跡設定は network を使わずに config で置く (git fetch は owner token を持たず失敗し得る)
        self._git("config", "branch.main.remote", "origin")
        self._git("config", "branch.main.merge", "refs/heads/main")
        self._git("update-ref", "refs/remotes/origin/main", sha)
        return "ok", f"main = {sha[:12]} (default), {INIT_BRANCH} 削除, origin/main を追跡"

    def _register(self) -> tuple[str, str]:
        """台帳の行を、台帳 repo の origin/main から切った専用 worktree の branch に commit する。

        台帳 repo の main checkout は読む専用で、そこへ書くと誰も commit しない差分が残る。
        push と PR は外部送信なので、この script では行わず canonical wrapper から出す (REGISTRATION_NEXT)。
        """
        registry = self.plan.registry_file
        if registry is None:
            return "skipped", "registry file 未指定"
        root, rel = self._registry_layout()
        if root is None:
            return "fail", f"台帳の main checkout を特定できない: {self.plan.tilde(registry)}"
        rc, _, err = self._git_at(root, "fetch", "-q", "origin", "main", timeout=300)
        if rc != 0:
            return "fail", "台帳 repo の origin/main を取得できない: " + err.strip()[-300:]
        rc, base_text, err = self._git_at(root, "show", f"origin/main:{rel}")
        if rc != 0:
            return "fail", f"origin/main に台帳 {rel} が無い: " + err.strip()
        if registry_has_key(base_text, self.plan.nwo):
            return "skipped", f"{self.plan.nwo} は origin/main の台帳に登録済み"
        worktree, branch = self._register_target(root)
        status, detail = self._ensure_register_worktree(root, worktree, branch)
        if status != "ok":
            return status, detail
        before = self._main_checkout_state(root, rel)
        status, detail = self._commit_registry_row(worktree, rel)
        if status != "ok":
            return status, detail
        if self._main_checkout_state(root, rel) != before:
            return "fail", "台帳 repo の main checkout が登録の前後で変わった (commit 入口が worktree の外に書いた)。push しない"
        rc, names, err = self._git_at(worktree, "diff", "-z", "--name-only", "origin/main...HEAD")
        changed = [name for name in names.split("\0") if name]
        if rc != 0 or changed != [rel]:
            return "fail", f"登録 branch の差分が台帳 1 file になっていない (push しない): {changed or err.strip()}"
        rc, sha, err = self._git_at(worktree, "rev-parse", "HEAD")
        if rc != 0 or not sha.strip():
            return "fail", "登録 branch の HEAD を取れない: " + err.strip()
        sha = sha.strip()
        self.registration = {
            "workspace_repo": self.plan.tilde(root), "worktree": self.plan.tilde(worktree),
            "branch": branch, "commit": sha, "file": rel,
        }
        return "ok", f"{branch} @ {sha[:12]} ({self.plan.tilde(worktree)})。push と PR はまだ"

    def _ensure_register_worktree(self, root: Path, worktree: Path, branch: str) -> tuple[str, str]:
        if worktree.exists():
            rc, current, _ = self._git_at(worktree, "rev-parse", "--abbrev-ref", "HEAD")
            if rc != 0 or current.strip() != branch:
                return "fail", f"{self.plan.tilde(worktree)} が {branch} の worktree ではない"
            return "ok", "既存の登録用 worktree を使う"
        if self._git_at(root, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")[0] == 0:
            args = ("worktree", "add", "-q", str(worktree), branch)   # 前回の branch だけ残っている時は付け直す
        else:
            args = ("worktree", "add", "-q", "--no-track", "-b", branch, str(worktree), "origin/main")
        rc, _, err = self._git_at(root, *args, timeout=300)
        return ("ok", "登録用 worktree を作成") if rc == 0 else ("fail", "登録用 worktree を作れない: " + err.strip())

    def _commit_registry_row(self, worktree: Path, rel: str) -> tuple[str, str]:
        key = self.plan.nwo
        target = worktree / rel
        text = target.read_text(encoding="utf-8")
        if not registry_has_key(text, key):
            updated = insert_registry_row(text, registry_row(self.plan, today=self.today), key=key)
            if updated is None:
                return "fail", f"registry anchor '{REGISTRY_ANCHOR}' が見つからない"
            target.write_text(updated, encoding="utf-8")
        rc, pending, err = self._git_at(worktree, "status", "--porcelain", "--", rel)
        if rc != 0:
            return "fail", "登録用 worktree の状態を読めない: " + err.strip()
        if not pending.strip():
            return "ok", "commit 済み"
        wrapper = worktree / REGISTRY_COMMIT_WRAPPER
        if not wrapper.exists():
            return "fail", f"台帳 repo の commit 入口が無い: {REGISTRY_COMMIT_WRAPPER}"
        rc, out, err = self.runner.run(
            ["bash", str(wrapper), REGISTRY_COMMIT_TARGET, f"docs: register {key} in the GitHub account map", "--only", rel],
            cwd=str(worktree), scoped_env={REGISTRY_COMMIT_DIR_ENV: str(worktree)}, timeout=180,
        )
        return ("ok", "commit") if rc == 0 else ("fail", "台帳の commit: " + (err or out).strip()[-600:])

    def _verify(self) -> tuple[str, str]:
        rc, out, err = self._gh("api", f"repos/{self.plan.nwo}", "--jq", "{full_name: .full_name, visibility: .visibility, default_branch: .default_branch}")
        if rc != 0:
            return "fail", err.strip()
        try:
            payload = json.loads(out or "{}")
        except json.JSONDecodeError:
            return "fail", "read-back の出力を解釈できない"
        if payload.get("full_name") != self.plan.nwo or str(payload.get("visibility", "")).lower() != self.plan.visibility:
            return "fail", f"read-back 不一致: {payload}"
        if payload.get("default_branch") != "main":
            return "fail", f"default branch が main ではない: {payload.get('default_branch')}"
        rc, out, err = self._gh("api", f"repos/{self.plan.nwo}/branches/main", "--jq", ".commit.sha")
        remote_sha = out.strip()
        if rc != 0 or not remote_sha:
            return "fail", "remote に main が無い (push 未完了): " + err.strip()
        local_sha = self._head_sha()
        if local_sha and remote_sha != local_sha:
            return "fail", f"remote main ({remote_sha[:12]}) が local HEAD ({local_sha[:12]}) と一致しない"
        return "ok", f"{self.plan.nwo} ({self.plan.visibility}) main={remote_sha[:12]}"


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--owner", default="nexus-ai-2045")
    parser.add_argument("--name", required=True)
    parser.add_argument("--visibility", choices=["public", "private"], required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--local-root", type=Path, help="既定: ~/Projects/Documents/.repos/nexus_ai (private は /private)")
    parser.add_argument("--repo-dir", type=Path, help="既定: <local-root>/<name>")
    parser.add_argument("--commit-name")
    parser.add_argument("--commit-email")
    parser.add_argument("--registry-file", type=Path, help="account↔repo map。既定: ~/Projects/Documents/references/github-account-repo-map.md")
    parser.add_argument("--push-wrapper", type=Path, help="既定: ~/Projects/shared/scripts/cc-push-resolved.sh")
    parser.add_argument("--preflight-script", type=Path, help="既定: <local-root>/repo-preflight/scripts/readiness_scan.py")
    parser.add_argument("--allow-no-preflight", action="store_true", help="repo-preflight が無い環境で検査を skip する (非推奨)")
    parser.add_argument("--confirm", action="store_true", help="実際に作成する。無い時は preflight だけ")
    parser.add_argument("--resume", action="store_true", help="途中で止まった作成を続きから再実行する (remote / origin / visibility が一致している時だけ)")
    parser.add_argument("--skip-push", action="store_true", help="push を別経路で済ませた後に残りだけを行う (--resume と併用)")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None, *, runner=None, home: Path | None = None,  # noqa: ANN001
         env: dict[str, str] | None = None, today: date | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = home or Path.home()
    env = dict(os.environ) if env is None else env
    today = today or date.today()
    try:
        plan = build_plan(
            owner=args.owner, name=args.name, visibility=args.visibility, description=args.description,
            home=home, env=env, local_root=args.local_root, repo_dir=args.repo_dir,
            commit_name=args.commit_name, commit_email=args.commit_email,
            registry_file=args.registry_file, push_wrapper=args.push_wrapper, preflight_script=args.preflight_script,
        )
    except BootstrapError as exc:
        print(json.dumps({"mode": "plan", "status": "BLOCKED", "cause": str(exc)}, ensure_ascii=False))
        return 1
    boot = Bootstrapper(plan, runner or SubprocessRunner(), today=today,
                        allow_no_preflight=args.allow_no_preflight, resume=args.resume, skip_push=args.skip_push)
    if args.confirm:
        result = boot.execute()
        result["mode"] = "execute"
    else:
        result = boot.preflight()
        result["mode"] = "preflight"
        result["next"] = "問題なければ同じ引数に --confirm を付けて実行する"
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[{result['mode']}] {result['status']} {plan.nwo} ({plan.visibility}) -> {plan.tilde(plan.repo_dir)}")
        for key, value in (result.get("checks") or result.get("preflight") or {}).items():
            print(f"  check {key}: {value}")
        for step in result.get("steps", []):
            print(f"  step {step['name']}: {step['status']} {step['detail']}")
        if result.get("registration"):
            print("  registration: " + json.dumps(result["registration"], ensure_ascii=False))
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
