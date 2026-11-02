import re
import shlex
import shutil
import subprocess

import pytest

from scripts.run_private_canary import (
    CanaryRequest,
    build_mutation_plan,
    validate_canary_request,
)

CREATE_PR = "scripts/create_pr_with_japanese_gate.py"


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
        "example-org/fixture",
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
    # 実行器はこのrepositoryに無い。planは人間が読むためだけのもの。
    assert plan["executor"] is None
    assert not any("--execute" in operation for operation in plan["exact_operation"])
    assert plan["stop_boundaries"]["automatic_cleanup"] is False
    assert "main merge" in plan["stop_boundaries"]["out_of_scope"]
    assert "push canary branch" in plan["stop_boundaries"][
        "requires_separate_current_conversation_approval"
    ]


def test_mutation_plan_requires_draft_pr_and_read_back() -> None:
    request = CanaryRequest(
        "example-org/fixture",
        "PRIVATE",
        "canary/test",
        "検証用canary",
        False,
    )

    operations = build_mutation_plan(request)["exact_operation"]

    create = next(operation for operation in operations if CREATE_PR in operation)
    assert "--draft" in create and "--confirm" in create
    assert not any(operation.startswith("gh pr create") for operation in operations)
    assert any("gh pr view" in operation for operation in operations)


def _fill_placeholders(operation: str) -> str:
    return re.sub(r"<([a-z-]+)>", r"\1", operation)


def test_mutation_plan_keeps_reviewed_title_as_one_shell_argument() -> None:
    title = "Canary \"private repo\" it's a check"
    request = CanaryRequest("example-org/fixture", "PRIVATE", "canary/test", title, False)

    create = next(
        operation
        for operation in build_mutation_plan(request)["exact_operation"]
        if CREATE_PR in operation
    )
    args = shlex.split(_fill_placeholders(create))

    assert args[args.index("--title") + 1] == title


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX shell が無い環境では展開を確かめられない")
def test_mutation_plan_keeps_reviewed_branch_and_repo_literal() -> None:
    branch = "canary/$USER"
    repo = "example-org/fixture"
    request = CanaryRequest(repo, "PRIVATE", branch, "検証", False)

    commands = [
        subprocess.run(
            ["sh", "-c", 'printf "%s\\n" ' + _fill_placeholders(operation).split(" ", 2)[2]],
            capture_output=True,
            text=True,
            check=True,
            env={"USER": "someone-else", "PATH": "/usr/bin:/bin"},
        ).stdout.splitlines()
        for operation in build_mutation_plan(request)["exact_operation"]
        if operation.startswith(("git switch", "git push", "gh pr", "python " + CREATE_PR))
    ]

    switch, push, create, view = commands
    assert switch[switch.index("--create") + 1] == branch
    assert push[-1] == f"HEAD:refs/heads/{branch}"
    assert create[create.index("--head") + 1] == branch
    assert create[create.index("--repo") + 1] == repo
    assert view[view.index("--repo") + 2] == branch
