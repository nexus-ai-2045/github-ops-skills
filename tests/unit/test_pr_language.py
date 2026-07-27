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
