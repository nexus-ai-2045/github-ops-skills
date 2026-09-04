---
name: new-repo-bootstrap
description: >
  新しい GitHub repository を作る時の入口。「リポジトリを切る」「repo を新しく作る」「新規 repo」
  「git init したい」「gh repo create」「別リポジトリに分ける」「public で公開する repo を作る」と言われたら、
  自分で git init / gh repo create を組み立てず、必ずこの skill を使う。
  置き場所の固定・commit 名義・公開前文書・repo-preflight 検査・owner の token での作成・canonical wrapper 経由の
  初回 push・公開直後の lockdown・台帳登録・read-back を 1 本の script が順番に行う。
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
done_when: script の execute が READY + gh repo view で read-back 一致
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
   | `preflight_script: missing` | repo-preflight の checkout が無い | `~/Projects/Documents/.repos/nexus_ai/repo-preflight` を clone する |

2. **CEO の承認を現在会話で確認**する (repo 名 / visibility / 説明)。前の会話や「全部推奨で」の一括承認は
   名前と visibility が言われていれば有効。言われていなければ 1 問だけ聞く。

3. **execute**。同じ引数に `--confirm` を足す。

```bash
python3 <skill dir>/scripts/bootstrap_repo.py --name <name> --visibility <public|private> --description "<一文>" --confirm --json
```

   step は `preflight → prepare_local → set_identity → scaffold_docs → initial_commit → readiness_scan →
   create_remote → add_remote → push → lockdown → register → verify` の順。途中で `fail` が出たら
   それ以降は走らない。`steps` をそのまま報告し、失敗した step の `detail` を人間語に直して伝える。

4. **read-back を報告**する。`verify` の detail (`owner/name (visibility)`) と `register` の台帳 path を書く。
   `push: skipped` なら、示された wrapper コマンドを次の一手として書く (自分で `git push` しない)。

## 前提条件 (この repository の外にある実行前提)

- `gh` に owner の token が入っていること (script は `gh auth token --user <owner>` で取り、対象 process の env にだけ渡す)
- canonical push wrapper `~/Projects/shared/scripts/cc-push-resolved.sh` (無ければ push は skip され、手順が表示される)
- repo-preflight の checkout `<local-root>/repo-preflight/scripts/readiness_scan.py` (無ければ fail-closed。`--allow-no-preflight` は非推奨)
- account↔repo 台帳 `~/Projects/Documents/references/github-account-repo-map.md` (無ければ register は skip)

script が見つからない・止まった時は、別の手段で同じ操作を組み立てない。止めて報告する。

## やらないこと

- global の `gh auth switch`
- `git push` を直接叩く (wrapper 経由のみ)
- visibility の変更、repo の削除
- 既存 repo への適用 (origin がある directory は対象外)
