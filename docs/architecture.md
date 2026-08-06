# Architecture

`src/github_ops/`が結果契約、redaction、command実行、account overlay、identity、
preflight、review-thread audit、skill drift比較を提供します。`scripts/`は薄いCLI、
`skills/`は移植したSSOT、`adapters/`はCodex / Claude / Grok のread-only参照検証です。
外部変更の判断はCLIの外側に残します。

## 再利用方針

- 新規 GitHub gate を作る前に、この repository の `scripts/` と既存 workspace helper を探す。
- PR review 吸収は `github_ops.review_threads` / `scripts/github_pr_review_thread_audit.py` を使う。
- runtime 配布は `nexus-ai-skills` 側の distribute 系へ任せ、ここは Core Suite 契約と検証に閉じる。
