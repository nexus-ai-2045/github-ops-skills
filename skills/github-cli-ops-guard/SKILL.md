---
name: github-cli-ops-guard
description: GitHub CLI (`gh`) のactive account drift、remote owner不一致、repo解決失敗、credential username差分、Git author差分をGitHub write前後に検査する共有向け運用ゲート。Use before or after `gh` / GitHub operations such as `git push`, `gh pr create`, `gh pr edit`, `gh pr merge`, branch cleanup, release/tag work, GitHub issue/discussion writes, or when errors mention wrong account, active account, repo not found, GraphQL repository resolution, `gh auth switch`, `gh auth status`, `GITHUB_TOKEN`, credential username, owner mismatch, or Japanese requests such as "gh名義", "GitHub名義", "repo解決失敗", "マージ前確認", "PR前ゲート", "運用保証", "共有前提".
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
2. Run the bundled read-only probe:

```powershell
python shared/skills/github-cli-ops-guard/scripts/gh_identity_probe.py --repo <repo-root> --json
```

3. If the repo has a stronger local preflight, run it too. Prefer repo-local or shared scripts over ad hoc parsing.
4. Treat `status=error` as a hard stop for GitHub writes. Do not push, create/edit PRs, merge, tag, release, or change settings.
5. If the only problem is active-account drift and the expected account is already authenticated, run the exact switch command shown by the probe, then rerun the probe:

```powershell
gh auth switch --hostname github.com --user <expected_owner>
```

6. After any GitHub write, verify the result with a read command and rerun the identity check if additional GitHub writes remain.

## Stop Lines

Stop and explain in human language when any of these are true:

- `gh_active_login` differs from the remote owner or expected owner.
- `credential_username` differs from the remote owner or expected owner before a GitHub write.
- `gh repo view owner/name` cannot resolve a repo that Git remote says should exist.
- `GITHUB_TOKEN` or `GH_TOKEN` is present and its identity has not been confirmed.
- Repo visibility is public or unknown and the user did not explicitly approve that target and operation.
- The target operation is `gh pr merge`, `commands:register`, release/tag, visibility, hook/settings/auth, or credential mutation without current-turn approval.
- The working tree is dirty and the intended GitHub write does not explicitly include or exclude that dirty scope.

## Recovery Pattern

Use proportional recovery, not broad reset:

| Symptom | Cause to check | Recovery |
| --- | --- | --- |
| `GraphQL: Could not resolve to a Repository` | active `gh` account cannot see target repo | `gh auth status --hostname github.com`, switch to expected account, rerun probe |
| push works but `gh pr view` fails | Git credential and `gh` active account differ | align `gh auth switch`, then verify repo view |
| `gh` is correct but `git clone` or push asks for another account | `credential.https://github.com.username` is fixed globally or locally | prefer repo-local correction: `git config --local credential.https://github.com.username <expected_owner>`, then rerun probe |
| `gh auth switch` succeeds but repo still fails | token scope/session may be stale | run `gh auth status`, consider `gh auth refresh` only after approval if scopes change |
| wrong owner in remote | checkout is not the intended repo | stop; do not switch accounts to fit the wrong remote |
| multiple possible expected owners | target is ambiguous | ask one short question before write |

## Closeout

A GitHub operation is not closed until all relevant checks are true:

- target repo and operation were named
- `shared/skills/github-cli-ops-guard/scripts/gh_identity_probe.py` or equivalent preflight passed
- write command succeeded, if a write was approved
- result was verified by read-only command (`gh pr view`, `gh pr checks`, `git rev-parse`, `gh release view`, etc.)
- open PR / branch / dirty worktree state is explained
- public/external boundary is stated
- any account drift and recovery command are reported plainly

## References

Read `shared/skills/github-cli-ops-guard/references/official-gh-auth.md` when diagnosing `gh auth status`, `gh auth switch`, token precedence, or multi-account behavior.
