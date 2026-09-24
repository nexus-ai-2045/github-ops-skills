---
name: pr-status
description: 現在のブランチに関連する PR の状況 (CI / レビューコメント / マージ可否) を確認して報告する。「PR の状況」「PR どうなってる」「CI 通ってる？」「マージできる？」と言われたら使用する。Do NOT use for: PR 作成 (commit-push-pr)、レビュー実施 (review-pr)。
---

# /pr-status

ユーザーが owner/repo の `/pulls` または `/pull/N` URL を貼ったら、cwd が違ってもその repo/PR を見る。URL が無いときだけ現在ブランチの `gh pr view` を使う。

## 手順
1. 貼られた GitHub URL の形で対象を決める。無ければ現在のブランチ名を取得する
   - `.../owner/repo/pulls`（リスト）→ owner/repo を対象にする。特定 PR 番号はまだ無い
   - `.../owner/repo/pull/N`（個別）→ owner/repo と PR 番号 N を対象にする
2. URL 形に応じて読み取る（cwd が違っても `-R owner/repo` を付ける）
   - `/pulls` → `gh pr list -R owner/repo`（リスト。`gh pr view` は使わない）
   - `/pull/N` → `gh pr view N -R owner/repo`（個別詳細）
   - URL 無し → 現在ブランチで `gh pr view`（なければ「PRなし」と報告）
3. 個別 PR が特定できているときだけ CIチェック状況を確認する。`/pulls` リストのときは一覧を報告し、特定 PR の指定が無ければここで止めてよい
4. 個別 PR についてレビューコメントがあれば要約
5. 個別 PR についてマージ可能か判定して報告

## 注意
- マージ可否の報告まで。マージ実行は CEO/メンテナ責務 (no-merge-without-ask)
- 明示の「レビューしてマージ」は、レビュー実施を配布スキル `review-pr` へ回す。マージ実行自体は
  この skill でも `review-pr` でも行わず、人間の明示承認があるまで止める (no-merge-without-ask)
