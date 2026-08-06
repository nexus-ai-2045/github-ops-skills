# 運用カード — GitHub write 前の接続順

この repository は **フル orchestrator ではない**。  
既存 skill / sibling repo を **直列ゲート** でつなぐ。

## 接続図

```text
作業開始
  git-sync-worktree-gate      … stale local に載せない
  using-git-worktrees         … 必要なら隔離 worktree
  worktree-lifecycle-control  … scan/台帳（削除しない）

GitHub を触る直前（この repo）
  scripts/preflight_write_gate.py
    ├ location / dirty scope
    └ identity (gh_identity_probe 相当)
  READY だけ次へ

実行（外側・明示承認）
  commit / push / PR / merge

収束
  post-merge-closeout / pr-status
  worktree-lifecycle-control → cleanup_candidate
  repo-hygiene-cleanup（削除は承認付き）
```

## 1 コマンド（この Core Suite）

```powershell
python scripts/preflight_write_gate.py --repo . --json
# dirty を意図的に含む write なら:
python scripts/preflight_write_gate.py --repo . --approved-path path/a.py --json
# または明示:
python scripts/preflight_write_gate.py --repo . --allow-dirty --json
```

## 責務境界

| システム | やる | やらない |
|---|---|---|
| github-ops-skills | identity / dirty scope / review thread audit | Settings 変更、worktree 削除、自動 merge |
| worktree-lifecycle-control | worktree 台帳・disposition | GitHub Settings、account 切替 |
| repo-hygiene-cleanup | 掃除候補の安全整理 | 無承認 force 削除 |
| repo-preflight / public-repo-readiness | 公開前判断材料 | 自動 public 化 |

## 復旧の順番（account / credential / worktree）

1. **場所** … 意図した repo / branch / worktree か  
2. **identity** … `gh` login と remote owner  
3. **credential username** … repo-local 修正を優先（global 雑いじり禁止）  
4. **もう一度** `preflight_write_gate.py`
