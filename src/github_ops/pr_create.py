from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, Sequence

from .command import CommandResult, CommandRunner
from .pr_language import check_pr_metadata
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
    confirmed: bool,
    draft: bool = False,
    runner: Runner | None = None,
) -> Outcome:
    """日本語gate通過後にPRを作成し、表示面をread-back検証する。"""
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
            {"body_file": str(body_file), "error": str(exc)},
        )
    language = check_pr_metadata(title, body)
    if language.status is not Status.READY:
        return language

    command_runner = runner or CommandRunner()
    create_argv = [
        "gh",
        "pr",
        "create",
        "--repo",
        repo,
        "--base",
        base,
        "--head",
        head,
        "--title",
        title,
        "--body-file",
        str(body_file),
    ]
    if draft:
        create_argv.append("--draft")
    created = command_runner.run(create_argv, timeout=60)
    if created.returncode != 0:
        return _blocked(
            "pr_create_failed",
            "gh pr createが失敗しました",
            "stderrを確認し、原因解消後に再実行してください",
            {"repository": repo, "stderr": created.stderr},
        )

    url = created.stdout.strip().splitlines()[-1] if created.stdout.strip() else ""
    if not url.startswith("https://github.com/"):
        return _unknown(
            "pr_url_unavailable",
            "PR作成結果からURLを取得できません",
            "GitHub上のPRを確認し、重複作成せず手動でread-backしてください",
            {"repository": repo, "stdout": created.stdout},
        )

    read_back = command_runner.run(
        [
            "gh",
            "pr",
            "view",
            url,
            "--repo",
            repo,
            "--json",
            "url,title,body,headRefName,baseRefName",
        ]
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
    observed_base = observed.get("baseRefName")
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
        and observed_base == base
    )
    evidence = {
        "url": url,
        "repository": repo,
        "base": observed_base,
        "head": observed_head,
        "title_body_exact_match": exact_match,
        "japanese_gate": observed_language.code,
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


def _blocked(code: str, cause: str, recovery: str, evidence: dict) -> Outcome:
    return Outcome(Status.BLOCKED, code, cause, "PR作成へ進めません", recovery, evidence)


def _unknown(code: str, cause: str, recovery: str, evidence: dict) -> Outcome:
    return Outcome(Status.UNKNOWN, code, cause, "PR作成後の状態を完了扱いにできません", recovery, evidence)
