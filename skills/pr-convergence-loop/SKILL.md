---
name: pr-convergence-loop
description: "Use when the user asks to keep going until the goal, open PR zero, residual zero, PR収束, merge remaining PRs, feedback loop, smoke/preflight/E2E/TDD/implementation/test/operation guarantee/PR/cleanup, or Japanese requests such as ゴールまで止まらないで, 残務ゼロまで, 収束して, フィードバックループ回して."
---

# PR Convergence Loop

## Purpose

Open PR を「見たつもり」「直したつもり」「終わったつもり」で止めず、実測とフィードバックループで収束させる。

この skill は GitHub PR の運用接着層であり、既存 skill を置き換えない。

## Use With

- `github-cli-ops-guard`: GitHub write 前後の identity / repo / approval gate
- `done-verification-closeout`: 完了宣言前の証跡確認
- `status-sweep`: 現在地を stale todo ではなく実測で確認
- `git-sync-worktree-gate`: dirty / divergence / worktree 境界確認
- `mechanical-review-pdca`: 小さな修正と検証の PDCA

Source pointers:

- `shared/skills/github-cli-ops-guard/SKILL.md`
- `shared/skills/done-verification-closeout/SKILL.md`
- `shared/skills/status-sweep/SKILL.md`

## FDE Packet

```text
goal: open PR / visible residual を収束し、残れば owner・理由・次の1手を出す
scope: current repo + current chat visible PRs
stoplines: main direct push / hook / settings / auth / secrets / production / external send / branch delete
merge_permission: current-turn explicit approval required
approval_binding: approved PR numbers + head SHA values fixed before merge
loop_unit: one PR at a time
done_when: open PR zero OR all remaining PRs have owner + blocker + next check
```

## Procedure

1. **Goal and Boundary**
   - 1文で current goal を置く。
   - in scope / out of scope / Type1 stopline を分ける。
   - `obsidian_check` / `scope_route` / `pdca` を最終報告に残す。

2. **Measure**
   - `gh pr list --repo <owner/name> --state open --json number,title,url,mergeStateStatus,isDraft,statusCheckRollup`
   - For merge approval, snapshot each approved PR as `number + headRefName + head SHA`.
   - Treat any new PR, changed head SHA, or changed target list as outside the prior approval; stop and request renewed approval.
   - `gh auth status --hostname github.com`
   - local worktree は dirty なら触らず、必要な実装は isolated worktree で行う。

3. **Prioritize**
   - Bugfix / failing CI / blocker 修正を先に扱う。
   - Design/doc PR は、実装修正PRに依存する場合は後に回す。
   - Roadmap/ADR/closeout PR は最後に整合確認する。

4. **Review**
   - PRごとに changed files / tests / CI / mergeState を見る。
   - 必要なら `code-reviewer` / `security-reviewer` / `planner` などの sidecar に read-only でリスク抽出を任せる。
   - main agent は採否・merge判断・Type1境界を保持する。

5. **Repair**
   - blocker があれば該当 PR branch / isolated worktree で最小修正する。
   - TDD が必要なら failing test を先に置く。
   - 検証は対象 test / smoke / diff check から始め、必要以上に広げない。

6. **Publish**
   - commit / push 前に GitHub identity と repo を確認する。
   - PR更新後、CI / statusCheckRollup を再確認する。

7. **Merge**
   - merge は Type1。current-turn explicit approval がない場合は停止する。
   - Merge only the approved PR number at the approved head SHA. If the PR was updated after approval, stop before merge.
   - Do not include newly observed PRs in the same approval, even when the user said "open PR zero".
   - 1本mergeしたら、次PRへ進む前に open PR list を再測定する。

8. **Closeout**
   - mergedAt / mergeCommit / open PR list / remote branch state を確認する。
   - branch delete や worktree delete は別 stopline。安全確認なしに実行しない。
   - 最終的に `open PR zero` か、残るPRごとの owner / blocker / next action を返す。

## Output Shape

```text
obsidian_check: done | na
scope_route: <repo / PR scope>
pdca: Plan / Do / Check / Act

ゴール:
- ...

実測:
- [事実: gh pr list] ...

処理:
- #123 ...

残務:
- zero
  or
- #124 owner=... blocker=... next=...
```

## Anti-patterns

- open PR が増えたのに古い「残務ゼロ」を維持する。
- PR merge 後に open PR list を再測定しない。
- script / skill の CLI 形を確認せず、存在しない subcommand を前提にする。
- branch / worktree cleanup を merge と同じ許可で実行する。
- repo全体 dirty を current chat residual と混ぜる。
