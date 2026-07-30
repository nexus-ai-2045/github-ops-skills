---
name: pr-status
description: 現在のブランチに関連する PR の状況 (CI / レビューコメント / マージ可否) を確認して報告する。「PR の状況」「PR どうなってる」「CI 通ってる？」「マージできる？」と言われたら使用する。Do NOT use for: PR 作成 (commit-push-pr)、レビュー実施 (review-pr)。
---

# /pr-status

現在のブランチに関連するPRの状況を確認する。

## 手順
1. 現在のブランチ名を取得
2. `gh pr view` でPR詳細を表示（なければ「PRなし」と報告）
3. CIチェック状況を確認
4. レビューコメントがあれば要約
5. マージ可能か判定して報告

## 注意
- マージ可否の報告まで。マージ実行は CEO/メンテナ責務 (no-merge-without-ask)
