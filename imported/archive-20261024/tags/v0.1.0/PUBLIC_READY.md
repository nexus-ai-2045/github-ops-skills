# Public Readiness

状態: **公開済み・lockdown 未完了**

visibility は 2026-08-23 に public になった。この文書は公開許可そのものではない。
ローカル検証、GitHub read-only 実測、Settings、人間目視を分けて記録する。

| 層 | 現在状態 | 根拠 |
|---|---|---|
| L1 静的契約 | READY | 2026-08-23、`05d7762` の Core Suite CI success |
| L2 ローカル実行 | READY | Codex/Claude/Grok adapter と unit tests |
| L3 GitHub read-only | 部分 | 2026-08-23、`gh repo view` で visibility=public、identity probe READY。secret scanning は disabled。権限照会はしていない |
| L4 private canary | 未実施 | mutation canary は人間承認が必要。ruleset / PVR は別の Settings 承認 |

人間確認の対象: README、LICENSE、SECURITY.md、CONTRIBUTING.md、PREFLIGHT.md、
secret scan、personal path scan、commit history、送信 file。

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
