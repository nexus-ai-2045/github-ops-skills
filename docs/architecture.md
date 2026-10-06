# Architecture

`src/github_ops/`が結果契約、redaction、command実行、account overlay、identity、
preflightを提供します。`scripts/`は薄いCLI、`skills/`は移植したSSOT、
`adapters/`はread-only参照検証です。外部変更の判断はCLIの外側に残します。

`gitops.py`はGit内のdesired stateとGitHub APIで観測した現在値を比較します。
reconcileはread-onlyの観測とdrift分類までとし、self-healや設定変更は行いません。
drift解消は通常のGitHub書き込みとして、identity、権限、現在会話の承認を再検証します。
