# 運用手順

## 日常確認

```powershell
python -m pytest -q
python adapters/codex/verify_adapter.py --repo . --json
python adapters/claude/verify_adapter.py --repo . --json
python adapters/grok/verify_adapter.py --repo . --json
python scripts/gh_identity_probe.py --repo . --json
python scripts/preflight_write_gate.py --repo . --json
```

接続順の正本: `docs/operating-card.md`

GitHub write 前の review thread 確認:

```powershell
python scripts/github_pr_review_thread_audit.py --repo owner/name --pr N --json
```

runtime skill との差分確認:

```powershell
python scripts/skill_drift_check.py --repo . --local-root <runtime-skills-root> --json
```

## L3 read-only E2E

通常確認は`python scripts/run_read_only_e2e.py --json`で行います。GitHubの設定変更、
投稿、pushは行いません。必要な環境変数が欠ける場合は`BLOCKED`で停止します。

必要環境変数:

- `GITHUB_OPS_LIVE_REPO`
- `GITHUB_OPS_EXPECTED_OWNER`
- `GITHUB_OPS_ACCOUNT_MAP` (repository外のoverlay。exampleは`examples/account-repo-map.example.yaml`)

## L4 private canary

private canaryはreview packetだけを生成します。現versionは`--execute`を指定しても
外部変更しません。実canaryは対象、visibility、送信内容を人間が確認した後の別工程です。
