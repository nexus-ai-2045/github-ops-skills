---
name: new-repo-bootstrap
description: >
  新しい GitHub repository を作る時の入口。「リポジトリを切る」「repo を新しく作る」「新規 repo」
  「git init したい」「gh repo create」「別リポジトリに分ける」「public で公開する repo を作る」と言われたら、
  自分で git init / gh repo create を組み立てず、必ずこの skill を使う。
  置き場所の固定・commit 名義・公開前文書・repo-preflight 検査・owner の token での作成・公開直後の lockdown・
  canonical wrapper 経由の作業 branch push と API による main 作成・台帳登録 branch の commit・read-back を 1 本の script が順番に行い、
  台帳登録の push と PR は手順 4 で canonical wrapper から出す。
  Do NOT use for: 既存 repo への push / PR (commit-push-pr, github-cli-ops-guard)、公開判定の整備だけ (public-repo-readiness)。
---

# new-repo-bootstrap — 新規 repository は必ずこの経路で作る

## なぜこの skill があるか

push / PR / 公開判定には既に道具があるが、「repo を新しく立てる」瞬間には道具が無く、
場所・名義・台帳・アカウント・安全設定を毎回その場で組み立てて、どれかを落としていた
(2026-09-05 実測: 置き場所違い、Full FDE 未昇格、PUBLIC_READY/PREFLIGHT の食い違い)。
この skill はその工程を 1 本の fail-closed script に固定する。

## FDE Packet

新規 repository の作成は **公開 / 外部送信 / Type1** に当たる。作業前に Full FDE に上げ、次を切る。

```text
entry: new repository bootstrap
repository: <owner>/<name>
visibility: public | private
local_dir: ~/Projects/Documents/.repos/nexus_ai/<name>  (private は /private/<name>)
commit_identity: nexus_ai <273569186+nexus-ai-2045@users.noreply.github.com>  (owner=nexus-ai-2045 の既定)
approval: current_turn_yes | missing   ← visibility と名前を CEO が現在会話で言っていること
registry_pr: 台帳 repo への登録 PR (1 行追加) も同じ承認で出す。merge は人が行う
done_when: script の execute が READY + gh repo view で read-back 一致 + 台帳登録 PR の URL
```

`approval: missing` なら `--confirm` を付けない (preflight だけ)。

## 手順

1. **preflight (read-only)**。何も書かない。

```bash
python3 <skill dir>/scripts/bootstrap_repo.py --name <name> --visibility <public|private> --description "<一文>" --json
```

   結果の `checks` を見る。`token_login: ok` / `remote_absent: ok` / `commit_identity: ok|n/a` /
   `preflight_script: ok` でなければ止めて理由を報告する。よくある止まり方:

   | check | 意味 | 対処 |
   |---|---|---|
   | `token_login: missing` | owner の token が gh の keyring に無い | `gh auth login` は CEO が行う。script は切り替えない |
   | `token_login: mismatch` | token の login が owner と違う | 対象 owner の token を入れ直す。global account は触らない |
   | `remote_absent: exists` | GitHub に同名 repo が既にある | 名前を変えるか、既存 repo を使う (この skill の対象外) |
   | `local_dir: has_origin` | 手元の directory に origin が既にある | 既存 repo。commit-push-pr を使う |
   | `commit_identity: mismatch` | 既存 commit が個人名義 | 公開 repo には出せない。作り直す |
   | `preflight_script: missing` | repo-preflight の checkout が無い (preflight はここで BLOCKED) | `~/Projects/Documents/.repos/nexus_ai/repo-preflight` を clone する。`--allow-no-preflight` は非推奨 |
   | `local_dir: nested_in_other_repo` | 指定 directory が別 repo の中 | 別の場所を指定する |
   | `remote_absent: exists_visibility_<x>` | `--resume` 先の remote の visibility が指定と違う | 指定を合わせるか、visibility 変更を別承認で行う |
   | `registry_file: not_git` / `no_origin_main` | 台帳が git の外にある / 台帳 repo に origin/main が無い | 台帳は branch → PR でしか更新しない。台帳 repo の checkout を直す |
   | `registry_file: commit_wrapper_missing` | 台帳 repo の origin/main に `shared/scripts/cc-commit.sh` が無い | 台帳 repo を同期してから再実行する |
   | `registry_file: worktree_dir_not_ignored` | 台帳 repo の `.worktrees/` が ignore されていない (登録用 worktree が main checkout を汚す) | 台帳 repo の `.gitignore` を直す |

2. **CEO の承認を現在会話で確認**する (repo 名 / visibility / 説明)。前の会話や「全部推奨で」の一括承認は
   名前と visibility が言われていれば有効。言われていなければ 1 問だけ聞く。
   この承認には、手順 4 の台帳登録 PR (台帳 repo へ 1 行追加) を出すことも含めて伝える。

3. **execute**。同じ引数に `--confirm` を足す。

```bash
python3 <skill dir>/scripts/bootstrap_repo.py --name <name> --visibility <public|private> --description "<一文>" --confirm --json
```

   step は `preflight → prepare_local → set_identity → scaffold_docs → initial_commit → readiness_scan →
   create_remote → lockdown (public のみ、push より先) → add_remote → push → promote_main → register → verify` の順。
   途中で `fail` が出たらそれ以降は走らない。`steps` をそのまま報告し、失敗した step の `detail` を人間語に直して伝える。

   push は main に直接行わない。`bootstrap/init` branch を canonical wrapper で push し (両方の push guard が
   branch push だけを許可するため)、GitHub API でその commit から `main` を作って既定 branch にし、`bootstrap/init` を消す。
   `verify` は remote の `main` が local HEAD と同じ sha であることまで確認する。

   `register` は台帳 repo の main checkout に**書かない**。台帳 repo の origin/main を fetch し、
   `.worktrees/register-<name>` に `bootstrap/register-<name>` branch の worktree を切って行を足し、
   台帳 repo の `shared/scripts/cc-commit.sh` で commit する (push はしない)。branch の差分が台帳 1 file でなければ fail。
   origin/main の台帳に登録済みなら skipped。結果は report の `registration` (worktree / branch / commit / file) に出る。

   途中で止まった後は、同じ引数に `--resume` を足して再実行する (remote / origin / visibility が一致する時だけ続きから走る)。
   push だけ別経路で済ませた場合は `--resume --skip-push`。`register` の再実行は同じ branch に重ねて commit しない。

4. **台帳登録を PR にして、read-back を報告**する。`registration` が無い (register が skipped) なら PR は不要。
   ある時は、その worktree の中の wrapper を使う (台帳 repo の main checkout の wrapper は古いことがある)。

```bash
bash <worktree>/shared/scripts/cc-push-resolved.sh --repo <worktree> --branch <branch>
python3 <worktree>/shared/scripts/japanese_user_facing_gate.py <worktree>/pr-body.md
python3 <worktree>/shared/scripts/gh_write_guarded.py --repo-root <worktree> -- pr create --base main --head <branch> --title "<日本語の題>" --body-file <worktree>/pr-body.md
```

   - PR 本文は日本語で、どの repo を何のために登録するかを書く。本文 file は worktree の中に置き (日本語ゲートは
     その checkout の中の file しか検査しない)、PR を作った後に消す。commit しない。
   - 報告には `verify` の detail (`owner/name (visibility) main=<sha>`) と、登録 PR の URL を書く。merge は人が行う。
   - `push: fail` や登録 PR の push / 作成の拒否は、wrapper の deny 理由をそのまま書く (自分で `git push` / `gh pr create` しない)。
     登録 PR が出せない間も、owner が登録済みの login なら新 repo への push と PR 作成は owner からの名義導出で通る。

## 前提条件 (この repository の外にある実行前提)

- `gh` に owner の token が入っていること (script は `gh auth token --user <owner>` で取り、対象 process の env にだけ渡す)
- canonical push wrapper `~/Projects/shared/scripts/cc-push-resolved.sh` (無ければ push は fail。`bootstrap/init` を別経路で push して `--resume --skip-push`)
- repo-preflight の checkout `<local-root>/repo-preflight/scripts/readiness_scan.py` (無ければ fail-closed。`--allow-no-preflight` は非推奨)
- account↔repo 台帳 `~/Projects/Documents/references/github-account-repo-map.md` (無ければ register は skip)。
  台帳 repo が origin/main を持ち、そこに `shared/scripts/cc-commit.sh` があり、`.worktrees/` が ignore されていること
  (満たさなければ preflight が BLOCKED。repo を作ってから register で止まらないようにするため)

script が見つからない・止まった時は、別の手段で同じ操作を組み立てない。止めて報告する。

## やらないこと

- global の `gh auth switch`
- `git push` を直接叩く (wrapper 経由のみ)。main へ push しない (API で作る)
- 台帳 repo の main checkout へ書く (登録は origin/main から切った branch → PR だけ)
- visibility の変更、repo の削除
- 既存 repo への適用 (origin がある directory は対象外)
