# Public Readiness

状態: **公開済み・lockdown 一部完了**

この文書は公開許可そのものではない。visibility の live 実測と、残っている Settings を分けて記録する。

2026-08-26 の `gh repo edit --visibility public` 後、未ログイン HTTP は 200、org public 一覧に載る。
GitHub Release `v0.1.0`（tag `3a6688c`）に続き、`v0.1.1` は公開後の README 可視化と live 記録を含む patch です。

| 層 | 現在状態 | 根拠 |
|---|---|---|
| L1 静的契約 | READY | 2026-08-28、main `6a10def` の Core Suite CI success（run `33215149396`）。jobs: Python tests / 静的契約とadapter検証。同 push の ai-ratchet-gate success（run `33215149344`） |
| L2 ローカル実行 | READY | 2026-08-28、Codex/Claude/Grok adapter READY（skill_count=8）と `python -m pytest -q`（312 passed） |
| L3 GitHub read-only | 一部 READY | visibility: 2026-08-28 未ログイン HTTP 200、`scripts/check_visibility_claim.py` READY。現行 tree の `scripts/public_identity_guard.py` READY。secret scanning enabled、push protection enabled、PVR enabled（2026-08-26 記録）。`scripts/run_read_only_e2e.py --json` の public 再実測は 2026-08-28 に実行し **UNKNOWN**（`live_read_failed`）。`gh repo view` / `gh pr list` は returncode 0 だが、既存 script が要する `gh api user`（active login）が integration token で 403 のため login 不変を確認できない。L3 全体を READY にしない |
| L4 private canary | 未実施 | mutation canary は別承認。ruleset は未設定（ADR-0002） |

## 公開面に出ている残リスク

- 現行 tree の identity scan は READY。履歴 blob `10941368c49e` / `5b9472760b08` に個人絶対パス候補が残る（含む commit は `340dad9`/`578a3d3` と `4867513`/`578a3d3`。現行ファイルでは placeholder に置換済み）。history rewrite はしていない。
- required status checks / ruleset は未設定。
- dependabot security updates は disabled。
- 未ログイン HTTP の 404 は既存 oracle（`public-repo-readiness`）どおり PRIVATE 観測として扱う。誤った URL の 404 との区別は人間材料。
- L3 `run_read_only_e2e.py` は UNKNOWN のまま。人間アカウントの overlay（repository 外）と `gh api user` 可能な認証で再実測するまで、権限・default-branch・PR読取の L3 実行保証は未完了。

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
