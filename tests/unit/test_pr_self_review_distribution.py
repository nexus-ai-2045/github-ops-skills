from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_self_review_is_in_every_copy_runtime_manifest() -> None:
    manifest = yaml.safe_load(
        (ROOT / "skills/commit-push-pr/manifest.yaml").read_text(encoding="utf-8")
    )
    for runtime in ("claude", "codex", "grok"):
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
    assert "advisory" in workflow
    # fork（private含む）のrepositoryを直接checkoutせず、base repository経由で取る
    assert "refs/pull/" in workflow
    assert "head_repo" not in workflow
    assert "persist-credentials: false" in workflow
    assert "scripts/check_pr_self_review.py" in workflow
    assert "--base-root" in workflow
    assert "--candidate-root" in workflow
    adr = (ROOT / "docs/adr/0006-pr-self-review-advisory-bootstrap.md").read_text(
        encoding="utf-8"
    )
    assert "advisory" in adr
    assert "required check" in adr


def test_commit_push_skill_fails_closed_for_review_input_and_base_pair() -> None:
    skill = (ROOT / "skills/commit-push-pr/SKILL.md").read_text(encoding="utf-8")
    assert "set -Eeuo pipefail" in skill
    assert "mktemp -d" in skill
    assert "trap 'rm -rf \"$TMPIDX_DIR\"' EXIT" in skill
    assert "DIFF_BASE" in skill
    assert "LIVE_BASE" in skill
    assert "REVIEWED_TREE" in skill
    assert "INTENDED_PATHS" in skill
    assert 'git add -A -- "${INTENDED_PATHS[@]}"' in skill
    assert "required checkではない" in skill
    assert "git fetch origin <base>" in skill
    assert "FETCH_HEAD" in skill
    commit_step = skill.split("7. 承認されたら:", 1)[1]
    assert "手順 1 の `INTENDED_PATHS` と同じ path だけを `git add`" in commit_step
    # commit前に本物のindexのtreeを照合する（commit後のHEAD^{tree}照合では遅い）
    guard = 'test "$(git write-tree)" = "$REVIEWED_TREE"'
    assert guard in commit_step.split("git commit ...", 1)[0]
    # shallow clone / 初回push / hook 書き換え / shell をまたぐ状態受け渡し
    assert "--is-shallow-repository" in skill
    assert "--unshallow" in skill
    assert "unborn" in skill
    assert 'STATE="$(git rev-parse --git-dir)/pr-self-review"' in skill
    assert 'REVIEWED_TREE=$(cat "$STATE/reviewed_tree")' in commit_step
    assert "git reset --soft HEAD@{1}" in commit_step
    assert "--no-verify" in skill
