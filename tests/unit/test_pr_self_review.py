from pathlib import Path

import pytest

from scripts.check_pr_self_review import (
    VerificationError,
    verify_artifact,
    verify_candidate,
)


ROOT = Path(__file__).resolve().parents[2]


def test_repository_artifact_and_packaged_copy_are_self_consistent() -> None:
    declared, computed = verify_artifact(ROOT)
    assert declared == computed


def test_candidate_must_match_trusted_base(tmp_path: Path) -> None:
    for relative in (
        Path("docs/pr-self-review.md"),
        Path("skills/commit-push-pr/references/pr-self-review.md"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())

    assert verify_candidate(tmp_path, ROOT)[0] == verify_artifact(ROOT)[0]


def test_trusted_check_rejects_candidate_self_edit(tmp_path: Path) -> None:
    for relative in (
        Path("docs/pr-self-review.md"),
        Path("skills/commit-push-pr/references/pr-self-review.md"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    changed = tmp_path / "docs/pr-self-review.md"
    changed.write_text(changed.read_text(encoding="utf-8") + "\n追記\n", encoding="utf-8")

    with pytest.raises(VerificationError, match="differs from"):
        verify_candidate(tmp_path, ROOT)


def test_trusted_check_rejects_missing_base_artifact(tmp_path: Path) -> None:
    for relative in (
        Path("docs/pr-self-review.md"),
        Path("skills/commit-push-pr/references/pr-self-review.md"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())

    with pytest.raises(VerificationError, match="bootstrap"):
        verify_candidate(tmp_path, tmp_path / "missing-base")
