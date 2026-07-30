from pathlib import Path

from github_ops.public_identity import (
    scan_repository_for_personal_paths,
    scan_repository_for_token_shapes,
    scan_text,
)
from github_ops.command import CommandRunner
from scripts.public_identity_guard import scan_git_tree


def test_windows_personal_path_is_blocked_without_echoing_value() -> None:
    personal_path = "C:" + "\\Users\\alice\\secret.txt"
    result = scan_text(personal_path)
    assert result.status.value == "BLOCKED"
    assert "alice" not in result.to_json()


def test_token_shape_is_blocked_without_echoing_value() -> None:
    token = "gh" + "p_" + "a" * 36
    result = scan_text(token)
    assert result.status.value == "BLOCKED"
    assert token not in result.to_json()


def test_repository_scanners_return_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "safe.txt").write_text("安全", encoding="utf-8")
    (tmp_path / "bad.txt").write_text(
        "C:" + "\\Users\\alice\\secret.txt",
        encoding="utf-8",
    )
    assert scan_repository_for_personal_paths(tmp_path) == ["bad.txt"]
    assert scan_repository_for_token_shapes(tmp_path) == []


def test_git_tree_scan_ignores_sensitive_text_deleted_from_head(
    tmp_path: Path,
) -> None:
    runner = CommandRunner()
    runner.run(["git", "init"], cwd=tmp_path)
    sample = tmp_path / "sample.txt"
    sample.write_text("C:" + "\\Users\\alice\\secret.txt\n", encoding="utf-8")
    runner.run(["git", "add", "sample.txt"], cwd=tmp_path)
    runner.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-m", "add sample",
        ],
        cwd=tmp_path,
    )
    sample.write_text("safe\n", encoding="utf-8")
    runner.run(["git", "add", "sample.txt"], cwd=tmp_path)
    runner.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-m", "sanitize",
        ],
        cwd=tmp_path,
    )

    assert scan_git_tree(runner, tmp_path, "HEAD").status.value == "READY"
