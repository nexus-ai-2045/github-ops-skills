from scripts.run_private_canary import CanaryRequest, validate_canary_request


def test_canary_requires_exact_confirmation() -> None:
    result = validate_canary_request(
        CanaryRequest("example-org/fixture", "PRIVATE", "canary/test", "検証", False)
    )
    assert result.status.value == "BLOCKED"
    assert result.code == "canary_confirmation_missing"


def test_canary_rejects_public_repo() -> None:
    result = validate_canary_request(
        CanaryRequest("example-org/fixture", "PUBLIC", "canary/test", "検証", True)
    )
    assert result.code == "canary_repo_not_private"


def test_confirmed_private_canary_is_ready_for_human_decision_only() -> None:
    result = validate_canary_request(
        CanaryRequest("example-org/fixture", "PRIVATE", "canary/test", "検証", True)
    )
    assert result.status.value == "READY"
