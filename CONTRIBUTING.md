# 貢献のしかた

この repository は GitHub 操作を fail-closed で止める Core Suite です。大きい変更を足す前に、既存の `skills/`・`scripts/`・sibling 正本を確認してください。新しい protocol は作りません。

## 確認順

1. 既存 skill / script / sibling repo（`repo-preflight`、`ai-ratchet-gate`）に同じ仕事がないか
2. 変更は小さい PR にする
3. 検証してから PR を出す
4. push / PR / merge / Settings 変更はそれぞれ別の承認

## ローカル確認

Python 3.11 以上。token は環境変数だけに置き、file へ書きません。

POSIX（Linux / macOS）:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python adapters/codex/verify_adapter.py --repo . --json
.venv/bin/python adapters/claude/verify_adapter.py --repo . --json
.venv/bin/python adapters/grok/verify_adapter.py --repo . --json
git diff --check
git status --short --branch
```

Windows（PowerShell）:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe adapters/codex/verify_adapter.py --repo . --json
.\.venv\Scripts\python.exe adapters/claude/verify_adapter.py --repo . --json
.\.venv\Scripts\python.exe adapters/grok/verify_adapter.py --repo . --json
git diff --check
git status --short --branch
```

Grok を使っている場合だけ、runtime 差分も見ます。`$HOME/.grok/skills` が無い checkout では省略してください。

```sh
.venv/bin/python scripts/skill_drift_check.py --repo . --runtime grok --local-root "$HOME/.grok/skills" --json
```

`ai-ratchet-gate` は GitHub Actions が Release wheel を pin して実行します。ローカルで同じ検査をする場合も、PyPI 名ではなく公開 Release の wheel を使います。

公開面・L3 の既存検査（新規 script は足さない）:

```sh
status_code=$(curl -sS -o /dev/null -w "%{http_code}" "https://github.com/nexus-ai-2045/github-ops-skills")
.venv/bin/python scripts/check_visibility_claim.py --public-ready PUBLIC_READY.md --status-code "$status_code" --json
.venv/bin/python scripts/public_identity_guard.py --repo . --json
# L3 read-only（repository外 overlay。未設定や auth 不能は BLOCKED/UNKNOWN）
# 手順: docs/operations.md
# GITHUB_OPS_LIVE_REPO / GITHUB_OPS_EXPECTED_OWNER / GITHUB_OPS_ACCOUNT_MAP
.venv/bin/python scripts/run_read_only_e2e.py --json
```

PR 上の既存 workflow 名: `Core Suite CI`、`ai-ratchet-gate`、`PR日本語gate`、`PRセルフレビュー（base監査 advisory）`。件数の正本は最新の CI / ローカル pytest 出力と [PUBLIC_READY.md](PUBLIC_READY.md)。

## PR

- title と本文は日本語。見出しは日本語。英語だけの見出しは不可
- 手順は [docs/pr-japanese-gate.md](docs/pr-japanese-gate.md)
- 本文に目的、変更、検証、残リスク、人間の停止線を書く
- `git add -A` は使わない

## 禁止

- secret / token / 個人の絶対パスを commit する
- Settings（required checks、secret scanning、visibility）を PR と同じ差分で変える
- ratchet エンジンや repo-preflight scanner をこの repo へコピーする
