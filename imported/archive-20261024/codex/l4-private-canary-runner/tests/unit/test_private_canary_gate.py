from scripts.run_private_canary import (
    CanaryRequest,
    build_mutation_plan,
    validate_canary_request,
)


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


def test_mutation_plan_names_exact_target_and_external_boundaries() -> None:
    request = CanaryRequest(
        "nexus-ai-2045/github-ops-skills",
        "PRIVATE",
        "canary/github-ops-skills",
        "GitHub操作経路canary",
        False,
    )

    plan = build_mutation_plan(request)

    assert plan["target_repo"] == request.repo
    assert plan["head_branch"] == request.branch
    assert plan["changed_paths"] == [
        ".github/private-canary/github-ops-skills.json"
    ]
    assert "scripts/execute_private_canary.py" in plan["executor_command"]
    assert "--execute" in plan["executor_command"]
    assert plan["stop_boundaries"]["automatic_cleanup"] is False
    assert "main merge" in plan["stop_boundaries"]["out_of_scope"]


def test_mutation_plan_requires_draft_pr_and_read_back() -> None:
    request = CanaryRequest(
        "example-org/fixture",
        "PRIVATE",
        "canary/test",
        "検証用canary",
        False,
    )

    operations = build_mutation_plan(request)["exact_operation"]

    assert any("gh pr create" in operation and "--draft" in operation for operation in operations)
    assert any("gh pr view" in operation for operation in operations)
