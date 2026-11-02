from __future__ import annotations

import re


TOKEN_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)(Authorization:\s*Bearer\s+)\S+"),
    re.compile(r"(?i)(GH_TOKEN\s*=\s*)\S+"),
)


def redact(text: str) -> str:
    result = text
    for pattern in TOKEN_PATTERNS:
        result = pattern.sub(_replacement, result)
    return result


def _replacement(match: re.Match[str]) -> str:
    prefix = match.group(1) if match.lastindex else ""
    return f"{prefix}[REDACTED]"
