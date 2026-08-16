# アーキテクチャ

`src/github_ops/`が結果契約、出力秘匿、コマンド実行、account overlay、identity、
preflightを提供します。`scripts/`は薄いCLI、`skills/`は移植したSSOT、
`adapters/`は読み取り専用の参照検証です。外部変更の判断はCLIの外側に残します。

PR作成は`pr_language`で表示面を事前検査し、`pr_create`が明示承認、
`gh pr create --body-file`、作成後の再取得確認を順番に固定します。メタデータ限定workflowは
checkout、secret、write権限を使わず、別経路から作られたPRの言語差分を検出します。
