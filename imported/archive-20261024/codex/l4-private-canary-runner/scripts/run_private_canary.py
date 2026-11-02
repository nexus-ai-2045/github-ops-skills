from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.output import configure_utf8_stdout
from github_ops.result import Outcome, Status


SCHEMA_VERSION = "github-ops/private-canary-review/v2"
RECORDED_BY = "codex"


@dataclass(frozen=True)
class CanaryRequest:
    repo: str
    visibility: str
    branch: str
    draft_pr_title: str
    confirmed: bool


def validate_canary_request(request: CanaryRequest) -> Outcome:
    if request.visibility.upper() != "PRIVATE":
        return Outcome(Status.BLOCKED, "canary_repo_not_private",
                       "canary対象がprivateではありません", "外部変更は実行しません",
                       "private repositoryを指定してください", {})
    if not request.confirmed:
        return Outcome(Status.BLOCKED, "canary_confirmation_missing",
                       "現在会話でのcanary承認がありません", "外部変更は実行しません",
                       "review packetを人間確認してください", {})
    return Outcome(Status.READY, "canary_request_valid",
                   "private canary条件が揃いました", "実行可否の人間判断へ進めます",
                   "実装工程では実行しません", {"validated": True})


def build_mutation_plan(request: CanaryRequest) -> dict[str, object]:
    marker_path = ".github/private-canary/github-ops-skills.json"
    return {
        "target_repo": request.repo,
        "base_branch": "main",
        "head_branch": request.branch,
        "draft_pr": {
            "title": request.draft_pr_title,
            "visibility": "private repository collaborators only",
        },
        "changed_paths": [marker_path],
        "executor_command": (
            "python scripts/execute_private_canary.py --repo . "
            f"--target-repo {request.repo} --branch {request.branch} "
            f'--draft-pr-title "{request.draft_pr_title}" '
            "--expected-account nexus-ai-2045 "
            f"--approval-ref L4-CANARY:{request.repo}:{request.branch} "
            "--approval-file <repo-external-approval.json> "
            "--thread-id <current-thread-id> "
            "--confirm-private-canary --execute "
            "--report-path <repo-external-private-canary-execution.json>"
        ),
        "exact_operation": [
            "git fetch origin main",
            f"git switch --create {request.branch} origin/main",
            f"write canary marker to {marker_path}",
            f"git add -- {marker_path}",
            'git commit -m "test: add private L4 canary marker"',
            f"git push origin HEAD:refs/heads/{request.branch}",
            (
                "gh pr create "
                f"--repo {request.repo} --base main --head {request.branch} "
                f'--draft --title "{request.draft_pr_title}" --body-file <reviewed-body-file>'
            ),
            f"gh pr view --repo {request.repo} {request.branch} --json number,isDraft,state,url,headRefName,baseRefName",
        ],
        "success_evidence": [
            "repository visibility is PRIVATE",
            "authenticated account matches the reviewed account",
            "remote owner/name matches target_repo",
            "push created exactly head_branch",
            "read-back reports OPEN draft PR with matching base/head",
            "global active account is unchanged",
            "report contains no credential material",
            "approval artifact is HMAC-valid, unexpired, executor-bound, and one-time",
        ],
        "failure_evidence": [
            "visibility, account, owner, remote, or branch mismatch",
            "dirty worktree or pre-existing canary branch",
            "push or draft PR creation failure",
            "read-back mismatch or missing evidence",
            "credential material detected in output",
            "approval artifact invalid, expired, tampered, or consumed",
        ],
        "stop_boundaries": {
            "requires_separate_current_conversation_approval": [
                "push canary branch",
                "create draft PR",
                "close draft PR",
                "delete remote branch",
            ],
            "out_of_scope": [
                "repository visibility change",
                "release",
                "main merge",
                "voice runtime",
            ],
            "automatic_cleanup": False,
        },
    }


def main() -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--draft-pr-title", required=True)
    parser.add_argument("--visibility", default="PRIVATE")
    parser.add_argument("--review-packet", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-private-canary", action="store_true")
    args = parser.parse_args()
    request = CanaryRequest(args.repo, args.visibility, args.branch,
                            args.draft_pr_title, args.confirm_private_canary)
    outcome = validate_canary_request(request)
    packet = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": datetime.now(
            timezone(timedelta(hours=9), name="JST")
        ).isoformat(),
        "recorded_by": RECORDED_BY,
        "request": asdict(request),
        "gate": outcome.to_dict(),
        "mutation_plan": build_mutation_plan(request),
        "executed": False,
        "note": "このversionは人間レビュー用planのみを生成し、--executeでも外部変更しません",
    }
    args.review_packet.parent.mkdir(parents=True, exist_ok=True)
    args.review_packet.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
