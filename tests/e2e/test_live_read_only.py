from scripts.run_read_only_e2e import required_inputs


def test_live_runner_reports_missing_inputs() -> None:
    result = required_inputs({})
    assert result.status.value == "BLOCKED"
    assert result.code == "live_input_missing"
    assert len(result.evidence["missing"]) == 3


def test_live_runner_accepts_complete_inputs() -> None:
    result = required_inputs(
        {
            "GITHUB_OPS_LIVE_REPO": "example-org/tool",
            "GITHUB_OPS_EXPECTED_OWNER": "example-org",
            "GITHUB_OPS_ACCOUNT_MAP": "account-map.yaml",
        }
    )
    assert result.status.value == "READY"
