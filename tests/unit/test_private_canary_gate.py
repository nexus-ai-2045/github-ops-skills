import re
import shlex
import shutil
import subprocess

import pytest

from scripts.run_private_canary import (
    MARKER_PATH,
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


def test_mutation_plan_verifies_private_target_before_any_git_write() -> None:
    request = CanaryRequest("example-org/fixture", "PRIVATE", "canary/test", "検証", False)
    operations = build_mutation_plan(request)["exact_operation"]

    verify = next(i for i, op in enumerate(operations) if op.startswith("test ") and "gh repo view" in op)
    first_write = next(i for i, op in enumerate(operations) if op.startswith(("git switch", "git push", "git commit")))

    assert operations[:2] == ["set -eu", "cd <reviewed-repo-root>"]
    assert verify < first_write
    assert shlex.quote("example-org/fixture PRIVATE") in operations[verify]


def test_mutation_plan_rejects_dirty_checkout_and_commits_only_marker() -> None:
    request = CanaryRequest("example-org/fixture", "PRIVATE", "canary/test", "検証", False)
    operations = build_mutation_plan(request)["exact_operation"]

    clean = operations.index('test -z "$(git status --porcelain)" || exit 1')
    switch = next(i for i, op in enumerate(operations) if op.startswith("git switch"))
    commit = next(op for op in operations if op.startswith("git commit"))

    assert clean < switch
    assert "--only" in commit
    assert commit.endswith(f"-- {MARKER_PATH}")


WRITE_PREFIXES = ("git switch", "git add", "git commit", "git push", "python " + CREATE_PR)


def test_every_pre_write_condition_is_checked_before_the_first_write() -> None:
    request = CanaryRequest("example-org/fixture", "PRIVATE", "canary/test", "検証", False)
    plan = build_mutation_plan(request)
    operations = plan["exact_operation"]
    checks = plan["pre_write_checks"]

    assert set(checks) == {
        "remote owner/name and visibility",
        "authenticated account",
        "dirty worktree",
        "pre-existing canary branch",
        "pre-existing local canary branch",
    }
    first_write = next(i for i, op in enumerate(operations) if op.startswith(WRITE_PREFIXES))
    for condition, check in checks.items():
        assert operations.index(check) < first_write, condition
        assert check.endswith("|| exit 1"), condition
    switch = next(i for i, op in enumerate(operations) if op.startswith("git switch"))
    assert operations[switch + 1].startswith('test "$(git branch --show-current)" = ')


@pytest.mark.skipif(shutil.which("sh") is None or shutil.which("git") is None, reason="sh と git が要る")
def test_planned_git_steps_stop_when_a_local_canary_branch_already_exists(tmp_path) -> None:
    request = CanaryRequest("example-org/fixture", "PRIVATE", "canary/test", "検証", False)
    plan = build_mutation_plan(request)
    steps = [
        op
        for op in plan["exact_operation"]
        if op == "set -eu"
        or op.startswith(("git switch", 'test "$(git branch --show-current)"'))
        or op == plan["pre_write_checks"]["pre-existing local canary branch"]
    ]
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], env=env, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "base"], cwd=work, env=env, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=work, env=env, check=True)
    subprocess.run(["git", "branch", "canary/test"], cwd=work, env=env, check=True)

    result = subprocess.run(
        ["sh", "-c", "\n".join(steps) + "\necho reached-write"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "reached-write" not in result.stdout


@pytest.mark.skipif(shutil.which("sh") is None or shutil.which("git") is None, reason="sh と git が要る")
def test_planned_push_refuses_to_update_an_existing_remote_branch(tmp_path) -> None:
    request = CanaryRequest("example-org/fixture", "PRIVATE", "canary/test", "検証", False)
    push = next(op for op in build_mutation_plan(request)["exact_operation"] if op.startswith("git push"))
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }

    def git(*args: str, cwd) -> None:
        subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)

    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git("init", "--bare", "-q", str(remote), cwd=tmp_path)
    git("init", "-q", str(work), cwd=tmp_path)
    git("remote", "add", "origin", str(remote), cwd=work)
    git("commit", "--allow-empty", "-q", "-m", "base", cwd=work)
    git("push", "-q", "origin", "HEAD:refs/heads/canary/test", cwd=work)
    git("commit", "--allow-empty", "-q", "-m", "marker", cwd=work)

    result = subprocess.run(["sh", "-c", push], cwd=work, env=env, capture_output=True, text=True)

    assert result.returncode != 0


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
