# 運用手順

通常確認は`python scripts/run_read_only_e2e.py`で行います。GitHubの設定変更、
投稿、pushは行いません。必要な環境変数が欠ける場合は`BLOCKED`で停止します。

private canaryはreview packetだけを生成します。現versionは`--execute`を指定しても
外部変更しません。packetにはtarget repo、branch、Draft PR、変更対象path、正確な操作順、
success/failure evidence、cleanupを含む停止線を記録します。

```powershell
python scripts/run_private_canary.py `
  --repo nexus-ai-2045/github-ops-skills `
  --branch canary/github-ops-skills `
  --draft-pr-title "GitHub操作経路canary" `
  --review-packet docs/evidence/private-canary-review.json
```

実canaryは対象、使用account、marker内容、Draft PR本文、外部から見える範囲を人間が
確認し、現在会話でpushとDraft PR作成を明示承認した後の別工程です。Draft PR closeと
remote branch削除はcleanupとして別承認を必要とし、自動実行しません。

人間レビュー後の実行commandは次です。このcommandはbranch pushとDraft PR作成を行うため、
表示された文字列全体に対する現在会話の明示承認が必要です。

```powershell
python scripts/execute_private_canary.py `
  --repo . `
  --target-repo nexus-ai-2045/github-ops-skills `
  --branch canary/github-ops-skills `
  --draft-pr-title "GitHub操作経路canary" `
  --expected-account nexus-ai-2045 `
  --approval-ref L4-CANARY:nexus-ai-2045/github-ops-skills:canary/github-ops-skills `
  --confirm-private-canary `
  --execute `
  --report-path docs/evidence/private-canary-execution.json
```

runnerはclean worktree、remote、account、PRIVATE、permission、default branch、canary branch
不存在をpush前に検証します。途中失敗後の自動cleanupは行いません。
