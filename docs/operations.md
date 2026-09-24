# 運用手順

## 日常確認

```powershell
python -m pytest -q
python adapters/codex/verify_adapter.py --repo . --json
python adapters/claude/verify_adapter.py --repo . --json
python adapters/grok/verify_adapter.py --repo . --json
python scripts/gh_identity_probe.py --repo . --json
python scripts/preflight_write_gate.py --repo . --expected-owner <owner> --expected-login <login> --json
```

接続順の正本: `docs/operating-card.md`

GitHub write 前の review thread 確認:

```powershell
python scripts/github_pr_review_thread_audit.py --repo owner/name --pr N --json
```

runtime skill との差分確認:

```powershell
python scripts/skill_drift_check.py --repo . --runtime codex --local-root <runtime-skills-root> --json
```

## コマンド実行の失敗と未完了の検査

`CommandResult.failure` が例外の区分を表します。`timed_out` は時間切れ、
`execution_failed` は起動・通信などの実行失敗です。実際の終了コード `124` / `127`
から例外を推定しません。例外時の `returncode=1` は既存の非ゼロ判定用です。
PR作成の成否が不明な場合は再作成せず、既存PRを読み取りで確認します。

`public_identity_guard.py` はGit tree内のファイルを一つでも読み取れないと
`UNKNOWN` を返します。未検査のファイルを読み飛ばして `READY` にはしません。

この結果契約の所有者は `src/github_ops/command.py` と各CLIの実装です。
採用条件は既存の `policy/invariants.json` の `GHO-EXEC-001` / `GHO-SCAN-001` に
登録し、`verify_invariant_registry.py` が登録削除・テスト欠落を検出します。
既存の `Core Suite CI` は全pytestと台帳検査を実行します。台帳検査だけの成功を
動作検証の代わりにはしません。公開前検査のCLIテストではJSONと終了値を照合します。

skillの配布・runtime有効化は配布側の既存入口の責務です。上記のローカルテストや
CIの成功から、home配布・全端末への反映・GitHub設定の有効化を推定しません。

マージ済みリモートbranchの棚卸しは、次のread-only入口を使います。

```sh
python scripts/github_remote_branch_audit.py \
  --repo owner/name --repo-root . \
  --expected-owner owner --expected-login login --json
```

この入口は、default branch、protected branch、PRの状態、branch HEADとPR HEADの一致を
分類します。`merged_head_exact` だけを削除候補として返し、closed/open/不明・HEAD変更は
保持します。削除やGitHub設定変更は実行しません。API応答・identity・JSONが確認できない
場合は `UNKNOWN` として停止します。

## Actions 実行枠

private repo の GitHub Actions は**課金しない**方針です（owner 判断、2026-09-24）。
無料枠を使い切ると、job は runner に割り当てられず、steps が 1 つも無いまま
数秒で failure になります。log は取得できません（404）。これはコードの失敗でも
flake でもありません。public repo の Actions は無料枠の対象外なので影響しません。

この状態では次のように扱います。

- `pr_convergence.checks_state_from_jobs`（`pr_convergence_decide.py` に `ci_jobs` と
  `workflow_files_changed` を渡すと使われます）が、失敗 job が全部「conclusion が
  `failure`・`runner_id` が `0`・steps なし」なら `not_executed` を返します。
  1 本でも実際に走って落ちた job があれば `failure`、`cancelled` だけなら待機です。
- PR が `.github/workflows` を変えている場合は `not_executed` にしません。workflow を
  壊した PR も runner なしで落ち、課金による未起動と区別できないためです。
- `not_executed` は `ci_not_executed` / `LOCAL_VERIFICATION` になります。同じ head で
  CI と同じ検査を手元で実行し、コマンドと結果を PR に記録します。
- コード修正（`NEEDS_REPAIR`）には進みません。課金・spending limit・visibility 変更を
  人間に問い直しません。枠は請求日にリセットされます。
- 手元検査は CI の代わりの証拠であり、CI が通ったことにはしません。PR にその旨を書きます。
- merge は従来どおり人間判断です。

## L3 読み取り専用の実環境検証

通常確認は`python scripts/run_read_only_e2e.py --json`で行います。GitHubの設定変更、
投稿、pushは行いません。必要な環境変数が欠ける場合は`BLOCKED`で停止します。

必要環境変数:

- `GITHUB_OPS_LIVE_REPO`
- `GITHUB_OPS_EXPECTED_OWNER`
- `GITHUB_OPS_ACCOUNT_MAP` (repository外のoverlay。exampleは`examples/account-repo-map.example.yaml`)

## L4 非公開環境での試行

private canaryはreview packetだけを生成します。現versionは`--execute`を指定しても
外部変更しません。実canaryは対象、visibility、送信内容を人間が確認した後の別工程です。

commit、push、PR作成は別々に人間確認を行います。PR作成時の日本語gateと作成後の
read-back手順は[`pr-japanese-gate.md`](pr-japanese-gate.md)を参照してください。

必須契約の一覧は[`README.md`](../README.md)の「必須契約」と
[`PUBLIC_READY.md`](../PUBLIC_READY.md)を正とします。新規gateは追加しません。
