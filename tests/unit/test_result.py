import json

import pytest

from github_ops.result import Outcome, Status


def test_outcome_json_contract_is_stable() -> None:
    outcome = Outcome(
        status=Status.BLOCKED,
        code="owner_mismatch",
        cause="token login does not match expected login",
        impact="GitHub write was not attempted",
        recovery="provide a token for the expected login",
        evidence={"expected_login": "example-user", "token_login": "other-user"},
    )
    assert json.loads(outcome.to_json()) == {
        "status": "BLOCKED",
        "code": "owner_mismatch",
        "cause": "token login does not match expected login",
        "impact": "GitHub write was not attempted",
        "recovery": "provide a token for the expected login",
        "evidence": {
            "expected_login": "example-user",
            "token_login": "other-user",
        },
    }


def test_ready_requires_evidence() -> None:
    with pytest.raises(ValueError, match="READY requires evidence"):
        Outcome(
            status=Status.READY,
            code="ready",
            cause="all checks passed",
            impact="operation may continue",
            recovery="none",
            evidence={},
        )
