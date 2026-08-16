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


def test_japanese_only_in_title_html_comment_does_not_pass() -> None:
    result = check_pr_metadata(
        "<!-- 日本語 --> Add gate",
        "## 概要\n安全な変更です。",
    )
    assert result.code == "title_not_japanese"


def test_indented_english_heading_is_blocked() -> None:
    result = check_pr_metadata(
        "日本語gateを追加",
        "## 概要\n説明は日本語です。\n\n   ## Summary\nEnglish section.",
    )
    assert result.code == "english_only_heading"


def test_setext_english_heading_is_blocked() -> None:
    result = check_pr_metadata(
        "日本語gateを追加",
        "## 概要\n説明は日本語です。\n\nSummary\n=======\nEnglish section.",
    )
    assert result.code == "english_only_heading"


def test_japanese_only_in_reference_destination_does_not_pass() -> None:
    result = check_pr_metadata(
        "日本語gateを追加",
        "English body only.\n\n[id]: https://example.com/日本語",
    )
    assert result.code == "body_not_japanese"


def test_japanese_only_in_inline_link_destination_does_not_pass() -> None:
    result = check_pr_metadata(
        "日本語gateを追加",
        "[English label](https://example.com/日本語)",
    )
    assert result.code == "body_not_japanese"


def test_japanese_inline_link_label_is_visible_and_passes() -> None:
    result = check_pr_metadata(
        "日本語gateを追加",
        "[日本語の説明](https://example.com/english)",
    )
    assert result.status.value == "READY"
