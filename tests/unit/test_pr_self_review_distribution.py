from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_self_review_is_in_every_copy_runtime_manifest() -> None:
    manifest = yaml.safe_load(
        (ROOT / "skills/commit-push-pr/manifest.yaml").read_text(encoding="utf-8")
    )
    for runtime in ("claude", "codex"):
        assert "references/pr-self-review.md" in manifest["runtimes"][runtime]["files"]


def test_packaged_checklist_matches_repository_document() -> None:
    assert (
        ROOT / "docs/pr-self-review.md"
    ).read_bytes() == (ROOT / "skills/commit-push-pr/references/pr-self-review.md").read_bytes()


def test_trusted_workflow_uses_base_only_verifier_and_read_permissions() -> None:
    workflow = (ROOT / ".github/workflows/pr-self-review-trusted.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request_target:" in workflow
    assert "edited" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pr_number:" in workflow
    assert "contents: read" in workflow
    assert "pull-requests: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "scripts/check_pr_self_review.py" in workflow
    assert "--base-root" in workflow
    assert "--candidate-root" in workflow


def test_commit_push_skill_fails_closed_for_review_input_and_base_pair() -> None:
    skill = (ROOT / "skills/commit-push-pr/SKILL.md").read_text(encoding="utf-8")
    assert "set -Eeuo pipefail" in skill
    assert "mktemp -d" in skill
    assert "trap 'rm -rf \"$TMPIDX_DIR\"' EXIT" in skill
    assert "DIFF_BASE" in skill
    assert "LIVE_BASE" in skill
    assert "REVIEWED_TREE" in skill
