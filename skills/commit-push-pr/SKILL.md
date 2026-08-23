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
     STATE="$(git rev-parse --git-dir)/pr-self-review"   # .git配下。commit対象に入らない
     mkdir -p "$STATE"

     # shallow cloneでは merge-base が祖先を見つけられない。先に深さを回復する
     if [ "$(git rev-parse --is-shallow-repository)" = true ]; then
       git fetch --unshallow origin <base> || git fetch --deepen=2147483647 origin <base>
     else
       git fetch origin <base>
     fi
     LIVE_BASE=$(git rev-parse FETCH_HEAD)
     DIFF_BASE=$(git merge-base FETCH_HEAD HEAD)

     INTENDED_PATHS=(<approved path 1> <approved path 2> ...)
     if ((${#INTENDED_PATHS[@]} == 0)); then echo 'no intended paths'; exit 2; fi
     TMPIDX_DIR=$(mktemp -d)
     trap 'rm -rf "$TMPIDX_DIR"' EXIT
     TMPIDX="$TMPIDX_DIR/index"
     GIT_INDEX_FILE="$TMPIDX" git read-tree HEAD
     GIT_INDEX_FILE="$TMPIDX" git add -A -- "${INTENDED_PATHS[@]}"
     GIT_INDEX_FILE="$TMPIDX" git diff --cached "$DIFF_BASE"
     REVIEWED_TREE=$(GIT_INDEX_FILE="$TMPIDX" git write-tree)

     # 手順7は別shellで動く。変数は消えるのでfileへ残す
     printf '%s\n' "$REVIEWED_TREE" > "$STATE/reviewed_tree"
     printf '%s\n' "$LIVE_BASE"     > "$STATE/live_base"
     printf '%s\n' "$(git rev-parse HEAD)" > "$STATE/reviewed_head"
     printf 'REVIEWED_TREE=%s DIFF_BASE=%s LIVE_BASE=%s\n' "$REVIEWED_TREE" "$DIFF_BASE" "$LIVE_BASE"
     ```

   - 初回 push（remote に `<base>` が無い / HEAD が unborn）はこの手順の対象外。
     `git fetch` が exit 128 で止まり、`read-tree HEAD` も通らない。
     その場合は **手順 1 をレビュー範囲の宣言だけに読み替える**:
     `DIFF_BASE` を空文字にし、`GIT_INDEX_FILE="$TMPIDX" git diff --cached` （base 指定なし）で
     全 file を差分として出し、同じセルフレビューを当てる。`LIVE_BASE` は記録せず、
     PR wrapper も使わない（初回 push に PR は存在しない）

   - `INTENDED_PATHS` は承認済みの関連ファイルを明示する。未 staged・staged・未 trackedのうち
     そのpathだけを一時indexへ取り込み、無関係差分やcredential候補をレビュー対象・commit対象へ混ぜない
   - `git fetch` を先に通してから `FETCH_HEAD` で解決する。`origin/<base>` の remote-tracking ref は
     古い・single-branch cloneに無い・force-push前を指す、のいずれもありうる。fetch が失敗したら
     `set -Eeuo pipefail` でここで止まる（古い値のままレビュー範囲を決めない）
   - `REVIEWED_TREE` / `LIVE_BASE` は `$(git rev-parse --git-dir)/pr-self-review/` へ書く。
     手順 7 は承認を挟んだ別 shell で動くので、変数のままでは消える。
     `.git` 配下なので commit 対象にも `.gitignore` の対象にもならない
   - 素の `git diff` は未 staged だけ、`git diff "$DIFF_BASE"` は未 tracked を落とす。
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
   - trusted gate workflow・検査器を変更する場合は、同じPRのhead側だけで承認しない。
     base側のprotected gate比較で停止し、別のtrusted changeとして隔離検証する
6. local検証とGitHub CIの対応を確認
   - 実行したtest、build、lint、adapter検証を列挙する
   - `.github/workflows/`とGitHub上のworkflow/checkを読み取り専用で確認する
   - localだけで実行され、GitHub CIに対応するcheckがない項目を明示する
   - CIが不足している場合は、PR作成前に「CIを追加するか」を必ずユーザーへ確認する
   - workflow追加とrequired check設定は別操作として扱い、settingsを自動変更しない
   - `pr-self-review-trusted.yml` はbase側から候補を監査する advisory であり、PR head SHAに結び付く
     required checkではない。merge許可やrequired設定の証拠として扱わず、人間bootstrap判断を残す
   - 5 または 6 の修正を行ったら、手順 1 の完全差分を取り直し、セルフレビューを最初から再実行する
   - 最終レビューで、`DIFF_BASE`（差分の共通祖先）と `LIVE_BASE`（fetch 後の `FETCH_HEAD`）を
     分けて記録する。PR wrapperの `--expected-base-sha` には `LIVE_BASE` を使う。あわせて branch、prospective diff、
     `git write-tree` の `REVIEWED_TREE` を記録する。
     照合は手順 7 が commit の前後で行う（値は `$(git rev-parse --git-dir)/pr-self-review/` 経由で渡す）。
     PRのbase SHAが変わった場合は、
     head SHAが同じでも旧レビューを再利用しない。再検査は手順 1 をやり直す
     （新しい base を fetch し直して `DIFF_BASE` / `LIVE_BASE` / `REVIEWED_TREE` を取り直し、
     セルフレビューを最初から実行する）。これは skill 同梱物だけで完結する。
     配布先に `.github/workflows/pr-self-review-trusted.yml` がある場合に限り、
     `workflow_dispatch` にPR番号を渡したbase側監査を追加で回してよい（必須ではない）
7. 承認されたら:
   - 手順 1 の `INTENDED_PATHS` と同じ path だけを `git add` でステージングする
   - **commit する前後の両方**で、tree が `REVIEWED_TREE` と一致することを確認する

     ```bash
     set -Eeuo pipefail
     STATE="$(git rev-parse --git-dir)/pr-self-review"
     REVIEWED_TREE=$(cat "$STATE/reviewed_tree")   # 手順1のshellは終了済み。fileから復元する
     case "$REVIEWED_TREE" in [0-9a-f][0-9a-f]*) ;; *) echo 'reviewed tree missing'; exit 2 ;; esac
     test "$(git rev-parse HEAD)" = "$(cat "$STATE/reviewed_head")" \
       || { echo 'HEAD moved since review'; exit 2; }

     # (1) commit 前: git add より前から index に残っていた無関係な stage 済み entry を検出
     test "$(git write-tree)" = "$REVIEWED_TREE" || { echo 'index differs from reviewed tree'; exit 2; }

     git commit ...

     # (2) commit 後: pre-commit hook が index を書き換えた場合はここで初めて分かる。
     #     検出だけでは未レビューの commit が残るので、必ず巻き戻す
     if [ "$(git rev-parse 'HEAD^{tree}')" != "$REVIEWED_TREE" ]; then
       git reset --soft HEAD@{1}
       echo 'a hook rewrote the tree; commit rolled back. re-review from step 1'
       exit 2
     fi
     rm -f "$STATE/reviewed_tree" "$STATE/reviewed_head" "$STATE/live_base"
     ```

     `REVIEWED_TREE` は手順 1 の shell 変数ではなく **file から読み直す**。承認を挟むため
     手順 7 は別 shell で動き、変数は消えている（空文字と比較して常に停止してしまう）
   - hook を `--no-verify` で無効化しない。ratchet や secret 検査を同時に外すことになる。
     hook に書き換えられたら **commit を巻き戻して手順 1 からやり直す** のが正しい復帰手順
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
