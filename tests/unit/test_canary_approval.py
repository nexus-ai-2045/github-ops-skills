import json
from datetime import datetime, timedelta, timezone

import pytest

from github_ops.canary_approval import ApprovalError, sign_approval, validate_approval


NOW = datetime(2026, 8, 6, tzinfo=timezone.utc)
KEY = "k" * 32


def payload() -> dict:
    return {
        "schema_version": "github-ops/private-canary-approval/v1",
        "recorded_at": NOW.isoformat(),
        "recorded_by": "codex",
        "target_repo": "nexus-ai-2045/github-ops-skills",
        "branch": "canary/github-ops-skills",
        "operation": "push_and_create_draft_pr",
        "executor_sha256": "a" * 64,
        "thread_id": "thread-1",
        "approved_by": "user",
        "expires_at": (NOW + timedelta(minutes=30)).isoformat(),
        "nonce": "n" * 32,
        "consumed": False,
    }


def test_signed_approval_is_bound_to_expected_fields(tmp_path) -> None:
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(sign_approval(payload(), KEY)), encoding="utf-8")
    result = validate_approval(
        path,
        key=KEY,
        now=NOW,
        expected={"target_repo": "nexus-ai-2045/github-ops-skills", "executor_sha256": "a" * 64},
    )
    assert result["consumed"] is False


def test_tampered_or_expired_approval_is_rejected(tmp_path) -> None:
    path = tmp_path / "approval.json"
    signed = sign_approval(payload(), KEY)
    signed["branch"] = "canary/other"
    path.write_text(json.dumps(signed), encoding="utf-8")
    with pytest.raises(ApprovalError, match="signature mismatch"):
        validate_approval(path, key=KEY, now=NOW, expected={})

    expired = payload()
    expired["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    path.write_text(json.dumps(sign_approval(expired, KEY)), encoding="utf-8")
    with pytest.raises(ApprovalError, match="expired"):
        validate_approval(path, key=KEY, now=NOW, expected={})
