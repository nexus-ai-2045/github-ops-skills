---
name: commit-push-pr
description: 変更を commit → push → PR 作成までワンコマンドで実行する。「push して PR まで」「PR 出して」「commit push pr」と言われたら使用する。main への push / PR 作成は必ずユーザー確認を挟む。commit のみ (quick-commit)、PR 状況確認 (pr-status)、マージには使わない。
---

# /commit-push-pr

現在の変更をコミット→プッシュ→PR作成までワンコマンドで実行する。

## 手順

1. `git status` と `git diff` で変更内容を確認
2. `git log --oneline -5` で最近のコミットスタイルを確認
3. 変更内容を分析してコミットメッセージをドラフト
   - repo固有のコミット規約があれば、その規約を優先する
   - 規約がなければ、日本語または英語から変更内容に合う言語を選ぶ
   - Conventional Commitsのtype/scope、コード識別子、API名は英語のままでよい
4. ユーザーにコミットメッセージを提示して確認
5. local検証とGitHub CIの対応を確認
   - 実行したtest、build、lint、adapter検証を列挙する
   - `.github/workflows/`とGitHub上のworkflow/checkを読み取り専用で確認する
   - localだけで実行され、GitHub CIに対応するcheckがない項目を明示する
   - CIが不足している場合は、PR作成前に「CIを追加するか」を必ずユーザーへ確認する
   - workflow追加とrequired check設定は別操作として扱い、settingsを自動変更しない
6. 承認されたら:
   - `git add` で関連ファイルをステージング（.env, credentials等は除外）
   - `git commit` でコミット（Co-Authored-By付き）
   - コミット後、`git rev-list --count origin/main..HEAD` で未push数をチェック
   - 未pushが1件以上 → 「未push {N}件。pushする？」とユーザーに確認
   - 承認 → mainなら `git push origin main`、ブランチなら `git push -u origin <branch>`
   - 拒否 → pushスキップ（次のコミット時にまた聞く）
   - push失敗（オフライン等） → エラーを伝えて終了（次回に持ち越し）
   - ブランチの場合、PR title/bodyを日本語でドラフトし、ユーザーへ提示して確認
   - PR bodyはUTF-8の一時ファイルへ保存し、次のgateを必ず実行する
     `python scripts/check_pr_japanese.py --title "<日本語title>" --body-file <body-file> --json`
   - gateが`READY`のときだけ、現在の会話でPR作成承認を再確認する
   - 承認後、次のwrapperで`gh pr create --body-file`と作成後read-backを実行する
     `python scripts/create_pr_with_japanese_gate.py --repo <owner/name> --base <base> --head <branch> --repo-root . --account-map <account-map> --expected-base-sha <base-sha> --expected-head-sha <head-sha> --title "<日本語title>" --body-file <body-file> --confirm --json`
   - wrapperが`UNKNOWN`または`BLOCKED`なら、PRを編集・再作成せず停止して報告する
7. 結果を返す

## 注意事項
- mainへのpushはユーザー確認を得てからOK
- .env, credentials.json 等のシークレットファイルはステージングしない
- コミットメッセージはユーザー確認後に実行
- ユーザー向け文書とPR title/bodyは日本語を既定にする
- `check_pr_japanese.py`を通さない直接の`gh pr create`は実行しない
- wrapper内のidentity、PRIVATE、権限、clean、local/remote head SHA、base SHA preflightを省略しない
- PR作成後はtitle/body/base/headをread-backし、承認済み入力との一致を確認する
- `gh` CLIが使えない場合はgit push URLを表示して手動PR作成を案内
- yuhitsu 等の公開協業 repo は push 前に local-verify-before-pr / yuhitsu-pr-local-identity-check (memory) を確認
