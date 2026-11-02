from pathlib import Path

from github_ops.public_identity import (
    scan_repository_for_personal_paths,
    scan_repository_for_token_shapes,
)


def test_public_readiness_files_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("README.md", "LICENSE", "SECURITY.md", "PUBLIC_READY.md"):
        assert (root / name).is_file(), name


def test_repository_contains_no_personal_absolute_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    assert scan_repository_for_personal_paths(root) == []


def test_repository_contains_no_token_shaped_values() -> None:
    root = Path(__file__).resolve().parents[2]
    assert scan_repository_for_token_shapes(root) == []
