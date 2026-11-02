---
name: review-pr
description: PRのコードレビューを行う。「PRをレビューして」「プルリクを確認して」「差分を見て」と言われたら使用する。security-reviewはセキュリティ特化の静的監査、このスキルはPR全体の多角的コードレビュー。Do NOT use for: セキュリティ特化の静的監査（security-reviewを使う）、コード実装、バグ修正。
---

# review-pr

PR やブランチ差分を、品質・設計・実装観点でレビューする。

## When To Use

Use for:
- PR review
- branch diff review
- change-set review

Do not use it for security-only auditing.

## Flow

1. fetch PR metadata or local branch diff
2. identify changed files and related tests
3. review in severity order:
   - critical: bugs, data loss, security, merge blockers
   - warning: performance, design, test coverage, readability
   - suggestion: refactor or doc improvements
4. summarize with approve / request changes / comment posture

## Notes

- read the PR body to understand intent
- always inspect test changes too
- prioritize the most consequential files when the diff is large
