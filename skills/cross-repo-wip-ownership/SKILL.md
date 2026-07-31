---
name: cross-repo-wip-ownership
description: 複数repositoryやworktreeの未commit変更がGitHub操作を止めたとき、所有者・期限・依存関係・secretリスクを台帳で検証し、allow／warn／blockへfail-closed分類する。sibling dirty、unknown WIP、並列agentの変更衝突、pre-push gateの反復停止を安全に解消するときに使う。
---

# Cross-repository WIP ownership

別repositoryの未commit変更を消去、stash、迂回せず、誰が何のために所有しているかを確認してGitHub操作の停止判断へ返す。

## 手順

1. 対象GitHub操作と、停止させている変更pathを読み取り専用で実測する。
2. `wip-ownership/v1`台帳からpathに一致するentryを探す。
3. exactとprefixを明示的に区別する。0件または複数一致は`block`にする。
4. owner、scope、reason、return_pathを確認する。
5. 実diffのSHA-256 fingerprintとsecret scan結果を取得する。台帳の自己申告を実測証拠の代用にしない。
6. timezone付き`recorded_at`と`expires_at`、`recorded_by`、`dependency`、`secret_risk`を現在時刻で再検証する。leaseは記録時刻から最大24時間にする。
7. 判定器へ変更path、台帳entry、実測証拠を渡し、結果をGitHub操作gateへ返す。

## 判定契約

- `allow`: `known_generated=true`で、ownerが有効、期限内、独立、実測diff一致、実測secret scanがclearの場合だけ。
- `warn`: 有効なownerが期限内で所有し、対象操作と独立し、実測diff一致、実測secret scanがclearの場合。
- `block`: owner不明、期限切れ、依存あり／不明、secret疑い／不明、台帳なし、曖昧一致。

台帳の`classification`は安全条件を緩和できない。`allow`と書かれていても生成物条件を満たさなければ`block`する。

## 停止境界

- `--no-verify`などでgateを迂回しない。
- 他担当の変更をcommit、stash、削除、復元しない。
- push、PR作成、merge、公開、auth切替は現在会話の別承認を必要とする。

## 返却

対象pathごとにclassification、reason code、ownerを返す。`block`では影響と、owner確認・期限更新・dependency解消などの次手を示す。

この共通手順は特定runtimeのtool名に依存しない。runtimeは、ファイル読取、現在時刻取得、判定器実行の能力をadapterとして提供する。
