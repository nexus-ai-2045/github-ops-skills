---
name: github-cli-ops-guard
description: GitHub CLI (`gh`) の有効アカウントのずれ、remote所有者の不一致、リポジトリ解決失敗、credential username差分、Git author差分、PRレビュー未吸収を、GitHub書き込み前後に検査する共有向け運用ゲート。不明な状態では操作を停止する。`git push`、`gh pr create`、`gh pr edit`、PRレビュー吸収、`gh pr merge`、レビュースレッド解決、branch整理、release/tag操作、GitHub issue/discussion書き込みの前後に使う。wrong account、active account、repo not found、GraphQL repository resolution、unresolved review threads、`gh auth switch`、`gh auth status`、`GITHUB_TOKEN`、credential username、owner mismatchに関するエラーや、「gh名義」「GitHub名義」「repo解決失敗」「マージ前確認」「PR前ゲート」「review吸収」「運用保証」「共有前提」の依頼にも使う。
---

# `GitHub CLI` 操作の安全確認

## 目的

非公開・共有・複数アカウントのワークスペースで、`gh` 操作のアカウントを安全に扱い、操作を追跡できるようにするために使う。

防ぐべき主な失敗は、`Git remote`・認証情報が指す所有者と `gh` の有効アカウントがずれ、リポジトリの読み書きに失敗したり、意図しない名義で操作したりすること。

## `FDE` の判断パケット

`GitHub` への書き込み前に、状況を次のパケットに整理する。

```text
entry: GitHub CLI operation
operation: push | pr_create | pr_edit | pr_merge | release | issue | discussion | visibility | read_only
repo: owner/name or local checkout
expected_owner:
expected_login:
active_gh_login:
remote_owner:
credential_username:
git_author:
publication_boundary: private | public | unknown
approval: current_turn_yes | missing | not_required_read_only
done_when: preflight ok + operation result verified + closeout clean
```

`operation` が `GitHub` の状態を変更する場合は、公開・人間レビューのゲートを先に適用する。リポジトリの公開範囲変更には、必ず対象リポジトリを指定した承認が必要。

## 必須の手順

1. ローカルの作業コピーまたは明示的な `--repo owner/name` から、対象リポジトリを特定する。
2. 同梱の読み取り専用検査を実行する。`github-ops-skills` 内で作業する場合は、このリポジトリのスクリプトを優先する。

```powershell
python scripts/gh_identity_probe.py --repo <repo-root> --json
# またはスキル内のコピー:
python skills/github-cli-ops-guard/scripts/gh_identity_probe.py --repo <repo-root> --expected-owner <owner> --expected-login <login> --json
```

   この`probe`は`fetch URL`だけでなく、`git remote get-url --all --push origin`で実効`push URL`を1件取得し、`credential`埋め込み・`GitHub scheme`不正・`fetch`先との`repository`不一致を検査する。`push URL`を確定できない場合は`error`として停止する。

3. リポジトリにより厳格な事前検査があれば、それも実行する。その場で解析処理を作るより、リポジトリ内または共有の既存スクリプトを優先する。
4. `status=error` / `BLOCKED` / `UNKNOWN` は、`GitHub` 書き込みの停止条件として扱う。`push`、`PR` 作成・編集、`merge`、`tag`、`release`、設定変更を実行しない。
5. 問題が有効アカウントのずれだけで、想定アカウントがすでに認証済みなら、検査が示す切替コマンドをそのまま実行し、検査を再実行する。

```powershell
gh auth switch --hostname github.com --user <expected_login>
```

6. `GitHub` への書き込み後は、読み取りコマンドで結果を確認する。さらに書き込みが残る場合は、名義検査を再実行する。

## `PR review` 吸収ゲート

`PR review` を吸収してから `merge` する時は、`GitHub GraphQL` `reviewThreads.isResolved` を解決状態の正本にします。`comment` 本文や `commit` の更新だけで「解決済み」と推定しません。

この `Core Suite` では、既存の `read-only helper` を吸収した次の `script` を使います。

```powershell
python scripts/github_pr_review_thread_audit.py --repo owner/name --pr N --json
# またはスキル内のコピー:
python skills/github-cli-ops-guard/scripts/github_pr_review_thread_audit.py --repo owner/name --pr N --json
```

- `exit` `0` / `decision=pass`: 未解決 `thread` なし、`pagination` 完了。
- `exit` `1` / `decision=warn`: 未解決 `current/outdated thread` あり、または `pagination` 未完了。吸収と `resolve` 後に再実行する。
- `exit` `1` / `decision=error`: `GitHub API error` または応答が壊れている。状態を推定せず停止する。

`gh pr merge` は `identity probe` と `review-thread audit` が通るまで実行しない。`merge` 自体は現在会話の明示承認が必要で、本 `skill` は `merge` を自動実行しない。

`GitHub Settings` の `Require conversation resolution` と `required checks` は `local command` や `repository file` だけでは保証できない。`Settings` 権限を持つ人間または管理 `API` の確認がない限り、`not_enabled_or_unverified` として扱う。

## `PR review thread resolve`（`review-disposition` 記録つき）

`Review / comment thread` は、返信に残した `review-disposition` の記録を `GitHub` が裏づけた時だけ閉じる。`comment` 本文の言い回しや `commit` の更新だけで「修正済み」と推定して `resolve` しない。

スレッドへ返信する時は、本文に次の印を 1 行だけ入れる（`HTML` コメントなので画面には出ない）。

```text
<!-- review-disposition: {"v":1,"kind":"fixed","commit":"<小文字40桁の commit>"} -->
<!-- review-disposition: {"v":1,"kind":"deferred","ref":"owner/repo#N"} -->
<!-- review-disposition: {"v":1,"kind":"dismissed","reason":"<理由>"} -->
```

- `JSON` の鍵は種類ごとに固定。余分な鍵、欠けた鍵、`v` が `1` 以外は不正。1 つの返信に印が 2 つ以上あっても不正。
- 採用する記録は、2 件目以降のコメントのうち、作者が `--expected-login` と一致し印を含む最後の物。最初のコメント（ボット本文）の印は読まない。採用した記録の後にコメントがあれば、名義を問わず保留（再指摘の扱い）。
- 最初のコメントの作者が `GitHub` 上の `Bot` でないスレッド（人のレビュアーが立てた物）は、記録があっても閉じない。
- `fixed`: 閉じてよいのは、`commit` が `head` の祖先か同一、指摘の `originalCommit` の厳密な子孫、`base` に含まれず、スレッドの `path` を変えている時だけ。変更ファイルが 300 件以上で切れている時と、マージコミット（親が 2 つ以上）の時は保留。
- `deferred`: 同じリポジトリの課題か `PR` が実在して開いており、この `PR` 自身でない時だけ閉じてよい。
- `dismissed`: 人が閉じる。
- 記録なし、印が不正、作者が違う、コメントのページが切れている、照合の `API` が失敗した場合は保留する。

```powershell
python scripts/github_pr_review_thread_audit.py --repo owner/name --pr N --json
python scripts/github_pr_review_thread_resolve.py --repo owner/name --pr N --expected-login LOGIN --json
python scripts/github_pr_review_thread_resolve.py --repo owner/name --pr N --apply --confirm --repo-root PATH --expected-owner OWNER --expected-login LOGIN --json
```

- `--apply` なしは判定だけ。各スレッドの `verdicts`（`resolvable` / `human` / `hold` / `already_resolved` と理由コード）を返し、変更操作は出さない。`--expected-login` が無いと全件保留。
- `--apply` は、判定が `resolvable` のスレッドだけ `resolveReviewThread` で閉じる。発行の直前に監査と記録を取り直して判定し直し、`head` / `base` が変わった、スレッドが未解決でなくなった、または閉じてよい組が変わっていれば 1 件も閉じずに止まる。`--thread-id` に監査に無い ID が混じる時も 1 件も閉じない。
- 部分的に閉じる。照合できた物だけ閉じ、残りは `materials` に理由コードつきで残る。操作後に未解決が残らなければ `ready`（終了コード `0`）、残れば `hold`、失敗は `error`（どちらも終了コード `1`）。
- `--apply` には既存 `write` 契約どおり `--confirm` と `IdentityProbe` 入力（`--repo-root` / `--expected-owner` / `--expected-login`）が必要。`GH_HOST` は `github.com` に固定する。
- `raw` `resolveReviewThread` や本文推定での `close` は使わない。
- 限界: 取り直しから発行までの短い間に付いた返信やボット本文の書き換えは捉えない。`--expected-login` は記録を書く名義と同じなので、人が同じ名義で返信しても別人とは区別できない（印の後のコメントは名義を問わず保留にして補う）。

## 停止条件

次のいずれかに該当する場合は停止し、人間に分かる言葉で説明する。

- `remote_owner` が `expected_owner` と異なる。
- `login` が指定されている場合に、`gh_active_login` が `expected_login` と異なる。
- `HTTPS credential username`は`identity`証拠として扱わない。`x-access-token`を含め、`API`が返す`login`で検証する。
- `Git remote` が示す存在するはずのリポジトリを、`gh repo view owner/name` で解決できない。
- `GITHUB_TOKEN` または `GH_TOKEN` が存在し、その名義が未確認。
- リポジトリの公開範囲が `public` または不明で、ユーザーがその対象と操作を明示承認していない。
- 対象操作が `gh pr merge`、`commands:register`、`release/tag`、公開範囲変更、`hook/settings/auth`、認証情報の変更で、現在のターンの承認がない。
- `merge` 候補に対して `github_pr_review_thread_audit.py` が `pass` 以外を返す。
- 作業ツリーに未コミット変更があり、その範囲を `GitHub` 書き込みに含めるか除外するかが明示されていない。
- `Git author` または `committer` が対象ワークスペースの公開名義ポリシー・拒否リストで個人用として拒否されている。`GitHub` 書き込み前に停止する。この手順で履歴を書き換えない。個人メールの具体値は共有するスキル本文へ複製せず、既存の拒否リストを参照する。
  同梱の名義検査は現在の `Git` 設定しか見ないので、この判定には使わない。送るコミット全件の `author` と `committer` を、ワークスペースの既存の範囲検査で確かめる（`Projects` では `python3 shared/scripts/github_account_context.py --check-range-identity --repo <repo> --login <login> --range <上流>..HEAD`。終了コード `0` 以外は停止）。この範囲検査がワークスペースに無い時は、名義を確かめられないものとして停止する。
- `github_pr_review_thread_resolve.py` が `hold` / `error` を返す。記録を裏づけられないスレッドは、判断材料として残す。

## 復旧の進め方

広範囲をリセットせず、問題の範囲に応じて復旧する。

| 症状 | 確認する原因 | 復旧方法 |
| --- | --- | --- |
| `GraphQL: Could not resolve to a Repository` | 有効な `gh` アカウントから対象リポジトリが見えない | `gh auth status --hostname github.com` で確認し、想定アカウントへ切り替えて検査を再実行する |
| `push` は成功するが `gh pr view` は失敗する | `Git` 認証情報と `gh` の有効アカウントが異なる | `gh auth switch` で揃え、リポジトリの表示を確認する |
| `gh` は正しいが `git clone` または `push` が別アカウントを要求する | `credential helper`または`token identity`が異なる | `token/API login`を検証し、`repo-local`な認証設定だけを修正して再実行 |
| `gh auth switch` は成功するがリポジトリ操作は失敗する | `token` の権限範囲または `session` が古い可能性 | `gh auth status` を実行する。権限範囲が変わる場合、承認後にのみ `gh auth refresh` を検討する |
| `remote` の所有者が違う | 作業コピーが意図したリポジトリではない | 停止する。誤った `remote` に合わせてアカウントを切り替えない |
| 想定所有者の候補が複数ある | 対象が曖昧 | 書き込み前に短い質問を一つする |
| レビュースレッドが未解決 | `merge` 候補に未完了の議論がある | 指摘を吸収し、スレッドを解決して監査を再実行する |

## 完了確認

該当する次の確認がすべて成立するまで、`GitHub` 操作を完了扱いにしない。

- 対象リポジトリと操作を明示した。
- `scripts/gh_identity_probe.py` または同等の事前検査が通った。
- 書き込みが承認された場合、そのコマンドが成功した。
- 読み取り専用コマンド（`gh pr view`、`gh pr checks`、`git rev-parse`、`gh release view` など）で結果を確認した。
- 開いている `PR`、`branch`、作業ツリーの未コミット変更の状態を説明した。
- 公開・外部操作の境界を明示した。
- アカウントのずれと復旧コマンドを平易に報告した。

## 参照先

`gh auth status`、`gh auth switch`、`token` の優先順位、複数アカウントの動作を診断する際は、`skills/github-cli-ops-guard/references/official-gh-auth.md` を読む。
