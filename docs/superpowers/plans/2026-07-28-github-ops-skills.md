# GitHub Operations Skills 実装計画

> **agentic worker向け:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推奨）または `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 複数GitHubアカウント環境で、対象owner・repository・credentialを一次確認し、誤操作をfail-closedで防ぐ再利用可能なCore Suiteを構築する。

**Architecture:** Python package `github_ops`が状態契約、overlay検証、identity probe、preflight、E2E runnerを提供する。`skills/`は操作手順、`adapters/`はCodex・Claudeから同じSSOTを参照する薄い接続層とし、個人用account mapやtokenはリポジトリ外のoverlayに保持する。

**Tech Stack:** Python 3.11+、標準ライブラリ、PyYAML、jsonschema、pytest、Git、GitHub CLI (`gh`)、PowerShell 7

---

## 記録情報

- schema_version: `fact-provenance/v1`
- recorded_at: `2026-07-28T02:02:42+09:00`
- recorded_by: `codex`
- status: `人間レビュー待ち`

### fact

- claim: 保存済み設計書は現在会話で実装計画作成への進行を承認された。
- actor: `user`
- event_time: `2026-07-28`
- observed_at: `2026-07-28T02:02:42+09:00`
- scope: `実装計画作成`
- source: `現在会話のOK GO`

### non_fact

- claim: 本計画はtask単位で検証・commitし、GitHub外部操作前の人間レビューで停止する実行案である。
- actor: `codex`
- event_time: `2026-07-28T02:02:42+09:00`
- scope: `github-ops-skills実装`
- non_fact_kind: `proposal`
- basis: `承認済み設計とwriting-plans手順`

### unknown

- claim: Task 1–11の実行結果。
- actor: `implementation runner`
- event_time: `unknown`
- scope: `github-ops-skills実装`
- unknown_reason: `実装はまだ開始していない`
- verification_next: `人間レビュー後に選択された実行方式で各taskを実測する`

## 実行前の固定条件

- 実装対象はこのリポジトリだけとする。
- 既存スキルは読み取り元として扱い、変更・削除しない。
- `git add -A`を使わず、各taskで列挙したpathだけをstageする。
- GitHubへの書き込み、repository作成、push、PR、mutation canary、公開はこの計画の自動実行範囲外とする。
- legacy sourceは環境変数で渡す。絶対パスをrepository内へ保存しない。

```powershell
$repo = (git rev-parse --show-toplevel).Trim()
if (-not $env:GITHUB_OPS_SHARED_ROOT) { throw 'GITHUB_OPS_SHARED_ROOT is required' }
if (-not $env:GITHUB_OPS_AGENT_SKILLS_ROOT) { throw 'GITHUB_OPS_AGENT_SKILLS_ROOT is required' }
python --version
gh --version
git status --short --branch
```

期待結果:

- Python 3.11以上。
- `gh`が実行可能。
- branchは`main`。
- 計画実行開始時のworktree状態が記録される。

## 固定ファイル構造

```text
.
├─ pyproject.toml
├─ README.md
├─ LICENSE
├─ SECURITY.md
├─ PUBLIC_READY.md
├─ src/github_ops/
│  ├─ __init__.py
│  ├─ result.py
│  ├─ command.py
│  ├─ account_map.py
│  ├─ identity.py
│  ├─ preflight.py
│  ├─ pr_language.py
│  ├─ public_identity.py
│  └─ redaction.py
├─ scripts/
│  ├─ gh_identity_probe.py
│  ├─ github_account_context.py
│  ├─ github_pr_readiness_preflight.py
│  ├─ check_pr_japanese.py
│  ├─ public_identity_guard.py
│  ├─ import_legacy_sources.py
│  ├─ run_read_only_e2e.py
│  └─ run_private_canary.py
├─ schemas/account-repo-map.schema.yaml
├─ examples/account-repo-map.example.yaml
├─ migration/source-manifest.json
├─ skills/<seven-core-skills>/
├─ adapters/codex/
│  ├─ README.md
│  └─ verify_adapter.py
├─ adapters/claude/
│  ├─ README.md
│  └─ verify_adapter.py
├─ tests/unit/
├─ tests/e2e/
├─ tests/fixtures/
└─ docs/
   ├─ architecture.md
   ├─ safety-boundary.md
   ├─ migration.md
   ├─ operations.md
   ├─ review-decision.md
   └─ evidence/
```

各Python moduleの責務:

- `result.py`: `READY` / `BLOCKED` / `UNKNOWN`の型とJSON契約。
- `command.py`: subprocess実行と環境の限定。
- `account_map.py`: overlayのload、schema検証、repo固有account解決。
- `identity.py`: remote、active login、token login、Git identityの観測。
- `preflight.py`: 観測結果を統合し、書き込み可否を判定。
- `pr_language.py`: 日本語PR metadata検査。
- `public_identity.py`: commit・diff・artifactの個人情報検査。
- `redaction.py`: secretを出力から除去。

### Task 1: Python packageと結果契約

**Files:**

- Create: `pyproject.toml`
- Create: `src/github_ops/__init__.py`
- Create: `src/github_ops/result.py`
- Create: `src/github_ops/redaction.py`
- Create: `tests/unit/test_result.py`
- Create: `tests/unit/test_redaction.py`

- [ ] Step 1: 結果契約の失敗testを書く

`tests/unit/test_result.py`:

```python
import json

import pytest

from github_ops.result import Outcome, Status


def test_outcome_json_contract_is_stable() -> None:
    outcome = Outcome(
        status=Status.BLOCKED,
        code="owner_mismatch",
        cause="token login does not match expected login",
        impact="GitHub write was not attempted",
        recovery="provide a token for the expected owner",
        evidence={"expected_login": "example-user", "token_login": "other-user"},
    )
    assert json.loads(outcome.to_json()) == {
        "status": "BLOCKED",
        "code": "owner_mismatch",
        "cause": "token login does not match expected login",
        "impact": "GitHub write was not attempted",
        "recovery": "provide a token for the expected owner",
        "evidence": {
            "expected_login": "example-user",
            "token_login": "other-user",
        },
    }


def test_ready_requires_evidence() -> None:
    with pytest.raises(ValueError, match="READY requires evidence"):
        Outcome(
            status=Status.READY,
            code="ready",
            cause="all checks passed",
            impact="operation may continue",
            recovery="none",
            evidence={},
        )
```

`tests/unit/test_redaction.py`:

```python
from github_ops.redaction import redact


def test_redacts_supported_github_tokens() -> None:
    text = "GH_TOKEN=ghp_" + "a" * 36
    assert "ghp_" not in redact(text)
    assert "[REDACTED]" in redact(text)
```

- [ ] Step 2: testを実行し、module未実装で失敗することを確認

```powershell
python -m pytest tests/unit/test_result.py tests/unit/test_redaction.py -q
```

期待結果: `ModuleNotFoundError: No module named 'github_ops'`。

- [ ] Step 3: package metadataと最小実装を書く

`pyproject.toml`は次を固定する。

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "github-ops-skills"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["PyYAML>=6.0.2,<7", "jsonschema>=4.23,<5"]

[project.optional-dependencies]
dev = ["pytest>=8.3,<9"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

`Status`は`str, Enum`として3値だけを持つ。`Outcome`はfrozen dataclassとし、`to_dict()`と`to_json()`を提供する。`redact()`は`ghp_`、`gho_`、`ghu_`、`ghs_`、`ghr_`、`github_pat_`形式と`Authorization: Bearer`を対象にする。

- [ ] Step 4: testを再実行して成功を確認

```powershell
python -m pip install -e '.[dev]'
python -m pytest tests/unit/test_result.py tests/unit/test_redaction.py -q
```

期待結果: 全testが`passed`。

- [ ] Step 5: 対象fileだけcommit

```powershell
git add -- pyproject.toml src/github_ops/__init__.py src/github_ops/result.py src/github_ops/redaction.py tests/unit/test_result.py tests/unit/test_redaction.py
git diff --cached --check
git commit -m "feat: add outcome and redaction contracts"
```

### Task 2: command runnerと環境限定

**Files:**

- Create: `src/github_ops/command.py`
- Create: `tests/unit/test_command.py`

- [ ] Step 1: tokenを子processだけへ渡す失敗testを書く

```python
from github_ops.command import CommandRunner


def test_scoped_env_does_not_mutate_parent(monkeypatch) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    captured = {}

    def fake_run(argv, **kwargs):
        captured.update(kwargs["env"])
        return type("Completed", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    runner = CommandRunner(run_impl=fake_run)
    runner.run(["gh", "api", "user"], scoped_env={"GH_TOKEN": "secret"})
    assert captured["GH_TOKEN"] == "secret"
    assert runner.parent_env("GH_TOKEN") is None


def test_result_output_is_redacted() -> None:
    token = "ghp_" + "a" * 36

    def fake_run(argv, **kwargs):
        return type(
            "Completed",
            (),
            {"returncode": 1, "stdout": "", "stderr": f"failed with {token}"},
        )()

    result = CommandRunner(run_impl=fake_run).run(["gh", "api", "user"])
    assert token not in result.stderr
    assert "[REDACTED]" in result.stderr
```

- [ ] Step 2: testを実行して失敗を確認

```powershell
python -m pytest tests/unit/test_command.py -q
```

期待結果: `github_ops.command`が存在せず失敗。

- [ ] Step 3: `CommandResult`と`CommandRunner`を実装

実行時は`os.environ.copy()`へ`scoped_env`を加え、`subprocess.run(..., capture_output=True, text=True, check=False, creationflags=CREATE_NO_WINDOW)`を使う。`CREATE_NO_WINDOW`はWindowsのみ設定し、stdout・stderrは返却前に`redact()`へ通す。

- [ ] Step 4: test成功とWindows非表示設定のunit testを確認

```powershell
python -m pytest tests/unit/test_command.py -q
```

期待結果: 全testが`passed`。

- [ ] Step 5: commit

```powershell
git add -- src/github_ops/command.py tests/unit/test_command.py
git diff --cached --check
git commit -m "feat: add scoped command runner"
```

### Task 3: account map schemaとoverlay解決

**Files:**

- Create: `schemas/account-repo-map.schema.yaml`
- Create: `examples/account-repo-map.example.yaml`
- Create: `src/github_ops/account_map.py`
- Create: `tests/fixtures/account-map.valid.yaml`
- Create: `tests/fixtures/account-map.invalid.yaml`
- Create: `tests/unit/test_account_map.py`

- [ ] Step 1: repo固有解決とfail-closedの失敗testを書く

```python
from pathlib import Path

import pytest

from github_ops.account_map import AccountMapError, load_account_map


def test_resolves_account_by_exact_owner_repo() -> None:
    account_map = load_account_map(Path("tests/fixtures/account-map.valid.yaml"))
    resolved = account_map.resolve("example-org/tooling")
    assert resolved.expected_owner == "example-org"
    assert resolved.expected_login == "example-user"
    assert resolved.account_label == "work"


def test_unknown_repo_fails_closed() -> None:
    account_map = load_account_map(Path("tests/fixtures/account-map.valid.yaml"))
    with pytest.raises(AccountMapError, match="repository is not mapped"):
        account_map.resolve("example-org/unknown")


def test_schema_violation_fails_closed() -> None:
    with pytest.raises(AccountMapError, match="schema validation failed"):
        load_account_map(Path("tests/fixtures/account-map.invalid.yaml"))
```

- [ ] Step 2: test失敗を確認

```powershell
python -m pytest tests/unit/test_account_map.py -q
```

期待結果: `github_ops.account_map`未実装で失敗。

- [ ] Step 3: schema、匿名example、loaderを実装

schemaは次を必須にする。

```yaml
schema_version: github-ops/account-map/v1
accounts:
  work:
    expected_login: example-user
repositories:
  example-org/tooling:
    account: work
    expected_owner: example-org
```

token値、credential値、絶対パスをschemaのpropertyとして許可しない。未知propertyは`additionalProperties: false`で拒否する。

- [ ] Step 4: testとexample検証を実行

```powershell
python -m pytest tests/unit/test_account_map.py -q
python -c "from pathlib import Path; from github_ops.account_map import load_account_map; load_account_map(Path('examples/account-repo-map.example.yaml'))"
```

期待結果: test成功、example loadのexit code 0。

- [ ] Step 5: commit

```powershell
git add -- schemas/account-repo-map.schema.yaml examples/account-repo-map.example.yaml src/github_ops/account_map.py tests/fixtures/account-map.valid.yaml tests/fixtures/account-map.invalid.yaml tests/unit/test_account_map.py
git diff --cached --check
git commit -m "feat: add repository account overlay schema"
```

### Task 4: identity probeとvalidated-token mode

**Files:**

- Create: `src/github_ops/identity.py`
- Create: `scripts/gh_identity_probe.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_identity.py`
- Create: `tests/e2e/test_identity_local.py`

- [ ] Step 1: identity分離の失敗testを書く

```python
from github_ops.identity import IdentityProbe


def test_token_login_mismatch_is_blocked(fake_runner) -> None:
    fake_runner.queue_json({"login": "other-user"})
    outcome = IdentityProbe(fake_runner).validate_token_login(
        expected_login="example-user",
        token="secret",
    )
    assert outcome.status.value == "BLOCKED"
    assert outcome.code == "token_login_mismatch"
    assert fake_runner.calls[0].scoped_env == {"GH_TOKEN": "secret"}


def test_probe_keeps_identity_fields_separate(fake_runner) -> None:
    probe = IdentityProbe(fake_runner)
    observed = probe.observe(repo=".")
    assert set(observed.to_dict()) == {
        "expected_owner",
        "expected_login",
        "remote_owner",
        "active_gh_login",
        "token_login",
        "git_author",
        "git_committer",
    }
```

`fake_runner` fixtureは`tests/conftest.py`へ置き、command列とscoped environmentだけを保存し、token値をassert失敗messageへ出さない。

- [ ] Step 2: test失敗を確認

```powershell
python -m pytest tests/unit/test_identity.py -q
```

期待結果: identity module未実装で失敗。

- [ ] Step 3: probeとCLIを実装

CLI契約:

```powershell
python scripts/gh_identity_probe.py --repo . --expected-owner example-org --expected-login example-user --json
```

JSONは`status`、`code`、`cause`、`impact`、`recovery`、`evidence`を持つ。tokenはCLI引数で受け取らず、対象processの`GH_TOKEN`だけを読む。token loginは`gh api user --jq .login`で一次確認し、`expected_login`と比較する。

- [ ] Step 4: unitとlocal E2Eを実行

```powershell
python -m pytest tests/unit/test_identity.py tests/e2e/test_identity_local.py -q
python scripts/gh_identity_probe.py --repo . --json
```

期待結果:

- test成功。
- remote未設定の現在repoでは`UNKNOWN`または`BLOCKED`を返し、tracebackを出さない。
- 出力にtoken形式が含まれない。

- [ ] Step 5: commit

```powershell
git add -- src/github_ops/identity.py scripts/gh_identity_probe.py tests/conftest.py tests/unit/test_identity.py tests/e2e/test_identity_local.py
git diff --cached --check
git commit -m "feat: add fail-closed identity probe"
```

### Task 5: preflight統合と書き込み契約

**Files:**

- Create: `src/github_ops/preflight.py`
- Create: `scripts/github_pr_readiness_preflight.py`
- Create: `scripts/github_account_context.py`
- Create: `tests/unit/test_preflight.py`
- Create: `tests/unit/test_account_context_cli.py`

- [ ] Step 1: READY条件と停止条件の失敗testを書く

```python
from github_ops.preflight import PreflightInput, run_preflight


def test_write_preflight_is_ready_only_when_all_proofs_match() -> None:
    result = run_preflight(
        PreflightInput(
            expected_repo="example-org/tooling",
            expected_owner="example-org",
            expected_login="example-user",
            remote_repo="example-org/tooling",
            token_login="example-user",
            permission="ADMIN",
            visibility="PRIVATE",
            worktree_paths=("src/github_ops/preflight.py",),
            approved_paths=("src/github_ops/preflight.py",),
            approval_present=True,
        )
    )
    assert result.status.value == "READY"


def test_missing_current_approval_is_blocked() -> None:
    result = run_preflight(
        PreflightInput(
            expected_repo="example-org/tooling",
            expected_owner="example-org",
            expected_login="example-user",
            remote_repo="example-org/tooling",
            token_login="example-user",
            permission="WRITE",
            visibility="PRIVATE",
            worktree_paths=(),
            approved_paths=(),
            approval_present=False,
        )
    )
    assert result.code == "approval_missing"
    assert result.status.value == "BLOCKED"


def test_unknown_visibility_never_becomes_ready() -> None:
    result = run_preflight(
        PreflightInput(
            expected_repo="example-org/tooling",
            expected_owner="example-org",
            expected_login="example-user",
            remote_repo="example-org/tooling",
            token_login="example-user",
            permission="WRITE",
            visibility=None,
            worktree_paths=(),
            approved_paths=(),
            approval_present=True,
        )
    )
    assert result.status.value == "UNKNOWN"
```

- [ ] Step 2: test失敗を確認

```powershell
python -m pytest tests/unit/test_preflight.py tests/unit/test_account_context_cli.py -q
```

期待結果: preflightとCLI未実装で失敗。

- [ ] Step 3: preflightとread-only context CLIを実装

必須check:

- exact `owner/name`
- expected ownerとremote owner
- expected loginとtoken login
- `viewerPermission`が`WRITE`、`MAINTAIN`、`ADMIN`のいずれか
- visibility
- dirty pathがapproved pathの部分集合
- approval flag
- 操作前global active login

`github_account_context.py`は既定でread-onlyとし、account切替optionを持たせない。GraphQL失敗時のREST fallbackは、両結果の矛盾を`UNKNOWN`として返す。

- [ ] Step 4: test成功とCLI JSONを確認

```powershell
python -m pytest tests/unit/test_preflight.py tests/unit/test_account_context_cli.py -q
python scripts/github_account_context.py --repo . --json
python scripts/github_pr_readiness_preflight.py --repo . --operation draft-pr --json
```

期待結果:

- unit test成功。
- remoteまたはapprovalがない場合、CLIはfail-closed JSONを返す。
- tracebackとsecret値を出さない。

- [ ] Step 5: commit

```powershell
git add -- src/github_ops/preflight.py scripts/github_account_context.py scripts/github_pr_readiness_preflight.py tests/unit/test_preflight.py tests/unit/test_account_context_cli.py
git diff --cached --check
git commit -m "feat: add GitHub write preflight"
```

### Task 6: PR日本語検査とpublic identity guard

**Files:**

- Create: `src/github_ops/pr_language.py`
- Create: `src/github_ops/public_identity.py`
- Create: `scripts/check_pr_japanese.py`
- Create: `scripts/public_identity_guard.py`
- Create: `tests/unit/test_pr_language.py`
- Create: `tests/unit/test_public_identity.py`

- [ ] Step 1: 日本語metadataと個人情報検出の失敗testを書く

```python
from github_ops.pr_language import check_pr_metadata
from github_ops.public_identity import scan_text


def test_japanese_pr_metadata_passes() -> None:
    result = check_pr_metadata("認証境界を追加", "## 概要\n誤account操作を停止します。")
    assert result.status.value == "READY"


def test_english_only_heading_is_blocked() -> None:
    result = check_pr_metadata("認証境界を追加", "## Summary\n誤操作を停止します。")
    assert result.code == "english_only_heading"


def test_windows_personal_path_is_blocked() -> None:
    result = scan_text("artifact at C:" + "\\Users\\alice\\secret.txt")
    assert result.status.value == "BLOCKED"
    assert "alice" not in result.to_json()
```

- [ ] Step 2: test失敗を確認

```powershell
python -m pytest tests/unit/test_pr_language.py tests/unit/test_public_identity.py -q
```

期待結果: module未実装で失敗。

- [ ] Step 3: 検査moduleとCLI wrapperを実装

検査対象:

- PR title、body、comment
- commit author、committer、message
- commit diff、tree path
- review artifact
- Windows、macOS、Linuxのlocal absolute path
- account map、token pattern、email denylist

検出結果は一致文字列そのものを返さず、rule codeとfile・line番号だけを返す。

- [ ] Step 4: testと自己scanを実行

```powershell
python -m pytest tests/unit/test_pr_language.py tests/unit/test_public_identity.py -q
python scripts/check_pr_japanese.py --title "認証境界を追加" --body "## 概要`n誤account操作を停止します。" --json
python scripts/public_identity_guard.py --repo . --range HEAD --json
```

期待結果:

- unit test成功。
- 日本語PR metadataは`READY`。
- 現在commitに個人情報patternがあれば`BLOCKED`となり、該当箇所を修正するまで次taskへ進まない。

- [ ] Step 5: commit

```powershell
git add -- src/github_ops/pr_language.py src/github_ops/public_identity.py scripts/check_pr_japanese.py scripts/public_identity_guard.py tests/unit/test_pr_language.py tests/unit/test_public_identity.py
git diff --cached --check
git commit -m "feat: add PR language and identity scans"
```

### Task 7: legacy Core Suiteの非破壊import

**Files:**

- Create: `scripts/__init__.py`
- Create: `migration/source-manifest.json`
- Create: `scripts/import_legacy_sources.py`
- Create: `tests/unit/test_import_legacy_sources.py`
- Create: `skills/github-cli-ops-guard/**`
- Create: `skills/commit-push-pr/**`
- Create: `skills/pr-status/**`
- Create: `skills/review-pr/**`
- Create: `skills/public-repo-readiness/**`
- Create: `skills/post-merge-closeout/**`
- Create: `skills/pr-convergence-loop/**`

- [ ] Step 1: source変更禁止とhash記録の失敗testを書く

```python
from pathlib import Path

from scripts.import_legacy_sources import import_sources


def test_import_copies_without_modifying_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "skill-a").mkdir(parents=True)
    original = source / "skill-a" / "SKILL.md"
    original.write_text("# Skill A\n", encoding="utf-8")

    records = import_sources(
        mappings=[("skill-a/SKILL.md", "skills/skill-a/SKILL.md")],
        source_root=source,
        target_root=target,
    )

    assert original.read_text(encoding="utf-8") == "# Skill A\n"
    assert records[0]["sha256"]
    assert (target / "skills/skill-a/SKILL.md").read_text(encoding="utf-8") == "# Skill A\n"
```

- [ ] Step 2: test失敗を確認

```powershell
python -m pytest tests/unit/test_import_legacy_sources.py -q
```

期待結果: import script未実装で失敗。

- [ ] Step 3: logical source manifestとimporterを実装

manifestは各fileについて次だけを保存する。

```json
{
  "schema_version": "github-ops/source-manifest/v1",
  "sources": [
    {
      "source_root": "shared",
      "source_path": "skills/github-cli-ops-guard/SKILL.md",
      "target_path": "skills/github-cli-ops-guard/SKILL.md",
      "sha256": "64-lowercase-hex"
    }
  ]
}
```

実行時のrootはCLI引数で受け取り、manifestへ絶対パスを書かない。対象skillは7件に固定し、symlink、repository外path、secret patternを拒否する。

- [ ] Step 4: dry-run、import、hash一致を確認

```powershell
python scripts/import_legacy_sources.py --shared-root $env:GITHUB_OPS_SHARED_ROOT --agent-skills-root $env:GITHUB_OPS_AGENT_SKILLS_ROOT --repo . --dry-run
python scripts/import_legacy_sources.py --shared-root $env:GITHUB_OPS_SHARED_ROOT --agent-skills-root $env:GITHUB_OPS_AGENT_SKILLS_ROOT --repo .
python scripts/import_legacy_sources.py --shared-root $env:GITHUB_OPS_SHARED_ROOT --agent-skills-root $env:GITHUB_OPS_AGENT_SKILLS_ROOT --repo . --verify-only
python -m pytest tests/unit/test_import_legacy_sources.py -q
```

期待結果:

- dry-runは7 skillと全対象fileを表示するが書き込まない。
- import後のmanifest hashがsource・target双方と一致。
- source側のGit statusが実行前後で不変。

- [ ] Step 5: import結果を読み、製品境界へ正規化

各`SKILL.md`から個人絶対パス、実在private repo、global account switchの既定手順を除く。共通CLIは`../../scripts/`ではなくinstalled package entry pointを参照する。元sourceは変更しない。

- [ ] Step 6: testと全skill lintを実行

```powershell
python -m pytest tests/unit/test_import_legacy_sources.py -q
python scripts/public_identity_guard.py --repo . --range HEAD --json
```

期待結果:

- test成功。
- `gh auth switch`は「既定では禁止」という説明以外に出現しない。
- personal pathとtoken patternは0件。

- [ ] Step 7: commit

```powershell
git add -- scripts/__init__.py migration/source-manifest.json scripts/import_legacy_sources.py tests/unit/test_import_legacy_sources.py skills/github-cli-ops-guard skills/commit-push-pr skills/pr-status skills/review-pr skills/public-repo-readiness skills/post-merge-closeout skills/pr-convergence-loop
git diff --cached --check
git commit -m "feat: import GitHub operations core skills"
```

### Task 8: Codex・Claude adapter

**Files:**

- Create: `adapters/__init__.py`
- Create: `adapters/codex/__init__.py`
- Create: `adapters/codex/README.md`
- Create: `adapters/codex/verify_adapter.py`
- Create: `adapters/claude/__init__.py`
- Create: `adapters/claude/README.md`
- Create: `adapters/claude/verify_adapter.py`
- Create: `tests/unit/test_adapters.py`

- [ ] Step 1: 同じSSOT参照の失敗testを書く

```python
from pathlib import Path

from adapters.codex.verify_adapter import verify as verify_codex
from adapters.claude.verify_adapter import verify as verify_claude


def test_both_adapters_resolve_the_same_skill_root() -> None:
    repo = Path(__file__).resolve().parents[2]
    assert verify_codex(repo)["skill_root"] == verify_claude(repo)["skill_root"]
    assert verify_codex(repo)["skill_count"] == 7
```

- [ ] Step 2: test失敗を確認

```powershell
python -m pytest tests/unit/test_adapters.py -q
```

期待結果: adapter module未実装で失敗。

- [ ] Step 3: read-only adapter verifierと日本語手順を実装

adapterはrepository内`skills/`への参照方法だけを説明・検証する。home directoryへ自動copy、symlink作成、設定変更を行わない。install commandはreview用に表示できるが実行しない。

- [ ] Step 4: testとadapter verifierを実行

```powershell
python -m pytest tests/unit/test_adapters.py -q
python adapters/codex/verify_adapter.py --repo . --json
python adapters/claude/verify_adapter.py --repo . --json
```

期待結果: 両方が同一絶対resolved root、7 skill、同一manifest hashをread-onlyで報告する。

- [ ] Step 5: commit

```powershell
git add -- adapters/__init__.py adapters/codex adapters/claude tests/unit/test_adapters.py
git diff --cached --check
git commit -m "feat: add Codex and Claude adapters"
```

### Task 9: live read-only E2Eとprivate canaryの停止境界

**Files:**

- Create: `scripts/run_read_only_e2e.py`
- Create: `scripts/run_private_canary.py`
- Create: `tests/e2e/test_live_read_only.py`
- Create: `tests/unit/test_private_canary_gate.py`
- Create: `docs/operations.md`

- [ ] Step 1: live input不足とcanary未承認の失敗testを書く

```python
from scripts.run_private_canary import CanaryRequest, validate_canary_request


def test_canary_requires_exact_confirmation() -> None:
    result = validate_canary_request(
        CanaryRequest(
            repo="example-org/fixture",
            visibility="PRIVATE",
            branch="canary/test",
            draft_pr_title="検証用canary",
            confirmed=False,
        )
    )
    assert result.status.value == "BLOCKED"
    assert result.code == "canary_confirmation_missing"


def test_canary_rejects_public_repo() -> None:
    result = validate_canary_request(
        CanaryRequest(
            repo="example-org/fixture",
            visibility="PUBLIC",
            branch="canary/test",
            draft_pr_title="検証用canary",
            confirmed=True,
        )
    )
    assert result.code == "canary_repo_not_private"
```

- [ ] Step 2: test失敗を確認

```powershell
python -m pytest tests/unit/test_private_canary_gate.py -q
```

期待結果: canary script未実装で失敗。

- [ ] Step 3: read-only runnerとdry-run-only canary packetを実装

`run_read_only_e2e.py`は次の環境変数を必須とし、未設定ならskipではなく`BLOCKED`で終了する。

- `GITHUB_OPS_LIVE_REPO=owner/name`
- `GITHUB_OPS_EXPECTED_OWNER=owner`
- `GITHUB_OPS_ACCOUNT_MAP=<overlay path>`

確認項目:

- expected loginとtoken login
- global active loginの事前値
- repo `nameWithOwner`
- visibility
- viewer permission
- default branch
- read-only PR list
- global active loginの事後値
- secret redaction

`run_private_canary.py`は既定でreview packet生成だけを行う。`--execute`と`--confirm-private-canary`の両方があっても、実装工程では実行しない。

- [ ] Step 4: offline testとlive read-only E2Eを実行

```powershell
python -m pytest tests/unit/test_private_canary_gate.py -q
python scripts/run_read_only_e2e.py --json
python scripts/run_private_canary.py --repo $env:GITHUB_OPS_LIVE_REPO --branch canary/github-ops-skills --draft-pr-title "GitHub操作経路canary" --review-packet docs/evidence/private-canary-review.json
```

期待結果:

- unit test成功。
- read-only E2Eは全項目`READY`でexit code 0。入力不足・不一致は非0。
- canaryは外部変更せずreview packetだけを生成。

- [ ] Step 5: global active account不変を明示確認

```powershell
$before = gh auth status --active 2>&1 | Out-String
python scripts/run_read_only_e2e.py --json
$after = gh auth status --active 2>&1 | Out-String
if ($before -cne $after) { throw 'global gh active account changed' }
```

期待結果: `$before -ceq $after`。

- [ ] Step 6: commit

```powershell
git add -- scripts/run_read_only_e2e.py scripts/run_private_canary.py tests/e2e/test_live_read_only.py tests/unit/test_private_canary_gate.py docs/operations.md docs/evidence/private-canary-review.json
git diff --cached --check
git commit -m "test: add read-only E2E and canary gate"
```

### Task 10: 公開準備文書、scan、review packet

**Files:**

- Create: `README.md`
- Create: `LICENSE`
- Create: `SECURITY.md`
- Create: `PUBLIC_READY.md`
- Create: `docs/architecture.md`
- Create: `docs/safety-boundary.md`
- Create: `docs/migration.md`
- Create: `docs/review-decision.md`
- Create: `tests/unit/test_repository_boundaries.py`
- Create: `docs/evidence/local-verification.json`

- [ ] Step 1: repository境界の失敗testを書く

```python
from pathlib import Path

from github_ops.public_identity import (
    scan_repository_for_personal_paths,
    scan_repository_for_token_shapes,
)


def test_public_readiness_files_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("README.md", "LICENSE", "SECURITY.md", "PUBLIC_READY.md"):
        assert (root / name).is_file(), name


def test_repository_contains_no_personal_absolute_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    offenders = scan_repository_for_personal_paths(root)
    assert offenders == []


def test_repository_contains_no_token_shaped_values() -> None:
    root = Path(__file__).resolve().parents[2]
    offenders = scan_repository_for_token_shapes(root)
    assert offenders == []
```

- [ ] Step 2: test失敗を確認

```powershell
python -m pytest tests/unit/test_repository_boundaries.py -q
```

期待結果: 必須文書未作成で失敗。

- [ ] Step 3: 日本語文書とMIT Licenseを作成

READMEは目的、安全境界、installしないread-only quick start、結果3状態、overlay例、保証レベルを説明する。`SECURITY.md`は脆弱性報告先を公開前に人間が確認する項目として明記する。`PUBLIC_READY.md`は現在値を自動断定せず、各検査の取得日時・command・結果を記録する。

- [ ] Step 4: 全testを実行

```powershell
python -m pytest -q
```

期待結果: 全offline testと、明示入力済みのlive read-only E2Eが成功。live testをpytest側でskipした場合はL3未保証として記録する。

- [ ] Step 5: secret・personal path・Git差分scanを実行

```powershell
rg -n -i 'gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|Authorization:\\s*Bearer\\s+\\S+' . -g '!docs/superpowers/plans/**'
python scripts/public_identity_guard.py --repo . --range HEAD --json
git diff --check HEAD
git status --short --branch
```

期待結果:

- secret pattern 0件。
- personal absolute path 0件。
- whitespace error 0件。
- 意図しないfile 0件。

- [ ] Step 6: Windows補助terminal smokeを実行

```powershell
python <SHARED_ROOT>\scripts\windows_terminal_flash_guard.py --repo <PROJECTS_ROOT> --smoke-count 3 --json
```

期待結果: 3回のsmokeが成功し、可視補助terminal違反0件。失敗時はローカル実装完了としない。

- [ ] Step 7: evidence JSONを保存し、事実来歴を検証

`docs/evidence/local-verification.json`は次を持つ。

```json
{
  "schema_version": "fact-provenance/v1",
  "recorded_at": "Asia/Tokyo RFC3339",
  "recorded_by": "codex",
  "claims": [
    {
      "classification": "fact",
      "claim": "offline tests passed",
      "actor": "pytest",
      "event_time": "Asia/Tokyo RFC3339",
      "scope": "local repository",
      "source": "python -m pytest -q",
      "observed_at": "Asia/Tokyo RFC3339"
    }
  ]
}
```

保存前に実測値で置換し、次で検証する。

```powershell
Get-Content docs/evidence/local-verification.json -Raw | python <CODEX_HOME>\skills\pre-execution-fact-check\scripts\validate_fact_provenance.py
```

期待結果: `PASS`。

- [ ] Step 8: review decision文書を完成

`docs/review-decision.md`へ次を記録する。

- 実装範囲
- commit一覧
- test件数と取得時刻
- L1、L2、L3の結果
- L4未実施であること
- scan結果
- 既知の制約
- GitHubに送信予定の全file
- private repository作成の正確な予定操作
- 推奨判断

- [ ] Step 9: commit

```powershell
git add -- README.md LICENSE SECURITY.md PUBLIC_READY.md docs/architecture.md docs/safety-boundary.md docs/migration.md docs/review-decision.md tests/unit/test_repository_boundaries.py docs/evidence/local-verification.json
git diff --cached --check
git commit -m "docs: add operations and review packet"
```

### Task 11: ローカルcloseoutと人間レビュー停止

**Files:**

- Modify: `PUBLIC_READY.md`
- Modify: `docs/review-decision.md`
- Modify: `docs/evidence/local-verification.json`

- [ ] Step 1: commit後の全検証を再実行

```powershell
python -m pytest -q
python scripts/run_read_only_e2e.py --json
python scripts/public_identity_guard.py --repo . --range HEAD --json
python adapters/codex/verify_adapter.py --repo . --json
python adapters/claude/verify_adapter.py --repo . --json
git fsck --no-dangling
git status --porcelain=v1
```

期待結果:

- offline test成功。
- live read-only E2E成功。
- identity scan成功。
- adapter結果一致。
- `git fsck`成功。
- worktree出力は空。

- [ ] Step 2: 現在の残務を4区分で記録

```text
ローカル実装: measured
private GitHub運用: L4未承認・未実施
人間レビュー: repository作成前review待ち
公開運用: 未承認・未実施
```

`measured`は実測結果に応じて`complete`、`blocked`、`unknown`へ置換する。未実施項目を完了扱いしない。

- [ ] Step 3: evidence更新だけをcommit

```powershell
git add -- PUBLIC_READY.md docs/review-decision.md docs/evidence/local-verification.json
git diff --cached --check
git commit -m "docs: record local verification evidence"
git status --short --branch
git log --oneline --decorate -12
```

期待結果: clean worktree。remoteは設定されていない。

- [ ] Step 4: 人間レビューへ提示して停止

提示する判断材料:

- repository予定名: `nexus-ai-2045/github-ops-skills`
- 正確な予定操作: private GitHub repository作成
- visibility: `private`
- commit history
- 送信予定file一覧
- test、L1–L3、scan、Windows smoke結果
- L4 canary review packet
- 既知の制約と未保証範囲
- global active account事前値

この時点でGitHub repository作成、remote追加、push、draft PR、canary、public化を実行しない。

## 計画の完了判定

この実装計画の実行完了には次をすべて必要とする。

- Task 1–11のcheckboxが実測結果に基づいて更新されている。
- offline testが成功している。
- live read-only E2Eが成功している。
- secret・personal path scanが成功している。
- Windows terminal flash guardが成功している。
- worktreeがcleanである。
- GitHub外部書き込みは未実施である。
- `docs/review-decision.md`に人間レビューの判断材料が揃っている。

private mutation canaryはこの計画の完了条件に含めず、別の明示承認後に実行する。
