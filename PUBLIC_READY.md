# Public Readiness

状態: **公開未承認**

この文書は公開許可ではありません。ローカル検証、GitHub read-only実測、private
canary、公開判断を別々に記録します。

| 層 | 現在状態 | 根拠 |
|---|---|---|
| L1 静的契約 | READY | 2026-08-24、commit `17ef9aa` / tree `ed7dd7d` で287 tests成功 |
| L2 ローカル実行 | READY | Codex/Claude/Grok adapter一致、identity probe READY |
| L3 GitHub read-only | READY | 2026-08-06、private repo・ADMIN権限・main・account不変をread-only実測 |
| L4 private canary | 未実施 | 人間承認が必要 |

公開前にREADME、LICENSE、SECURITY.md、secret scan、personal path scan、
commit history、送信file、`PUBLIC_READY.md`を人間が確認します。

## 必須契約（公開判断前）

公開判断の前に、READMEの「必須契約」が揃っていることを人間が確認します。

- `repo-preflight` / `public-repo-readiness`
- 本repoの GitHub ops suite（この Core Suite）
- 必要時の `engineering-brain`
- FDE（`fractal-decision-ecosystem` / skill内 FDE Packet）
- `ai-ratchet-gate`
- `nexus-management-os`
- `nexus_ai` を mainline／最新参照として扱う（第二複製にしない）

この節は契約名の明示だけです。新規scriptや新規protocolは定義しません。
