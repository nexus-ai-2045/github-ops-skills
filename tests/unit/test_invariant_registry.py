from pathlib import Path

from scripts.verify_invariant_registry import verify


def test_repository_invariant_registry_is_self_consistent() -> None:
    assert verify(Path(__file__).resolve().parents[2]) == []
