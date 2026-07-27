from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.result import Outcome, Status


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


def main() -> int:
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
        "schema_version": "github-ops/private-canary-review/v1",
        "recorded_at": datetime.now(
            timezone(timedelta(hours=9), name="JST")
        ).isoformat(),
        "request": asdict(request),
        "gate": outcome.to_dict(),
        "executed": False,
        "note": "--execute指定時もこのversionは外部変更を実行しません",
    }
    args.review_packet.parent.mkdir(parents=True, exist_ok=True)
    args.review_packet.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
