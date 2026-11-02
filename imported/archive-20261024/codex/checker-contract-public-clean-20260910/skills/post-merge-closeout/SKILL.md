---
name: post-merge-closeout
description: "PRマージ後に、残務ゼロ、マージ済み?, closeout, 運用保証, PR閉じた?, open PR残, branch削除、またはPR単体とrepo全体TODOの混線を避けたい時に使う。post_merge_closeout_report.pyでGitHub/Git証跡をread-only収集し、PR単体、repo全体、次の1手に分けて日本語優先で報告する。"
---

# post-merge-closeout

## 目的

このskillは、PR（プルリクエスト）マージ後の確認を小さく、再現可能にし、発散させないために使う。

このskillはプロダクト方針を判断しない。証跡を集め、既存の
`post_merge_closeout:` packetを評価し、結果を次の3箱で報告する。

1. PR単体
2. repo全体
3. 次の1手

## 必要な入力

- 対象repo。できれば `owner/name`。
- 対象PR番号。
- 利用可能ならlocal checkout path。

PR番号が不明な時は、browser ambient stateだけで断定しない。repoが分かっているならread-onlyのPR listで確認するか、短く1問だけ確認する。

## 前提条件

この手順が呼ぶ 2 つの script は **この repository には無い**。host workspace
（`shared/scripts/` を持つ側）から実行することを前提とする。

- `shared/scripts/post_merge_closeout_report.py` — merge 証跡の収集
- `shared/scripts/post_merge_cleanup.py` — worktree / local branch の cleanup

この repository を単体で clone しただけでは手順 3 以降は実行できない。
script が見つからない時は **代替を自作せず、そこで止めて報告する**。
自作すると同じ処理の実装が増え、どれが正本か分からなくなる。

なお `post_merge_cleanup.py` は同名の script が複数ある。この手順が要求する
`--check` と `--confirm-merged-branch` を持つのは host workspace 側のもので、
fractal-decision-ecosystem の `scripts/post_merge_cleanup.py` は別実装であり
これらの option を持たない。取り違えないこと。

## 手順

1. 対象PR番号とrepoを確認する。
2. 実行するcommandがread-onlyであることを確認する。このskillではapprove、merge、push、branch削除、PR編集をしない。
3. repo rootからcollectorを実行する。

```bash
python3 shared/scripts/post_merge_closeout_report.py collect --repo <owner/name> --pr <number> --json
```

4. collectorはGitHub CLI（GitHub command line interface）のaccount contextを先に検査する。drift時はGitHub APIを呼ぶ前に停止し、`github-cli-ops-guard` の修復経路を表示する。
5. 現在会話でauth切替の明示承認があり、対象repoのaccount mapが登録済みなら、次の明示オプションで安全切替と収集を一度に行う。

```bash
python3 shared/scripts/post_merge_closeout_report.py collect --repo <owner/name> --pr <number> --switch-account-if-needed --json
```

承認がない時はこのオプションを付けない。
6. 対象PRのcloseoutがpassした後、local branch / worktreeを棚卸しする。

```bash
git worktree list --porcelain
git -C <target-worktree> status --porcelain --ignored
git ls-remote --heads origin <target-branch>
python3 shared/scripts/post_merge_cleanup.py --check --cwd <repo-root> --json
```

7. 次の条件をすべて満たす対象だけをcleanup候補にする。
   - 対象PRが `MERGED`
   - remote branchが `not_found`
   - 対象worktreeがclean
   - 対象branchが `main` ではない
   - 現在処理中のworktreeではなく、別worktreeから削除できる
   - 別セッション所有・用途不明ではない
8. worktree削除とlocal branch削除はwrite操作として、現在会話の明示承認後だけcleanupを適用する。

```bash
python3 shared/scripts/post_merge_cleanup.py --apply --cwd <repo-root> \
  --confirm-merged-branch <target-branch> --json
```

cleanupはlinked worktree内の `Documents/runtime/push-audit.jsonl` をrepo rootの正本へ
JSON object単位で重複なく統合し、全行を検証してからworktree → local branchの順で削除する。
Python cache、pytest cache、0 byteの `pipeline_dispatcher.log` 以外の未知ignored file、
dirty / locked / owner不明のworktreeは削除せず、`保留: 理由` として報告する。
`gone-upstream` はremote削除だけではmerge証明にならないため、collectorで対象PRが
`MERGED` と確認できたbranchだけを `--confirm-merged-branch` へ渡す。
9. 結果は下の出力形で報告する。

## 出力形

```text
PR単体:
- [事実: command] state / merged_at / merge_commit / remote_main / remote_branch

repo全体:
- [事実: command] open_pr_count と open PR一覧

local整理:
- [事実: command] target worktree / local branch / clean判定 / cleanup結果

次の1手:
- passなら「このPR単体は閉じた」
- repo全体にopen PRがあれば「残りはPR #N」
- command failureなら人間語で原因を1行
```

## 解釈ルール

- `decision=pass` は、対象PRのmerge commitが現在のremote mainに含まれ、対象branchが消えていることを意味する。
- repo全体にopen PRが残っているだけで、対象PRの失敗扱いにしない。
- すべての返答で `PR単体` と `repo全体` を分ける。
- command evidenceで `target_diff: ok`、`remote_branch: not_found` が出ており、残queueも明示できる時だけ運用保証と言う。

## 停止線

次のwrite操作の前で止める。

- `gh pr review`
- `gh pr merge`
- `git push`
- collectorのread-only証跡確認を超えるbranch deletion
- worktree removal / local branch deletion
- hook/settings/auth/secrets変更

ユーザーがこれらの操作を依頼した時は、先に対応するGitHub/FDE gateへ切り替える。
