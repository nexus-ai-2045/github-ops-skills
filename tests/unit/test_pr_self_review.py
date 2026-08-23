from pathlib import Path
import hashlib

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
        Path("docs/pr-self-review-trusted-digests.txt"),
        Path(".github/workflows/pr-self-review-trusted.yml"),
        Path("scripts/check_pr_self_review.py"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())

    assert verify_candidate(tmp_path, ROOT)[0] == verify_artifact(ROOT)[0]


def test_trusted_check_rejects_candidate_self_edit(tmp_path: Path) -> None:
    for relative in (
        Path("docs/pr-self-review.md"),
        Path("skills/commit-push-pr/references/pr-self-review.md"),
        Path("docs/pr-self-review-trusted-digests.txt"),
        Path(".github/workflows/pr-self-review-trusted.yml"),
        Path("scripts/check_pr_self_review.py"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    for relative in (
        Path("docs/pr-self-review.md"),
        Path("skills/commit-push-pr/references/pr-self-review.md"),
    ):
        changed = tmp_path / relative
        changed.write_text(
            changed.read_text(encoding="utf-8").replace(
                "title: PR セルフレビュー", "title: PR セルフレビュー（改変）"
            ),
            encoding="utf-8",
        )

    with pytest.raises(VerificationError, match="allowlist"):
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


def test_trusted_check_allows_a_preapproved_replacement(tmp_path: Path) -> None:
    for relative in (
        Path("docs/pr-self-review.md"),
        Path("skills/commit-push-pr/references/pr-self-review.md"),
        Path("docs/pr-self-review-trusted-digests.txt"),
        Path(".github/workflows/pr-self-review-trusted.yml"),
        Path("scripts/check_pr_self_review.py"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    for relative in (
        Path("docs/pr-self-review.md"),
        Path("skills/commit-push-pr/references/pr-self-review.md"),
    ):
        changed = tmp_path / relative
        changed.write_text(
            changed.read_text(encoding="utf-8").replace(
                "title: PR セルフレビュー", "title: PR セルフレビュー（更新）"
            ),
            encoding="utf-8",
        )
    digest = hashlib.sha256(
        (tmp_path / "docs/pr-self-review.md").read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    allowlist = tmp_path / "docs/pr-self-review-trusted-digests.txt"
    allowlist.write_text(allowlist.read_text(encoding="utf-8") + f"{digest}\n", encoding="utf-8")
    assert verify_candidate(tmp_path, tmp_path)[0] == "dfb366f323516772"


def test_trusted_check_rejects_symlinked_artifact(tmp_path: Path) -> None:
    for relative in (
        Path("skills/commit-push-pr/references/pr-self-review.md"),
        Path("docs/pr-self-review-trusted-digests.txt"),
        Path(".github/workflows/pr-self-review-trusted.yml"),
        Path("scripts/check_pr_self_review.py"),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    linked = tmp_path / "docs/pr-self-review.md"
    linked.parent.mkdir(parents=True, exist_ok=True)
    try:
        linked.symlink_to(ROOT / "docs/pr-self-review.md")
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(VerificationError, match="symlink"):
        verify_candidate(tmp_path, tmp_path)


def test_trusted_check_rejects_gate_replacement(tmp_path: Path) -> None:
    base_root = tmp_path / "base"
    candidate_root = tmp_path / "candidate"
    for relative in (
        Path("docs/pr-self-review.md"),
        Path("skills/commit-push-pr/references/pr-self-review.md"),
        Path("docs/pr-self-review-trusted-digests.txt"),
        Path(".github/workflows/pr-self-review-trusted.yml"),
        Path("scripts/check_pr_self_review.py"),
    ):
        target = base_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
        candidate = candidate_root / relative
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes((ROOT / relative).read_bytes())
    gate = candidate_root / "scripts/check_pr_self_review.py"
    gate.write_text(gate.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    with pytest.raises(VerificationError, match="protected gate"):
        verify_candidate(candidate_root, base_root)


def test_trusted_check_rejects_allowlist_replacement(tmp_path: Path) -> None:
    base_root = tmp_path / "base"
    candidate_root = tmp_path / "candidate"
    for relative in (
        Path("docs/pr-self-review.md"),
        Path("skills/commit-push-pr/references/pr-self-review.md"),
        Path("docs/pr-self-review-trusted-digests.txt"),
        Path(".github/workflows/pr-self-review-trusted.yml"),
        Path("scripts/check_pr_self_review.py"),
    ):
        base_path = base_root / relative
        base_path.parent.mkdir(parents=True, exist_ok=True)
        base_path.write_bytes((ROOT / relative).read_bytes())
        candidate_path = candidate_root / relative
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_bytes((ROOT / relative).read_bytes())
    allowlist = candidate_root / "docs/pr-self-review-trusted-digests.txt"
    allowlist.write_text(allowlist.read_text(encoding="utf-8") + "0" * 64 + "\n", encoding="utf-8")
    with pytest.raises(VerificationError, match="protected gate"):
        verify_candidate(candidate_root, base_root)
