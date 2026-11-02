---
name: github-cli-ops-guard
description: GitHub CLI (`gh`) のactive account drift、remote owner不一致、repo解決失敗、credential username差分、Git author差分、PR review未吸収と fail-closed resolve をGitHub write前後に検査する共有向け運用ゲート。Use before or after `gh` / GitHub operations such as `git push`, `gh pr create`, `gh pr edit`, PR review absorption, `gh pr merge`, review thread resolve, branch cleanup, release/tag work, GitHub issue/discussion writes, or when errors mention wrong account, active account, repo not found, GraphQL repository resolution, unresolved review threads, `gh auth switch`, `gh auth status`, `GITHUB_TOKEN`, credential username, owner mismatch, or Japanese requests such as "gh名義", "GitHub名義", "repo解決失敗", "マージ前確認", "PR前ゲート", "review吸収", "運用保証", "共有前提".
---

# GitHub CLI Ops Guard

## Purpose

Use this skill to keep `gh` operations account-safe and auditable across private, shared, and multi-account workspaces.

The core failure this skill prevents is: Git remote/credential points to one owner, but `gh` active account has drifted to another account, so repo reads/writes fail or target the wrong identity.

## FDE Packet

Before a GitHub write, reduce the situation to this packet:

```text
entry: GitHub CLI operation
operation: push | pr_create | pr_edit | pr_merge | release | issue | discussion | visibility | read_only
repo: owner/name or local checkout
expected_owner:
expected_login:
active_gh_login:
remote_owner:
credential_username:
git_author:
publication_boundary: private | public | unknown
approval: current_turn_yes | missing | not_required_read_only
done_when: preflight ok + operation result verified + closeout clean
```

If `operation` mutates GitHub state, apply the publication/human-review gate first. Repository visibility changes always require repo-specific approval.

## Required Workflow

1. Identify the target repo from the local checkout or explicit `--repo owner/name`.
2. Run the bundled read-only probe (prefer this repository's script when operating from github-ops-skills):

```powershell
python scripts/gh_identity_probe.py --repo <repo-root> --json
# or skill-local copy:
python skills/github-cli-ops-guard/scripts/gh_identity_probe.py --repo <repo-root> --expected-owner <owner> --expected-login <login> --json
```

   このprobeはfetch URLだけでなく、`git remote get-url --all --push origin`で実効push URLを1件取得し、credential埋め込み・GitHub scheme不正・fetch先とのrepository不一致を検査する。push URLを確定できない場合は`error`として停止する。

3. If the repo has a stronger local preflight, run it too. Prefer repo-local or shared scripts over ad hoc parsing.
4. Treat `status=error` / `BLOCKED` / `UNKNOWN` as a hard stop for GitHub writes. Do not push, create/edit PRs, merge, tag, release, or change settings.
5. If the only problem is active-account drift and the expected account is already authenticated, run the exact switch command shown by the probe, then rerun the probe:

```powershell
gh auth switch --hostname github.com --user <expected_login>
```

6. After any GitHub write, verify the result with a read command and rerun the identity check if additional GitHub writes remain.

## PR review 吸収ゲート

PR review を吸収してから merge する時は、GitHub GraphQL `reviewThreads.isResolved` を解決状態の正本にします。comment 本文や commit の更新だけで「解決済み」と推定しません。

この Core Suite では、既存の read-only helper を吸収した次の script を使います。

```powershell
python scripts/github_pr_review_thread_audit.py --repo owner/name --pr N --json
# or skill-local copy:
python skills/github-cli-ops-guard/scripts/github_pr_review_thread_audit.py --repo owner/name --pr N --json
```

- exit `0` / `decision=pass`: 未解決 thread なし、pagination 完了。
- exit `1` / `decision=warn`: 未解決 current/outdated thread あり、または pagination 未完了。吸収と resolve 後に再実行する。
- exit `1` / `decision=error`: GitHub API error または応答が壊れている。状態を推定せず停止する。

`gh pr merge` は identity probe と review-thread audit が通るまで実行しない。merge 自体は現在会話の明示承認が必要で、本 skill は merge を自動実行しない。

GitHub Settings の `Require conversation resolution` と required checks は local command や repository file だけでは保証できない。Settings 権限を持つ人間または管理 API の確認がない限り、`not_enabled_or_unverified` として扱う。

## PR review thread resolve（既存 audit 判定のみ）

Review / comment thread を閉じる前に、既存の read-only audit 判定を使う。comment 本文や commit 更新だけで「修正済み」と推定して resolve しない。

```powershell
python scripts/github_pr_review_thread_audit.py --repo owner/name --pr N --json
python scripts/github_pr_review_thread_resolve.py --repo owner/name --pr N --json
```

- 既存判定が `error` / pagination 未完了 / 未解決 thread あり → resolve しない。未解決は materials として残す。
- `--apply` は既存判定がすでに `isResolved` と判定した thread の確認だけ（未解決の強制 close はしない）。確認は audit snapshot の read-only 判定であり、`resolveReviewThread` mutation は発行しない。
- `--apply` には既存 write 契約どおり `--confirm` と IdentityProbe 入力（`--repo-root` / `--expected-owner` / `--expected-login`）が必要。`GH_HOST` は github.com に固定する。
- raw `resolveReviewThread` や本文推定での close は使わない。

## Stop Lines

Stop and explain in human language when any of these are true:

- `remote_owner` differs from `expected_owner`.
- `gh_active_login` differs from `expected_login` when a login is specified.
- HTTPS credential usernameはidentity証拠として扱わない。`x-access-token`を含め、APIが返すloginで検証する。
- `gh repo view owner/name` cannot resolve a repo that Git remote says should exist.
- `GITHUB_TOKEN` or `GH_TOKEN` is present and its identity has not been confirmed.
- Repo visibility is public or unknown and the user did not explicitly approve that target and operation.
- The target operation is `gh pr merge`, `commands:register`, release/tag, visibility, hook/settings/auth, or credential mutation without current-turn approval.
- `github_pr_review_thread_audit.py` returns non-pass for a merge candidate.
- The working tree is dirty and the intended GitHub write does not explicitly include or exclude that dirty scope.
- `github_pr_review_thread_resolve.py` returns `hold` / `error` (unresolved or unjudgeable threads remain as materials).

## Recovery Pattern

Use proportional recovery, not broad reset:

| Symptom | Cause to check | Recovery |
| --- | --- | --- |
| `GraphQL: Could not resolve to a Repository` | active `gh` account cannot see target repo | `gh auth status --hostname github.com`, switch to expected account, rerun probe |
| push works but `gh pr view` fails | Git credential and `gh` active account differ | align `gh auth switch`, then verify repo view |
| `gh` is correct but `git clone` or push asks for another account | credential helperまたはtoken identityが異なる | token/API loginを検証し、repo-localな認証設定だけを修正して再実行 |
| `gh auth switch` succeeds but repo still fails | token scope/session may be stale | run `gh auth status`, consider `gh auth refresh` only after approval if scopes change |
| wrong owner in remote | checkout is not the intended repo | stop; do not switch accounts to fit the wrong remote |
| multiple possible expected owners | target is ambiguous | ask one short question before write |
| review threads remain unresolved | merge candidate still has open discussion | absorb findings, resolve threads, rerun audit |

## Closeout

A GitHub operation is not closed until all relevant checks are true:

- target repo and operation were named
- `scripts/gh_identity_probe.py` or equivalent preflight passed
- write command succeeded, if a write was approved
- result was verified by read-only command (`gh pr view`, `gh pr checks`, `git rev-parse`, `gh release view`, etc.)
- open PR / branch / dirty worktree state is explained
- public/external boundary is stated
- any account drift and recovery command are reported plainly

## References

Read `skills/github-cli-ops-guard/references/official-gh-auth.md` when diagnosing `gh auth status`, `gh auth switch`, token precedence, or multi-account behavior.
