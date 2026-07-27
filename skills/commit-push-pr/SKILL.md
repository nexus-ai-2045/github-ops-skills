---
name: commit-push-pr
description: 変更を commit → push → PR 作成までワンコマンドで実行する。「push して PR まで」「PR 出して」「commit push pr」と言われたら使用する。main への push / PR 作成は必ずユーザー確認を挟む。Do NOT use for: commit のみ (quick-commit)、PR 状況確認 (pr-status)、マージ (実行しない)。
---

# /commit-push-pr

現在の変更をコミット→プッシュ→PR作成までワンコマンドで実行する。

## 手順

1. `git status` と `git diff` で変更内容を確認
2. `git log --oneline -5` で最近のコミットスタイルを確認
3. 変更内容を分析してコミットメッセージをドラフト（英語・imperative mood）
4. ユーザーにコミットメッセージを提示して確認
5. 承認されたら:
   - `git add` で関連ファイルをステージング（.env, credentials等は除外）
   - `git commit` でコミット（Co-Authored-By付き）
   - コミット後、`git rev-list --count origin/main..HEAD` で未push数をチェック
   - 未pushが1件以上 → 「未push {N}件。pushする？」とユーザーに確認
   - 承認 → mainなら `git push origin main`、ブランチなら `git push -u origin <branch>`
   - 拒否 → pushスキップ（次のコミット時にまた聞く）
   - push失敗（オフライン等） → エラーを伝えて終了（次回に持ち越し）
   - ブランチの場合、必要に応じて `gh pr create` でPR作成
6. 結果を返す

## 注意事項
- mainへのpushはユーザー確認を得てからOK
- .env, credentials.json 等のシークレットファイルはステージングしない
- コミットメッセージはユーザー確認後に実行
- `gh` CLIが使えない場合はgit push URLを表示して手動PR作成を案内
- yuhitsu 等の公開協業 repo は push 前に local-verify-before-pr / yuhitsu-pr-local-identity-check (memory) を確認
