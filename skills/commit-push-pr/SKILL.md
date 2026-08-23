---
name: commit-push-pr
description: 変更を commit → push → PR 作成までワンコマンドで実行する。「push して PR まで」「PR 出して」「commit push pr」と言われたら使用する。main への push / PR 作成は必ずユーザー確認を挟む。commit のみ (quick-commit)、PR 状況確認 (pr-status)、マージには使わない。
---

# /commit-push-pr

現在の変更をコミット→プッシュ→PR作成までワンコマンドで実行する。

## 手順

1. `git status` と、これから PR に入る差分全体で変更内容を確認
   - 一時 index に全部 stage して差分を取る。作業ツリーと本物の index は触らない

     ```bash
     set -Eeuo pipefail
     DIFF_BASE=$(git merge-base origin/<base> HEAD)
     LIVE_BASE=$(git rev-parse origin/<base>)
     TMPIDX_DIR=$(mktemp -d)
     trap 'rm -rf "$TMPIDX_DIR"' EXIT
     TMPIDX="$TMPIDX_DIR/index"
     GIT_INDEX_FILE="$TMPIDX" git read-tree HEAD
     GIT_INDEX_FILE="$TMPIDX" git add -A
     GIT_INDEX_FILE="$TMPIDX" git diff --cached "$DIFF_BASE"
     GIT_INDEX_FILE="$TMPIDX" git write-tree
     ```

   - `git add -A` を通すので、未 staged・staged・コミット済みに加えて
     **未 tracked の新規 file も中身ごと** 入る。`.gitignore` 済みは入らない
     (手順 7 の `git add` でも commit されないので範囲が一致する)
   - 素の `git diff` は未 staged だけ、`git diff "$BASE"` は未 tracked を落とす。
     どちらも手順 7 が push する範囲より狭く、新規 file が確認を素通りする
2. `git log --oneline -5` で最近のコミットスタイルを確認
3. 変更内容を分析してコミットメッセージをドラフト
   - repo固有のコミット規約があれば、その規約を優先する
   - 規約がなければ、日本語または英語から変更内容に合う言語を選ぶ
   - Conventional Commitsのtype/scope、コード識別子、API名は英語のままでよい
4. ユーザーにコミットメッセージを提示して確認
5. skill と一緒に配布される `references/pr-self-review.md` のセルフレビューを、手順 1 で取った差分
   （= これから push して PR に入る範囲の全体。未 tracked の新規 file を含む）に当てる
   - 複数リポジトリのレビュー指摘を一般化した停止条件 R1〜R14 と、20 項目の確認表
   - 該当した項目は、直してから次へ進む。R1/R8/R11などの停止条件が `blocked` / `unknown`
     のままなら commit・push を停止する。PR本文への事後説明は解除にならない。
     例外は、対象・影響・期限を明記した人間のリスク承認を commit・push より前に記録した場合だけ
     とする（mainへのpushには適用しない）
   - この file は生成物。手で編集しない (CI が本文 hash と配布コピー一致で検出する)
6. local検証とGitHub CIの対応を確認
   - 実行したtest、build、lint、adapter検証を列挙する
   - `.github/workflows/`とGitHub上のworkflow/checkを読み取り専用で確認する
   - localだけで実行され、GitHub CIに対応するcheckがない項目を明示する
   - CIが不足している場合は、PR作成前に「CIを追加するか」を必ずユーザーへ確認する
   - workflow追加とrequired check設定は別操作として扱い、settingsを自動変更しない
   - 5 または 6 の修正を行ったら、手順 1 の完全差分を取り直し、セルフレビューを最初から再実行する
   - 最終レビューで、`DIFF_BASE`（差分の共通祖先）と `LIVE_BASE`（`git rev-parse origin/<base>` の現在値）を
     分けて記録する。PR wrapperの `--expected-base-sha` には `LIVE_BASE` を使う。あわせて branch、prospective diff、
     `git write-tree` の `REVIEWED_TREE` を記録する。
     commit直前に一時 index で同じ tree を再計算し、値が変わったら停止する。commit後は
     `git rev-parse HEAD^{tree}` と `REVIEWED_TREE` が一致することを確認する。PRのbase SHAが変わった場合は、
     head SHAが同じでも旧レビューを再利用しない。`.github/workflows/pr-self-review-trusted.yml` の
     `workflow_dispatch` にPR番号を指定して、base/head組を再検査する
7. 承認されたら:
   - `git add` で関連ファイルをステージング（.env, credentials等は除外）
   - `git commit` でコミット（Co-Authored-By付き）。手順 5 の最終レビューと同じ tree であることを確認する
   - コミット後、`git rev-list --count origin/main..HEAD` で未push数をチェック
   - 未pushが1件以上 → 「未push {N}件。pushする？」とユーザーに確認（未解決の停止条件があれば確認前に停止）
   - 承認 → mainなら `git push origin main`、ブランチなら `git push -u origin <branch>`
   - 拒否 → pushスキップ（次のコミット時にまた聞く）
   - push失敗（オフライン等） → エラーを伝えて終了（次回に持ち越し）
   - ブランチの場合、PR title/bodyを日本語でドラフトし、ユーザーへ提示して確認
   - PR title/bodyはUTF-8の一時ファイルへ保存し、shell展開を避けて次のgateを必ず実行する
     `python scripts/check_pr_japanese.py --title-file <title-file> --body-file <body-file> --json`
   - gateが`READY`のときだけ、現在の会話でPR作成承認を再確認する
   - 承認後、次のwrapperで`gh pr create --body-file`と作成後read-backを実行する
     `python scripts/create_pr_with_japanese_gate.py --repo <owner/name> --base <base> --head <branch> --repo-root . --account-map <account-map> --expected-base-sha <base-sha> --expected-head-sha <head-sha> --expected-visibility PRIVATE --title-file <title-file> --body-file <body-file> --confirm --json`
   - wrapperが`UNKNOWN`または`BLOCKED`なら、PRを編集・再作成せず停止して報告する
8. 結果を返す

## 注意事項
- mainへのpushはユーザー確認を得てからOK
- .env, credentials.json 等のシークレットファイルはステージングしない
- コミットメッセージはユーザー確認後に実行
- ユーザー向け文書とPR title/bodyは日本語を既定にする
- `check_pr_japanese.py`を通さない直接の`gh pr create`は実行しない
- wrapper内のidentity、期待visibility、権限、clean、local/remote head SHA、live base SHA preflightを省略しない
- visibilityは既定`PRIVATE`とし、公開repositoryでは人間承認後に限り`--expected-visibility PUBLIC`を明示する。visibility自体は変更しない
- PR作成後はtitle/body/base/headをread-backし、承認済み入力との一致を確認する
- `gh` CLIが使えない場合はgit push URLを表示して手動PR作成を案内
- yuhitsu 等の公開協業 repo は push 前に local-verify-before-pr / yuhitsu-pr-local-identity-check (memory) を確認
