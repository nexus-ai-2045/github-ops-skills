from github_ops.pr_language import check_pr_metadata


def test_japanese_pr_metadata_passes() -> None:
    result = check_pr_metadata("認証境界を追加", "## 概要\n誤account操作を停止します。")
    assert result.status.value == "READY"


def test_english_only_heading_is_blocked() -> None:
    result = check_pr_metadata("認証境界を追加", "## Summary\n誤操作を停止します。")
    assert result.code == "english_only_heading"


def test_english_only_title_is_blocked() -> None:
    result = check_pr_metadata("Add safety gate", "## 概要\n誤操作を停止します。")
    assert result.code == "title_not_japanese"


def test_english_heading_inside_fenced_example_is_ignored() -> None:
    result = check_pr_metadata(
        "日本語gateを追加",
        "## 概要\n使用例です。\n\n```markdown\n## Summary\nexample\n```",
    )
    assert result.status.value == "READY"


def test_english_heading_inside_long_fence_is_ignored() -> None:
    result = check_pr_metadata(
        "日本語gateを追加",
        "## 概要\n使用例です。\n\n````markdown\n## Summary\nexample\n````",
    )
    assert result.status.value == "READY"


def test_japanese_only_in_html_comment_does_not_pass() -> None:
    result = check_pr_metadata(
        "日本語gateを追加",
        "<!-- 本文は日本語で書いてください -->\nEnglish body only.",
    )
    assert result.code == "body_not_japanese"
