# 人間レビュー判断材料

対象 PR: この branch の GitHub PR（hardening + composition gate）  
対象 repo: `nexus-ai-2045/github-ops-skills`（**private 維持**）  
レビュー目的: merge してよいか / 何をまだ止めるか

## 採用した方針

| 項目 | 判断 |
|---|---|
| フル orchestrator | **不採用** |
| 既存 skill/repo 接続 | **採用**（operating-card） |
| 薄い write preflight | **採用**（location + dirty + identity） |
| L4 mutation canary | **保留** |
| public / visibility 変更 | **しない** |
| runtime skill 一括同期 | **しない**（drift 検知のみ） |
| worktree 削除の自動化 | **しない**（sibling に委譲） |

## 変更の中身（レビュー観点）

1. **バグ修正**: legacy import の symlink 拒否  
2. **既存吸収**: PR review-thread audit  
3. **skill 更新**: github-cli-ops-guard / public-repo-readiness  
4. **契約**: public-repo-readiness manifest / Grok adapter / skill drift  
5. **接続**: `docs/operating-card.md` + `scripts/preflight_write_gate.py`

## 検証証拠（再実行可能なもの）

| 項目 | 期待 |
|---|---|
| `python -m pytest -q` | 全 pass |
| adapters codex/claude/grok | READY / skill_count=8 |
| `scripts/gh_identity_probe.py --repo . --json` | READY |
| `scripts/run_read_only_e2e.py --json`（overlay 付き） | READY private/ADMIN |
| `scripts/preflight_write_gate.py --repo . --json` | location+identity 結果 |
| personal path / token scan | 0 件 |

## 明示ストップライン（自動でやらない）

- merge（人間 yes が必要）
- L4 private canary execute
- visibility public
- GitHub Settings 変更
- worktree/branch 削除
- runtime home への skill 上書き配布

## 人間が決めること（チェックリスト）

- [ ] この private Core Suite 方針（ガードレール中心）でよいか  
- [ ] operating-card の接続順を運用標準にしてよいか  
- [ ] dirty scope を fail-closed にする挙動でよいか（`--allow-dirty` / `--approved-path` 例外）  
- [ ] PR を merge するか  
- [ ] L4 canary は引き続き保留か  
- [ ] runtime 同期は別 PR にするか  

## 推奨（レビューア向け）

1. **merge 可**にするなら: L1–L3 と preflight の証拠が揃っていることだけ確認  
2. **merge 後すぐやらない**: public 化、Settings 一括、runtime 強制同期  
3. **次の別作業**: agent 起動テンプレに operating-card を1行参照させる  

## リスク

| リスク | 深刻度 | 緩和 |
|---|---|---|
| dirty fail-closed が日常で煩い | 中 | approved-path / allow-dirty を意図明示時だけ |
| worktree lifecycle と二重管理に見える | 低 | この repo は削除せず compose 参照のみ |
| runtime skill と SSOT 差分が残る | 中 | skill_drift_check で可視化、同期は別判断 |
