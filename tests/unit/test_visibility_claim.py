from __future__ import annotations

import json
from pathlib import Path

from github_ops.result import Status
from github_ops.visibility_claim import (
    classify_unauthenticated_http,
    compare_visibility_claim,
    evaluate_visibility_claim,
    parse_public_ready_visibility,
)
from scripts.check_visibility_claim import main as check_visibility_claim_main


PUBLIC_READY_PUBLIC = "状態: **公開済み・lockdown 一部完了**\n"
PUBLIC_READY_PRIVATE = "状態: **PRIVATE（live）・公開未承認**\n"
PUBLIC_READY_2026_08_26_LIE = "状態: **公開済み・lockdown 未完了**\n"


def test_parse_public_ready_visibility_public_claim() -> None:
    assert parse_public_ready_visibility(PUBLIC_READY_PUBLIC) == "PUBLIC"


def test_parse_public_ready_visibility_private_claim() -> None:
    assert parse_public_ready_visibility(PUBLIC_READY_PRIVATE) == "PRIVATE"


def test_parse_public_ready_visibility_negated_public_wording_is_private() -> None:
    text = "状態: **非公開（公開済みではない）**\n"
    assert parse_public_ready_visibility(text) == "PRIVATE"
    result = evaluate_visibility_claim(text, 200)
    assert result.status is Status.BLOCKED
    assert result.code == "visibility_claim_mismatch"
    assert result.evidence["claim"] == "PRIVATE"
    assert result.evidence["observed"] == "PUBLIC"


def test_parse_public_ready_visibility_empty_or_missing_status_is_unknown() -> None:
    assert parse_public_ready_visibility("") == "UNKNOWN"
    assert parse_public_ready_visibility("lockdown 一部完了\n") == "UNKNOWN"


def test_classify_unauthenticated_http() -> None:
    assert classify_unauthenticated_http(200) == "PUBLIC"
    assert classify_unauthenticated_http(404) == "PRIVATE"
    assert classify_unauthenticated_http(0) == "UNKNOWN"
    assert classify_unauthenticated_http(500) == "UNKNOWN"


def test_compare_public_claim_against_private_oracle_is_blocked() -> None:
    result = compare_visibility_claim("PUBLIC", "PRIVATE")
    payload = json.loads(result.to_json())
    assert result.status is Status.BLOCKED
    assert result.code == "visibility_claim_mismatch"
    assert payload["evidence"]["claim"] == "PUBLIC"
    assert payload["evidence"]["observed"] == "PRIVATE"
    assert "ghp_" not in result.to_json()
    assert "github_pat_" not in result.to_json()


def test_compare_public_claim_against_public_oracle_is_ready() -> None:
    result = compare_visibility_claim("PUBLIC", "PUBLIC")
    assert result.status is Status.READY
    assert result.evidence["claim"] == "PUBLIC"
    assert result.evidence["observed"] == "PUBLIC"


def test_compare_private_claim_against_public_oracle_is_inverse_drift() -> None:
    result = compare_visibility_claim("PRIVATE", "PUBLIC")
    assert result.status is Status.BLOCKED
    assert result.code == "visibility_claim_mismatch"
    assert result.evidence["claim"] == "PRIVATE"
    assert result.evidence["observed"] == "PUBLIC"


def test_unknown_claim_or_observed_is_unknown_not_ready() -> None:
    unknown_claim = compare_visibility_claim("UNKNOWN", "PUBLIC")
    unknown_observed = compare_visibility_claim("PUBLIC", "UNKNOWN")
    both_unknown = compare_visibility_claim("UNKNOWN", "UNKNOWN")
    for result in (unknown_claim, unknown_observed, both_unknown):
        assert result.status is Status.UNKNOWN
        assert result.status is not Status.READY


def test_regression_2026_08_26_public_ready_lie_with_unauth_404_is_blocked() -> None:
    token = "gh" + "p_" + "a" * 36
    text = (
        PUBLIC_READY_2026_08_26_LIE
        + f"GH_TOKEN={token}\n"
        + "owner-logged-in gh repo view is not the public oracle\n"
    )
    result = evaluate_visibility_claim(text, 404)
    assert parse_public_ready_visibility(text) == "PUBLIC"
    assert classify_unauthenticated_http(404) == "PRIVATE"
    assert result.status is Status.BLOCKED
    assert result.code == "visibility_claim_mismatch"
    assert result.evidence["claim"] == "PUBLIC"
    assert result.evidence["observed"] == "PRIVATE"
    assert token not in result.to_json()
    assert "ghp_" not in result.to_json()


def test_cli_checks_caller_supplied_status_code_without_network(
    tmp_path: Path,
    capsys,
) -> None:
    public_ready = tmp_path / "PUBLIC_READY.md"
    public_ready.write_text(PUBLIC_READY_2026_08_26_LIE, encoding="utf-8")
    exit_code = check_visibility_claim_main(
        ["--public-ready", str(public_ready), "--status-code", "404", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "BLOCKED"
    assert payload["code"] == "visibility_claim_mismatch"
    assert payload["evidence"]["claim"] == "PUBLIC"
    assert payload["evidence"]["observed"] == "PRIVATE"
    assert payload["evidence"]["status_code"] == 404
