# Public Readiness

状態: **公開済み・lockdown 一部完了**

この文書は公開許可そのものではない。visibility の live 実測と、残っている Settings を分けて記録する。

2026-08-26 の `gh repo edit --visibility public` 後、未ログイン HTTP は 200、org public 一覧に載る。
GitHub Release `v0.1.0`（tag `3a6688c`）も公開面から見える。

| 層 | 現在状態 | 根拠 |
|---|---|---|
| L1 静的契約 | READY | 2026-08-23、`05d7762` の Core Suite CI success。公開 HEAD は `3a6688c` |
| L2 ローカル実行 | READY | Codex/Claude/Grok adapter と unit tests（2026-08-26、293 passed） |
| L3 GitHub read-only | READY | 2026-08-26、`visibility=public`、未ログイン 200、identity probe READY。secret scanning enabled、push protection enabled、PVR enabled |
| L4 private canary | 未実施 | mutation canary は別承認。ruleset は未設定（ADR-0002） |

## 公開面に出ている残リスク

- 現行 tree の identity scan は READY。履歴 commit `10941368c49e` / `5b9472760b08` に個人絶対パス候補が残る（現行ファイルでは placeholder に置換済み）。history rewrite はしていない。
- required status checks / ruleset は未設定。
- dependabot security updates は disabled。

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
