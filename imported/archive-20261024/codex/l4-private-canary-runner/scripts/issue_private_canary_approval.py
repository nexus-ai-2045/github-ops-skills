from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.canary_approval import SCHEMA_VERSION, sign_approval
from github_ops.output import configure_utf8_stdout


def main() -> int:
    configure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Issue one-time L4 canary approval")
    parser.add_argument("--target-repo", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--executor-sha256", required=True)
    parser.add_argument("--executor-commit", required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--draft-pr-title", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    key = os.environ.get("GITHUB_OPS_CANARY_APPROVAL_KEY", "")
    if not 1 <= args.minutes <= 60:
        parser.error("--minutes must be between 1 and 60")
    now = datetime.now(timezone.utc)
    payload = sign_approval(
        {
            "schema_version": SCHEMA_VERSION,
            "recorded_at": now.isoformat(),
            "recorded_by": "codex",
            "target_repo": args.target_repo,
            "branch": args.branch,
            "operation": "push_and_create_draft_pr",
            "executor_sha256": args.executor_sha256,
            "executor_commit": args.executor_commit,
            "expected_account": args.expected_account,
            "draft_pr_title": args.draft_pr_title,
            "thread_id": args.thread_id,
            "approved_by": args.approved_by,
            "expires_at": (now + timedelta(minutes=args.minutes)).isoformat(),
            "nonce": secrets.token_urlsafe(32),
            "consumed": False,
        },
        key,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "READY", "path": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
