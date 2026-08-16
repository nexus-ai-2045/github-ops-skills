# Architecture

`src/github_ops/`が結果契約、redaction、command実行、account overlay、identity、
preflightを提供します。`scripts/`は薄いCLI、`skills/`は移植したSSOT、
`adapters/`はread-only参照検証です。外部変更の判断はCLIの外側に残します。

PR作成は`pr_language`で表示面を事前検査し、`pr_create`が明示承認、
`gh pr create --body-file`、作成後read-backを順番に固定します。metadata-only workflowは
checkout、secret、write権限を使わず、別経路から作られたPRの言語driftを検出します。
