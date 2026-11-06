<!-- repo-preflight:review-record -->

# 公開準備状況

## 2026-11-06 共通ゲートのbase-guard呼出しを廃止

- 共通 `preflight-gate` の固定参照を `fe2e90f91615a5e5ed3f9b2b497c99f5786e5847` へ更新する。独立ワークフローに加え、共通ゲート内のbase-guard呼出しも廃止した統合版を採用する。
- 通常のpreflight・名義・秘密情報・ラチェット検査を維持する。以下の導入記録は当時の履歴として保持する。

## 2026-11-03 `base-guard` を外す

- 対象: `base-guard` は検査定義（`.github/workflows/`）を変える `PR` を必ず赤にする。必須チェックにも `ruleset` にも入っておらず、止めるのはマージの入口だけで、毎回人の手作業を要していた。所有者の判断で外す。
- 残る検査: `preflight`・`ai-ratchet-gate`・`Core Suite CI`・`repository-guarantees`・`PR日本語gate`・`PRセルフレビュー（base監査 advisory）` はそのまま。
- 判定: 検査定義の変更は、これまでどおり `PR` の差分とレビューで見る。

## 2026-10-26 main の赤を解く（検査の固定先の更新）

- 対象: `main` の CI が赤のまま。原因は3つで、既存の `PR` #6（wheel）・#2（preflight の固定先）・#1（初回 push の比較元）はそれぞれ1つしか直さないため、互いの赤が残っていた。1本にまとめて直す。
- `ai-ratchet-gate`: Release wheel を `v0.2.0`（SHA-256 `95ebac0a…a0d4a8`）に固定する。`v0.1.1` の配布物は作り直しで消え、取得が 404 になっていた。
- `repo-preflight`: `preflight.yml`・`base-guard.yml`・`repository-guarantees.yml` の固定先を `v0.10.0`（`5b7c774deb8e`）にそろえる。仮の SHA（`PIN_TBD`）をやめる。
- Core Suite: 初回 push で比較元（before）が全0・空・存在しないときは、空ツリーと比べて全ファイルの差分形式を見る。PR の比較元が壊れているときは今までどおり失敗させる。
- 検査は弱めていない。`base-guard` は検査定義の変更を `main` 側の定義で見るため、この `PR` では赤になり得る。必須チェックの一時解除は人が判断する。

## 2026-10-18 中身だけで作り直し

- 対象: 旧リポジトリの履歴・`PR` の参照・コメントに個人情報が残ったため、同じ名前で中身だけのリポジトリを作り直した。旧リポジトリは非公開の保管庫 `github-ops-skills-archive`。
- 中身: 保管庫の `main`（`18dfbf85022b`）に、作成用の道具の修正2件を足した版。取り込み `PR` #1 で、木の番号の一致を照合した。
- 判定: 作り直し後の公開前検査で、秘密情報・個人のパス・名義の照合・`commit` の名義は合格。下の旧い記録にある「履歴の個人パス候補」は、この公開リポジトリには無い。
- 作成時に有効にした設定: 秘密情報の検査（`secret scanning`）、送信時の遮断（`push protection`）、非公開の脆弱性報告（`private vulnerability reporting`）、統合後の枝の自動削除。
- 残り: 必須の検査（`required status checks`）と `ruleset` は未設定（`ADR-0002` の別承認）。

## 2026-08-27 `v0.1.1`

- 対象: public 化後の README 可視化（#13）と PUBLIC_READY live 記録（#12）を含む patch
- pyproject version: `0.1.1`
- 判定: 機械検査は pass。履歴の個人パス候補 2 blob と ruleset 未設定は残リスク
- この記録の操作: version bump の PR。tag `v0.1.1` は merge 後。告知は含まない

---

# 2026-08-24 記録（PR #11）

- 検査対象 parent HEAD: `05d7762c32c2ee3975d6fb2f4b6e2e2a4827f210`
- 文書差分: PR #11（README / SECURITY / CONTRIBUTING / PREFLIGHT / PUBLIC_READY）
- 確認日時: 2026-08-24
- 判定: `blocked`

parent の CI と、この PR の文書差分は別記録です。文書側は Codex review 吸収後の tip で再確認します。

## 確認済み

- [ ] README / LICENSE / SECURITY.md / CONTRIBUTING.md / PREFLIGHT.md（PR #11 の文書差分。parent scan だけでは未カバー）
- [x] test: parent `05d7762` の Core Suite CI success（run 32658364419）。PR #11 の Python tests も pass
- [x] ratchet: parent と同 PR で ai-ratchet-gate success
- [x] secret pattern の working tree 検査（repo-preflight `secret_scan` pass、finding_count 0）
- [ ] secret scanning / push protection（GitHub Settings。未設定）
- [ ] private vulnerability reporting（`enabled: false`）
- [ ] required status checks / ruleset（rulesets 空。ADR-0002 の別承認）
- [ ] history の個人パス候補 2 commit（`10941368c49e`、`5b9472760b08`）。公開履歴の rewrite は未実施
- [ ] dependency 脆弱性監査（CLI 範囲外。未実施）

## 人間目視

- reviewer:
- reviewed_at:
- exact HEAD / PR diff:
- reviewed content: README 情報設計、CONTRIBUTING、PREFLIGHT、SECURITY の public 報告経路
- decision: `changes_requested`
- 外から見える files と commit history: public repository `nexus-ai-2045/github-ops-skills`
- review済み: ローカル pytest、remote CI success、repo-preflight release scan
- 未review: README の人間目視、history 2 commit、Settings
- 残余リスク: history に個人パス候補が残る。ruleset 未設定のため ratchet は merge を機械強制しない
- 次に承認する正確な操作: この branch の PR 作成。tag / 告知 / Settings 変更は含まない

## repository-guarantees（repo-preflight 整合性ゲート）

- `.repo-preflight-consistency.json`（shadow）を置く。専用 workflow（旧 `.github/workflows/repository-guarantees.yml`、workflow_dispatch のみ）は実行 0 回で、必須チェック `all-green`（`preflight.yml` → preflight-gate）と `ai-ratchet-gate.yml` に検査が重なるため 2026-10-25 に外した。検査ロジックは上流 repo-preflight を SHA 固定で取得し、コピーしない。
- 手元同等の確認は `python <repo-preflight>/scripts/consistency_gate.py --repo . --base-ref origin/main --require-config --require-mode shadow --json` と `python -m ai_ratchet_gate --repo .`。
