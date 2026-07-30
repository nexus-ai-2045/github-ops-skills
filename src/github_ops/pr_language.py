from __future__ import annotations

import re

from .result import Outcome, Status


JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def check_pr_metadata(title: str, body: str) -> Outcome:
    evidence = {
        "title_has_japanese": bool(JAPANESE_RE.search(title)),
        "body_has_japanese": bool(JAPANESE_RE.search(body)),
    }
    if not evidence["title_has_japanese"]:
        return _blocked(
            "title_not_japanese",
            "PR titleに日本語がありません",
            evidence,
        )
    if not evidence["body_has_japanese"]:
        return _blocked(
            "body_not_japanese",
            "PR bodyに日本語がありません",
            evidence,
        )
    english_only = [
        heading
        for heading in HEADING_RE.findall(body)
        if re.search(r"[A-Za-z]", heading) and not JAPANESE_RE.search(heading)
    ]
    if english_only:
        evidence["english_only_heading_count"] = len(english_only)
        return _blocked(
            "english_only_heading",
            "英語だけの見出しがあります",
            evidence,
        )
    return Outcome(
        status=Status.READY,
        code="pr_metadata_ready",
        cause="PR titleとbodyの日本語境界を確認しました",
        impact="次のPR preflightへ進めます",
        recovery="none",
        evidence=evidence,
    )


def _blocked(code: str, cause: str, evidence: dict) -> Outcome:
    return Outcome(
        status=Status.BLOCKED,
        code=code,
        cause=cause,
        impact="PR作成へ進めません",
        recovery="ユーザー向け見出しと説明を日本語へ修正してください",
        evidence=evidence,
    )
