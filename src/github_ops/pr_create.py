from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Protocol, Sequence

from .account_map import AccountMapError, load_account_map
from .command import CommandFailure, CommandResult, CommandRunner
from .identity import IdentityProbe
from .pr_language import check_pr_metadata
from .redaction import redact
from .result import Outcome, Status


class Runner(Protocol):
    def run(self, argv: Sequence[str], **kwargs: object) -> CommandResult: ...


def create_pr_with_japanese_gate(
    *,
    repo: str,
    base: str,
    head: str,
    title: str,
    body_file: Path,
    repo_root: Path,
    account_map_file: Path,
    expected_base_sha: str,
    expected_head_sha: str,
    confirmed: bool,
    expected_visibility: str = "PRIVATE",
    draft: bool = False,
    branch_purpose: str = "development",
    runner: Runner | None = None,
) -> Outcome:
    """日本語gate通過後にPRを作成し、表示面をread-back検証する。"""
    if branch_purpose not in {"development", "resident_adaptation"}:
        return _blocked(
            "branch_purpose_invalid",
            "枝の目的を判定できません",
            "development または resident_adaptation を明示してください",
            {"branch_purpose": branch_purpose},
        )
    if branch_purpose == "resident_adaptation":
        return _blocked(
            "resident_adaptation_not_publishable",
            "常駐への適応枝は開発PRの対象外です",
            "開発正本への固有変更を分離し、レビューしてください",
            {"branch_purpose": branch_purpose},
        )
    if expected_visibility not in {"PRIVATE", "PUBLIC", "INTERNAL"}:
        return _blocked(
            "expected_visibility_invalid",
            "期待visibilityが許可値ではありません",
            "PRIVATE、PUBLIC、INTERNALのいずれかを明示してください",
            {"expected_visibility": expected_visibility},
        )
    if not confirmed:
        return _blocked(
            "human_confirmation_required",
            "PR作成の人間承認がありません",
            "承認後に --confirm を指定してください",
            {"repository": repo, "base": base, "head": head},
        )
    if not body_file.is_file():
        return _blocked(
            "body_file_missing",
            "PR bodyファイルを読み込めません",
            "UTF-8のbodyファイルを用意してください",
            {"body_file": str(body_file)},
        )

    try:
        body = body_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return _blocked(
            "body_file_unreadable",
            "PR bodyファイルをUTF-8で読み込めません",
            "UTF-8のbodyファイルを用意してください",
            {"body_file": str(body_file), "error": redact(str(exc))},
        )
    language = check_pr_metadata(title, body)
    if language.status is not Status.READY:
        return language

    command_runner = runner or CommandRunner()
    repo_selector = f"github.com/{repo}"
    try:
        preflight = _verify_preflight(
            repo=repo,
            base=base,
            head=head,
            repo_root=repo_root,
            account_map_file=account_map_file,
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
            expected_visibility=expected_visibility,
            runner=command_runner,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _unknown(
            "pr_preflight_execution_failed",
            "PR作成前preflightを完了できません",
            "Git、GitHub認証、networkを確認してください",
            {"repository": repo, "error": redact(str(exc))},
        )
    if preflight.status is not Status.READY:
        return preflight
    content = _verify_content(repo_root=repo_root, base_sha=expected_base_sha,
                              head_sha=expected_head_sha, runner=command_runner)
    if content.status is not Status.READY:
        return content
    create_argv = [
        "gh",
        "pr",
        "create",
        "--repo",
        repo_selector,
        "--base",
        base,
        "--head",
        head,
        "--title",
        title,
        "--body-file",
        "-",
    ]
    if draft:
        create_argv.append("--draft")
    try:
        created = command_runner.run(
            create_argv,
            input_text=body,
            timeout=60,
            scoped_env={"GH_HOST": "github.com"},
        )
    except subprocess.TimeoutExpired:
        return _unknown(
            "pr_create_timeout",
            "gh pr createの完了状態を確認できません",
            "再作成せず、対象branchの既存PRをread-onlyで確認してください",
            {"repository": repo, "head": head},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # CommandRunner.run が握るので通常は到達しない。runner を差し替えた
        # 呼び出し元が生の例外を投げる場合の保険として残す。
        return _unknown(
            "pr_create_execution_failed",
            "gh pr createの完了状態を確認できません",
            "再作成せず、対象branchの既存PRをread-onlyで確認してください",
            {"repository": repo, "head": head, "error": redact(str(exc))},
        )
    if created.failure is CommandFailure.TIMED_OUT:
        return _unknown(
            "pr_create_timeout",
            "gh pr createの完了状態を確認できません",
            "再作成せず、対象branchの既存PRをread-onlyで確認してください",
            {"repository": repo, "head": head},
        )
    if created.failure is CommandFailure.EXECUTION_FAILED:
        return _unknown(
            "pr_create_execution_failed",
            "gh pr createの完了状態を確認できません",
            "再作成せず、対象branchの既存PRをread-onlyで確認してください",
            {"repository": repo, "head": head, "error": created.stderr},
        )
    if created.returncode != 0:
        return _unknown(
            "pr_create_indeterminate",
            "gh pr createの成否を確定できません",
            "再作成せず、対象branchの既存PRをread-onlyで確認してください",
            {"repository": repo, "head": head, "stderr": created.stderr},
        )

    url = created.stdout.strip().splitlines()[-1] if created.stdout.strip() else ""
    if not url.startswith("https://github.com/"):
        return _unknown(
            "pr_url_unavailable",
            "PR作成結果からURLを取得できません",
            "GitHub上のPRを確認し、重複作成せず手動でread-backしてください",
            {"repository": repo, "stdout": created.stdout},
        )

    try:
        read_back = command_runner.run(
            [
                "gh",
                "pr",
                "view",
                url,
                "--repo",
                repo_selector,
                "--json",
                "url,title,body,headRefName,baseRefName,headRefOid,baseRefOid,isDraft",
            ],
            redact_stdout=False,
            scoped_env={"GH_HOST": "github.com"},
        )
    except subprocess.TimeoutExpired:
        return _unknown(
            "pr_read_back_timeout",
            "作成後のPR表示面の再取得がtimeoutしました",
            "PRを編集・再作成せず、既存URLをread-onlyで確認してください",
            {"url": url},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _unknown(
            "pr_read_back_execution_failed",
            "作成後のPR表示面を再取得できません",
            "PRを編集・再作成せず、既存URLをread-onlyで確認してください",
            {"url": url, "error": redact(str(exc))},
        )
    if read_back.failure is CommandFailure.TIMED_OUT:
        return _unknown(
            "pr_read_back_timeout",
            "作成後のPR表示面の再取得がtimeoutしました",
            "PRを編集・再作成せず、既存URLをread-onlyで確認してください",
            {"url": url},
        )
    if read_back.failure is CommandFailure.EXECUTION_FAILED:
        return _unknown(
            "pr_read_back_execution_failed",
            "作成後のPR表示面を再取得できません",
            "PRを編集・再作成せず、既存URLをread-onlyで確認してください",
            {"url": url, "error": read_back.stderr},
        )
    if read_back.returncode != 0:
        return _unknown(
            "pr_read_back_failed",
            "作成後のPR表示面を再取得できません",
            "PRを編集せず、URLとGitHub認証を確認してください",
            {"url": url, "stderr": read_back.stderr},
        )
    try:
        observed = json.loads(read_back.stdout)
    except json.JSONDecodeError:
        return _unknown(
            "pr_read_back_invalid_json",
            "作成後のPR情報がJSONではありません",
            "PRを編集せず、read-backを再実行してください",
            {"url": url},
        )
    if not isinstance(observed, dict):
        return _unknown(
            "pr_read_back_invalid_shape",
            "作成後のPR情報がobjectではありません",
            "PRを編集せず、API応答を確認してください",
            {"url": url},
        )

    observed_title = observed.get("title")
    observed_body = observed.get("body")
    observed_head = observed.get("headRefName")
    observed_head_sha = observed.get("headRefOid")
    observed_base = observed.get("baseRefName")
    observed_base_sha = observed.get("baseRefOid")
    observed_draft = observed.get("isDraft")
    if not isinstance(observed_title, str) or not isinstance(observed_body, str):
        return _unknown(
            "pr_read_back_metadata_missing",
            "作成後のPR title/bodyを確認できません",
            "PRを編集せず、API応答を確認してください",
            {"url": url},
        )
    observed_language = check_pr_metadata(observed_title, observed_body)
    exact_match = (
        observed_title == title
        and observed_body == body
        and observed_head == head
        and observed_head_sha == expected_head_sha
        and observed_base == base
        and observed_base_sha == expected_base_sha
        and observed_draft is draft
    )
    evidence = {
        "url": url,
        "repository": repo,
        "base": observed_base,
        "base_sha": observed_base_sha,
        "head": observed_head,
        "head_sha": observed_head_sha,
        "is_draft": observed_draft,
        "title_body_exact_match": exact_match,
        "japanese_gate": observed_language.code,
        "branch_purpose": branch_purpose,
        "content_check": content.evidence,
    }
    if observed_language.status is not Status.READY or not exact_match:
        return _unknown(
            "pr_read_back_mismatch",
            "作成後のPR表示面が承認済み入力と一致しません",
            "PRを編集せず、人間レビューで差分を確認してください",
            evidence,
        )
    return Outcome(
        status=Status.READY,
        code="pr_created_and_verified",
        cause="日本語gate通過後にPRを作成し、表示面を再確認しました",
        impact="PR URLを人間レビューへ渡せます",
        recovery="none",
        evidence=evidence,
    )


def _verify_preflight(
    *,
    repo: str,
    base: str,
    head: str,
    repo_root: Path,
    account_map_file: Path,
    expected_base_sha: str,
    expected_head_sha: str,
    expected_visibility: str,
    runner: Runner,
) -> Outcome:
    gh_host = os.environ.get("GH_HOST")
    if gh_host and gh_host.casefold() != "github.com":
        return _blocked(
            "github_host_mismatch",
            "GH_HOSTがoriginのgithub.comと一致しません",
            "GH_HOSTを解除し、github.com向けidentityを再確認してください",
            {"expected_host": "github.com", "configured_host": gh_host},
        )
    if ":" in head:
        return _blocked(
            "fork_head_unsupported",
            "fork修飾headは安全な照合対象外です",
            "同一repositoryのbranchを使用してください",
            {"head": head},
        )
    try:
        resolution = load_account_map(account_map_file).resolve(repo)
    except AccountMapError as exc:
        return _blocked(
            "account_map_invalid",
            "account mapを解決できません",
            "対象repositoryのaccount mapを確認してください",
            {"error": redact(str(exc))},
        )
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    identity = IdentityProbe(runner).probe(
        repo_root,
        expected_owner=resolution.expected_owner,
        expected_login=resolution.expected_login,
        token=token,
        expected_host="github.com",
    )
    if identity.status is not Status.READY:
        return identity
    if identity.evidence.get("repository") != repo:
        return _blocked(
            "remote_repository_mismatch",
            "origin repositoryが--repoと一致しません",
            "repo_root、origin、--repoを確認してください",
            {
                "expected_repository": repo,
                "origin_repository": identity.evidence.get("repository"),
            },
        )

    checks = {
        "status": runner.run(["git", "status", "--porcelain=v1"], cwd=repo_root),
        "head": runner.run(["git", "rev-parse", "HEAD"], cwd=repo_root),
        "base": runner.run(
            ["git", "ls-remote", "--heads", "origin", f"refs/heads/{base}"],
            cwd=repo_root,
        ),
        "remote_head": runner.run(
            ["git", "ls-remote", "--heads", "origin", f"refs/heads/{head}"],
            cwd=repo_root,
        ),
        "repo": runner.run(
            [
                "gh",
                "repo",
                "view",
                f"github.com/{repo}",
                "--json",
                "nameWithOwner,visibility,viewerPermission,defaultBranchRef",
            ],
            cwd=repo_root,
            scoped_env={"GH_HOST": "github.com"},
        ),
    }
    if any(result.returncode != 0 for result in checks.values()):
        return _unknown(
            "pr_preflight_command_failed",
            "PR作成前の一次証拠を取得できません",
            "Git、GitHub認証、networkを確認してください",
            {"repository": repo},
        )
    if checks["status"].stdout:
        return _blocked(
            "worktree_not_clean",
            "worktreeに未commit変更があります",
            "PR対象をcommitし、clean状態を再確認してください",
            {"repository": repo},
        )
    local_head = checks["head"].stdout.strip()
    remote_base_fields = checks["base"].stdout.split()
    base_sha = remote_base_fields[0] if remote_base_fields else ""
    remote_head_fields = checks["remote_head"].stdout.split()
    remote_head_sha = remote_head_fields[0] if remote_head_fields else ""
    try:
        repo_info = json.loads(checks["repo"].stdout)
    except json.JSONDecodeError:
        return _unknown(
            "repo_metadata_invalid",
            "repository情報がJSONではありません",
            "GitHub APIを再確認してください",
            {"repository": repo},
        )
    if not isinstance(repo_info, dict):
        return _unknown(
            "repo_metadata_invalid_shape",
            "repository情報がobjectではありません",
            "GitHub APIを再確認してください",
            {"repository": repo},
        )
    permission = repo_info.get("viewerPermission")
    exact = (
        repo_info.get("nameWithOwner") == repo
        and repo_info.get("visibility") == expected_visibility
        and permission in {"WRITE", "MAINTAIN", "ADMIN"}
        and local_head == expected_head_sha
        and remote_head_sha == expected_head_sha
        and base_sha == expected_base_sha
    )
    evidence = {
        "repository": repo,
        "login": identity.evidence.get("login"),
        "visibility": repo_info.get("visibility"),
        "permission": permission,
        "base": base,
        "base_sha": base_sha,
        "head": head,
        "local_head_sha": local_head,
        "remote_head_sha": remote_head_sha,
    }
    if not exact:
        return _blocked(
            "pr_preflight_mismatch",
            "PR作成前の対象、identity、権限、SHAが期待値と一致しません",
            "差分を確認し、期待値を更新せず停止してください",
            evidence,
        )
    return Outcome(
        Status.READY,
        "pr_preflight_ready",
        "PR作成前のidentity、visibility、権限、base/head SHAを確認しました",
        "日本語gate通過後のPR作成へ進めます",
        "none",
        evidence,
    )


def _verify_content(*, repo_root: Path, base_sha: str, head_sha: str, runner: Runner) -> Outcome:
    """固定SHAのGit一致だけを判定し、意味の同値や枝名から目的を推測しない。"""
    evidence = {"base_sha": base_sha, "head_sha": head_sha}

    def git(*args: str) -> CommandResult:
        return runner.run(["git", *args], cwd=repo_root, redact_stdout=False)

    def valid_oid(value: str) -> bool:
        return bool(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value))

    def invalid_evidence() -> Outcome:
        return _unknown(
            "content_evidence_invalid",
            "採用検査のGit出力が完全な形式ではありません",
            "出力形式とpathを確認し、独立レビューしてください",
            evidence,
        )

    if not valid_oid(base_sha) or not valid_oid(head_sha):
        return invalid_evidence()
    try:
        ancestor = git("merge-base", "--all", base_sha, head_sha)
        base_tree = git("rev-parse", f"{base_sha}^{{tree}}")
        merged = git("merge-tree", "--write-tree", base_sha, head_sha)
        if any(result.returncode or result.failure is not None
               for result in (ancestor, base_tree, merged)):
            return _unknown(
                "content_integration_unknown",
                "差分の採用状態を確定できません",
                "競合や不足objectを読取り確認し、独立レビューしてください",
                evidence,
            )
        ancestors = ancestor.stdout.strip().splitlines()
        tree = merged.stdout.strip().splitlines()
        if (
            len(ancestors) != 1 or len(tree) != 1
            or not valid_oid(ancestors[0]) or not valid_oid(tree[0])
            or not valid_oid(base_tree.stdout.strip())
            or len({len(base_sha), len(head_sha), len(ancestors[0]),
                    len(tree[0]), len(base_tree.stdout.strip())}) != 1
        ):
            return _unknown(
                "content_integration_unknown",
                "統合基点または結果が一意ではありません",
                "独立レビューで統合基点を確定してください",
                evidence,
            )
        evidence["merge_base_sha"] = ancestors[0]
        evidence["merged_tree"] = tree[0]
        if tree[0] == base_tree.stdout.strip():
            return _blocked(
                "content_already_adopted",
                "枝の変更は基準側に採用済み、または差分がありません",
                "既存の採用証拠を確認し、重複PRを作成しないでください",
                evidence,
            )
        paths = git("diff", "--name-only", "--no-renames", "-z", ancestors[0], head_sha)
        if paths.returncode or paths.failure is not None:
            return _unknown(
                "content_paths_unknown",
                "変更対象を取得できません",
                "Git差分を独立レビューしてください",
                evidence,
            )
        if (
            not paths.stdout.endswith("\0")
            or any(char in paths.stdout for char in ("\r", "\n", "\ufffd"))
        ):
            return invalid_evidence()
        changed_paths = paths.stdout[:-1].split("\0")
        if not all(changed_paths) or len(set(changed_paths)) != len(changed_paths):
            return invalid_evidence()
        adopted = False
        unique = False
        overlap = False
        for path in changed_paths:
            entries = [
                git("--literal-pathspecs", "ls-tree", "-z", ref, "--", path)
                for ref in (ancestors[0], base_sha, head_sha)
            ]
            if any(entry.returncode or entry.failure is not None for entry in entries):
                return _unknown(
                    "content_entries_unknown",
                    "変更対象の採用状態を取得できません",
                    "Git差分を独立レビューしてください",
                    evidence,
                )
            parsed = []
            for entry in entries:
                if not entry.stdout:
                    parsed.append("")
                    continue
                if not entry.stdout.endswith("\0") or entry.stdout.count("\0") != 1:
                    return invalid_evidence()
                metadata, separator, observed_path = entry.stdout[:-1].partition("\t")
                fields = metadata.split(" ")
                if (
                    not separator or observed_path != path or len(fields) != 3
                    or fields[0] not in {"100644", "100755", "120000", "160000"}
                    or fields[1] != ("commit" if fields[0] == "160000" else "blob")
                    or not valid_oid(fields[2]) or len(fields[2]) != len(head_sha)
                ):
                    return invalid_evidence()
                parsed.append(entry.stdout)
            old, base_entry, head_entry = parsed
            if not old and not head_entry:
                return invalid_evidence()
            if base_entry == head_entry:
                adopted = True
            else:
                unique = True
                if base_entry != old:
                    overlap = True
        if overlap or (adopted and unique) or not unique:
            return _blocked(
                "content_adoption_review_required",
                "部分採用または基準側と重なる変更に独立レビューが必要です",
                "固有変更を分離し、最新基準から計画を作り直してください",
                evidence,
            )
        return Outcome(
            Status.READY,
            "content_unique",
            "基準側に未採用の固有変更を確認しました",
            "PR作成へ進めます",
            "none",
            evidence,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        evidence["error"] = redact(str(exc))
        return _unknown(
            "content_verification_failed",
            "採用状態の検査を完了できません",
            "Gitを確認し、再作成せず読取り検査してください",
            evidence,
        )


def _blocked(code: str, cause: str, recovery: str, evidence: dict) -> Outcome:
    return Outcome(Status.BLOCKED, code, cause, "PR作成へ進めません", recovery, evidence)


def _unknown(code: str, cause: str, recovery: str, evidence: dict) -> Outcome:
    return Outcome(Status.UNKNOWN, code, cause, "PR作成後の状態を完了扱いにできません", recovery, evidence)
