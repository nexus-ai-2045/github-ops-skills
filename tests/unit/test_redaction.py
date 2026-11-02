from github_ops.redaction import redact


def test_redacts_supported_github_tokens() -> None:
    text = "GH_TOKEN=gh" + "p_" + "a" * 36
    redacted = redact(text)
    assert "gh" + "p_" not in redacted
    assert "[REDACTED]" in redacted
