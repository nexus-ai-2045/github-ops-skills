# Public Readiness

状態: **公開済み・lockdown 一部完了**

2026-10-18: 中身だけで作り直した。秘密情報の検査・送信時の遮断・非公開の脆弱性報告・統合後の枝の自動削除は、作成時に有効にした（実測）。以下の旧い表の実行番号と `commit` の番号は、保管庫の履歴を指す。

この文書は公開許可そのものではない。visibility の live 実測と、残っている Settings を分けて記録する。

2026-08-26 の `gh repo edit --visibility public` 後、未ログイン HTTP は 200、org public 一覧に載る。
GitHub Release `v0.1.0`（tag `3a6688c`）に続き、`v0.1.1` は公開後の README 可視化と live 記録を含む patch です。

| 層 | 現在状態 | 根拠 |
|---|---|---|
| L1 静的契約 | READY | 2026-08-28、main `6a10def` の Core Suite CI success（run `33215149396`）。jobs: Python tests / 静的契約とadapter検証。同 push の ai-ratchet-gate success（run `33215149344`） |
| L2 ローカル実行 | READY | 2026-08-28、Codex/Claude/Grok adapter READY（skill_count=8）と `python -m pytest -q`（312 passed） |
| L3 GitHub read-only | READY | visibility: 2026-08-28 未ログイン HTTP 200、`scripts/check_visibility_claim.py` READY。現行 tree の `scripts/public_identity_guard.py` READY。secret scanning enabled、push protection enabled、PVR enabled（2026-08-26 記録）。`scripts/run_read_only_e2e.py --json` の live E2E は 2026-08-29（JST）に人間アカウント overlay で再実測し **READY**（`live_read_only_verified`、active login `nexus-ai-2045`） |
| L4 private canary | 未実施 | mutation canary は別承認。committed `docs/evidence/private-canary-review.json`（recorded_at 2026-07-28）は request.visibility PRIVATE、gate.status BLOCKED、gate.code `canary_confirmation_missing`、executed false。2026-08-29 の live packet（未 commit）は現行 visibility が PUBLIC のため BLOCKED。ruleset は未設定（ADR-0002） |

## 公開面に出ている残リスク

- 2026-10-18 に、このリポジトリを中身だけで作り直した。旧リポジトリは非公開の保管庫 `github-ops-skills-archive` に移した。旧い履歴・`PR` の参照・コメントにあった個人のパス・個人名義は、この公開リポジトリには無い。
- required status checks / ruleset は未設定。
- 依存の脆弱性の自動更新（`dependabot security updates`）は有効（2026-10-18 実測）。
- 未ログイン HTTP の 404 は既存 oracle（`public-repo-readiness`）どおり PRIVATE 観測として扱う。誤った URL の 404 との区別は人間材料。
- L4 private canary は未実施。committed packet は `canary_confirmation_missing` で BLOCKED（executed false）。2026-08-29 live packet（未 commit）は現行 PUBLIC のため BLOCKED。mutation canary は実行していない。

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
