#!/usr/bin/env python3
"""新規 GitHub repository の作成を 1 本の fail-closed 手順にまとめる。

置き場所の固定、commit 名義の設定、公開前文書の雛形、repo-preflight 検査、
owner の token だけを使った GitHub 作成、canonical wrapper 経由の初回 push、
公開直後の lockdown、台帳への登録、作成結果の read-back を順番に行う。

- 既定は preflight のみ (read-only)。`--confirm` が無い限り何も書かない。
- global の `gh` active account は切り替えない。owner の token を対象 process の env にだけ渡す。
- token を file・引数・出力へ残さない。
- どこかで止まったら、それ以降の step は実行しない (fail-closed)。
- 標準ライブラリだけで動く (runtime copy 単体で実行できる)。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

KNOWN_IDENTITIES: dict[str, tuple[str, str]] = {
    "nexus-ai-2045": ("nexus_ai", "273569186+nexus-ai-2045@users.noreply.github.com"),
}
DEFAULT_LOCAL_ROOT = Path("Projects/Documents/.repos/nexus_ai")
DEFAULT_REGISTRY = Path("Projects/Documents/references/github-account-repo-map.md")
DEFAULT_PUSH_WRAPPER = Path("Projects/shared/scripts/cc-push-resolved.sh")
REGISTRY_ANCHOR = "| 公開協業 repo 全般"
SCAN_REQUIRED_CHECKS = ("required_documents", "secret_scan", "personal_path_scan", "commit_identity")
SCAN_ACCEPTED = {"pass", "not_applicable"}
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SCAFFOLD_ORDER = ("LICENSE", "README.md", "SECURITY.md", "PREFLIGHT.md", "CONTRIBUTING.md", ".gitignore")


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
            raise BootstrapError(
                f"owner {owner} の commit 名義が未登録。--commit-name と --commit-email を指定する"
            )
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
            "## ライセンスと出典\n\n"
            "- コード・文書: MIT (`LICENSE`)。名義は nexus_ai\n"
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

def registry_row(plan: Plan, *, today: date) -> str:
    local = plan.tilde(plan.repo_dir)
    return (
        f"| `{plan.nwo}`（{plan.description}） | {plan.visibility} | **{plan.owner}** | "
        f"{today.isoformat()} bootstrap_repo.py で作成と同時登録。local: `{local}` |"
    )


def insert_registry_row(text: str, row: str) -> str | None:
    if row in text:
        return text
    lines = text.splitlines(keepends=True)
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
        self.resume = resume  # 途中で止まった後の再実行 (remote / origin が既にあっても一致すれば続ける)
        self.skip_push = skip_push  # 初回 push を人の手で済ませた時だけ (public 空 remote は gate が main push を止める)
        self._token: str | None = None
        self._remote_exists = False

    # -- helpers --
    def _git(self, *args: str) -> tuple[int, str, str]:
        return self.runner.run(["git", *args], cwd=str(self.plan.repo_dir))

    def _gh(self, *args: str) -> tuple[int, str, str]:
        assert self._token, "token を先に解決する"
        return self.runner.run(["gh", *args], scoped_env={"GH_TOKEN": self._token, "GH_HOST": "github.com"})

    def _resolve_token(self) -> str:
        rc, out, _ = self.runner.run(
            ["gh", "auth", "token", "--hostname", "github.com", "--user", self.plan.owner]
        )
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
        if checks["token_login"] == "ok":
            rc, _, _ = self._gh("repo", "view", self.plan.nwo, "--json", "nameWithOwner")
            self._remote_exists = rc == 0
            checks["remote_absent"] = "ok" if rc != 0 else ("exists_resume" if self.resume else "exists")
        else:
            checks["remote_absent"] = "unknown"

        repo_dir = self.plan.repo_dir
        if not repo_dir.exists():
            checks["local_dir"] = "absent"
            checks["commit_identity"] = "n/a"
        else:
            rc, out, _ = self._git("rev-parse", "--is-inside-work-tree")
            if rc != 0 or out.strip() != "true":
                checks["local_dir"] = "not_git"
            else:
                rc, url, _ = self._git("remote", "get-url", "origin")
                if rc != 0:
                    checks["local_dir"] = "git_no_origin"
                elif self.resume and url.strip() == self.plan.remote_url:
                    checks["local_dir"] = "origin_matches"
                else:
                    checks["local_dir"] = "has_origin"
            rc, log, _ = self._git("log", "--format=%an|%ae")
            expected = f"{self.plan.commit_name}|{self.plan.commit_email}"
            authors = {line.strip() for line in log.splitlines() if line.strip()} if rc == 0 else set()
            checks["commit_identity"] = "ok" if not authors or authors == {expected} else "mismatch"

        checks["preflight_script"] = "ok" if self.plan.preflight_script else ("skipped" if self.allow_no_preflight else "missing")
        checks["push_wrapper"] = "ok" if self.plan.push_wrapper else "manual"
        checks["registry_file"] = "ok" if self.plan.registry_file else "skipped"

        blocking = (
            checks["token_login"] != "ok"
            or checks["remote_absent"] not in {"ok", "exists_resume"}
            or checks["local_dir"] in {"not_git", "has_origin"}
            or checks["commit_identity"] == "mismatch"
        )
        return {
            "status": "BLOCKED" if blocking else "READY",
            "checks": checks,
            "plan": self._plan_view(),
        }

    def _plan_view(self) -> dict[str, Any]:
        p = self.plan
        return {
            "repository": p.nwo, "visibility": p.visibility, "description": p.description,
            "repo_dir": p.tilde(p.repo_dir), "commit_name": p.commit_name, "commit_email": p.commit_email,
            "registry_file": p.tilde(p.registry_file) if p.registry_file else None,
            "push_wrapper": p.tilde(p.push_wrapper) if p.push_wrapper else None,
            "preflight_script": p.tilde(p.preflight_script) if p.preflight_script else None,
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

        for name, action in (
            ("prepare_local", self._prepare_local),
            ("set_identity", self._set_identity),
            ("scaffold_docs", self._scaffold),
            ("initial_commit", self._initial_commit),
            ("readiness_scan", self._readiness_scan),
            ("create_remote", self._create_remote),
            ("add_remote", self._add_remote),
            ("push", self._push),
            ("lockdown", self._lockdown),
            ("register", self._register),
            ("verify", self._verify),
        ):
            try:
                status, detail = action()
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                status, detail = "fail", f"{type(exc).__name__}: {exc}"
            if not record(name, status, detail):
                return report
        report["status"] = "READY"
        return report

    def _prepare_local(self) -> tuple[str, str]:
        if self.plan.repo_dir.exists():
            return "ok", "既存 directory を使う (origin なし)"
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
        if rc == 0:
            rc, status, _ = self._git("status", "--porcelain")
            if status.strip():
                return "fail", "既存 commit があり worktree が dirty。先に commit するか片付ける"
            return "skipped", "既存 commit あり"
        rc, _, err = self._git("add", "--", *SCAFFOLD_ORDER)
        if rc != 0:
            return "fail", err.strip()
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
        checks = payload.get("checks") or {}
        bad = {
            name: (checks.get(name) or {}).get("status", "missing")
            for name in SCAN_REQUIRED_CHECKS
            if (checks.get(name) or {}).get("status") not in SCAN_ACCEPTED
        }
        if bad:
            return "fail", "readiness_scan: " + json.dumps(bad, ensure_ascii=False)
        return "ok", "required_documents / secret / personal_path / identity pass"

    def _create_remote(self) -> tuple[str, str]:
        if self.resume and self._remote_exists:
            return "skipped", "remote は作成済み (resume)"
        rc, _, err = self._gh(
            "repo", "create", self.plan.nwo, f"--{self.plan.visibility}", "--description", self.plan.description,
        )
        return ("ok", self.plan.nwo) if rc == 0 else ("fail", err.strip())

    def _add_remote(self) -> tuple[str, str]:
        rc, url, _ = self._git("remote", "get-url", "origin")
        if rc == 0 and url.strip() == self.plan.remote_url:
            return "skipped", "origin は設定済み"
        rc, _, err = self._git("remote", "add", "origin", self.plan.remote_url)
        return ("ok", self.plan.remote_url) if rc == 0 else ("fail", err.strip())

    def _push(self) -> tuple[str, str]:
        if self.skip_push:
            return "skipped", "--skip-push (初回 push は人の手で済ませた前提。remote の branch を verify で確認する)"
        wrapper = self.plan.push_wrapper
        if wrapper is None:
            return "skipped", (
                "push wrapper 不在。canonical wrapper (cc-push-resolved.sh) で "
                f"`--repo {self.plan.tilde(self.plan.repo_dir)} --branch main` を実行する"
            )
        rc, out, err = self.runner.run(
            ["bash", str(wrapper), "--repo", str(self.plan.repo_dir), "--branch", "main"], timeout=300,
        )
        return ("ok", "pushed via wrapper") if rc == 0 else ("fail", (err or out).strip()[-800:])

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
        return "ok", "secret scanning + push protection + private vulnerability reporting"

    def _register(self) -> tuple[str, str]:
        registry = self.plan.registry_file
        if registry is None:
            return "skipped", "registry file 未指定"
        text = registry.read_text(encoding="utf-8")
        updated = insert_registry_row(text, registry_row(self.plan, today=self.today))
        if updated is None:
            return "fail", f"registry anchor '{REGISTRY_ANCHOR}' が見つからない"
        if updated != text:
            registry.write_text(updated, encoding="utf-8")
        return "ok", self.plan.tilde(registry)

    def _verify(self) -> tuple[str, str]:
        rc, out, err = self._gh("api", f"repos/{self.plan.nwo}", "--jq", "{full_name: .full_name, visibility: .visibility}")
        if rc != 0:
            return "fail", err.strip()
        try:
            payload = json.loads(out or "{}")
        except json.JSONDecodeError:
            return "fail", "read-back の出力を解釈できない"
        if payload.get("full_name") != self.plan.nwo or str(payload.get("visibility", "")).lower() != self.plan.visibility:
            return "fail", f"read-back 不一致: {payload}"
        return "ok", f"{self.plan.nwo} ({self.plan.visibility})"


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
    parser.add_argument("--resume", action="store_true", help="途中で止まった作成を続きから再実行する (remote / origin が一致している時だけ)")
    parser.add_argument("--skip-push", action="store_true", help="初回 push を人の手で済ませた後に lockdown 以降だけを行う (--resume と併用)")
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
            registry_file=args.registry_file, push_wrapper=args.push_wrapper,
            preflight_script=args.preflight_script,
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
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
