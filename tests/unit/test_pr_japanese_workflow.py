from pathlib import Path


def test_workflow_is_metadata_only_and_read_only() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github" / "workflows" / "pr-japanese-gate.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request:" in workflow
    assert "contents: read" in workflow
    assert "GITHUB_EVENT_PATH" in workflow
    assert "rendered_body = rendered_text(body)" in workflow
    assert "html_comments" in workflow
    assert "markdown_links" in workflow
    assert "日本語の見出しがありません" in workflow
    assert "visible_title = rendered_text(title)" in workflow
    assert "`{3,}|~{3,}" in workflow
    assert "actions/checkout" not in workflow
    assert "pull_request_target" not in workflow
    assert "write" not in workflow
    assert "secrets." not in workflow
