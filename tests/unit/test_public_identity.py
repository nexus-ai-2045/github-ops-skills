from pathlib import Path

from github_ops.public_identity import (
    scan_repository_for_personal_paths,
    scan_repository_for_token_shapes,
    scan_text,
)


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
