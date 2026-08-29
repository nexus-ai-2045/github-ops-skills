# アーキテクチャ

設計判断は次の ADR に記録しています。番号は `docs/adr/` の全 file と一致します
（`scripts/verify_adr_numbering.py` が採番の一意性を CI で検査します）。

- [ADR-0001: PR日本語gateは限定的な構文契約とする](adr/0001-pr-japanese-gate-boundary.md)
- [ADR-0002: GitHub write・review・runtime検査は実効状態をfail-closedで確認する](adr/0002-github-write-review-runtime-fail-closed.md)
- [ADR-0003: PR収束は有界なコントローラで扱う](adr/0003-pr-convergence-bounded-controller.md)
- [ADR-0004: Review findingは不変条件へ昇格する](adr/0004-review-findings-to-invariants.md)
- [ADR-0005: skill manifestのssot_pointersはこのrepositoryに実在すること](adr/0005-skill-manifest-pointers-must-exist-in-this-repository.md)
- [ADR-0006: PRセルフレビューのbase監査とbootstrap境界](adr/0006-pr-self-review-advisory-bootstrap.md)
- [ADR-0007: ADRの採番は一意で機械検査に載せる](adr/0007-adr-numbers-must-be-unique.md)

`src/github_ops/`が結果契約、出力秘匿、コマンド実行、account overlay、identity、
preflight、review-thread audit、skill drift比較を提供します。`scripts/`は薄いCLI、
`skills/`は移植したSSOT、`adapters/`はCodex／Claude／Grokのread-only参照検証です。
外部変更の判断はCLIの外側に残します。

PR作成は`pr_language`で表示面を事前検査し、`pr_create`が明示承認、
`gh pr create --body-file`、作成後の再取得確認を順番に固定します。メタデータ限定workflowは
checkout、secret、write権限を使わず、別経路から作られたPRの言語差分を検出します。

## 再利用方針

- 新規GitHub gateを作る前に、このrepositoryの`scripts/`と既存workspace helperを探す。
- PR review吸収は`github_ops.review_threads`／`scripts/github_pr_review_thread_audit.py`を使う。
- runtime配布は`nexus-ai-skills`側のdistribute系へ任せ、ここはCore Suite契約と検証に閉じる。
- 検証済みreview findingは`policy/invariants.json`の安定IDと回帰testへ昇格し、
  `migration/source-manifest.json`のtarget hashをCIで再検証する。
- GitHub Settings、required checks、runtime配布は別の人間承認境界とする。
