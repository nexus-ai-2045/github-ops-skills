# Architecture

`src/github_ops/`が結果契約、redaction、command実行、account overlay、identity、
preflightを提供します。`scripts/`は薄いCLI、`skills/`は移植したSSOT、
`adapters/`はread-only参照検証です。外部変更の判断はCLIの外側に残します。
