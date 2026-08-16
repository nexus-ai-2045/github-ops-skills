from __future__ import annotations

import re

from .result import Outcome, Status


JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
ATX_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)\s*$", re.MULTILINE)
SETEXT_HEADING_RE = re.compile(
    r"^[ \t]{0,3}(.+?)\s*\n[ \t]{0,3}(?:=+|-+)\s*$", re.MULTILINE
)
FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
REFERENCE_DEFINITION_RE = re.compile(r"^[ \t]{0,3}\[[^\]]+\]:\s*\S+.*$", re.MULTILINE)
INLINE_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^\n)]*\)")


def _rendered_text(body: str) -> str:
    visible: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    for line in body.splitlines():
        if fence_char:
            if re.fullmatch(rf"\s*{re.escape(fence_char)}{{{fence_length},}}\s*", line):
                fence_char = None
            continue
        opening = FENCE_OPEN_RE.match(line)
        if opening:
            marker = opening.group(1)
            fence_char, fence_length = marker[0], len(marker)
            continue
        visible.append(line)
    rendered = HTML_COMMENT_RE.sub("", "\n".join(visible))
    rendered = REFERENCE_DEFINITION_RE.sub("", rendered)
    return INLINE_LINK_RE.sub(r"\1", rendered)


def check_pr_metadata(title: str, body: str) -> Outcome:
    visible_title = HTML_COMMENT_RE.sub("", title)
    rendered_body = _rendered_text(body)
    evidence = {
        "title_has_japanese": bool(JAPANESE_RE.search(visible_title)),
        "body_has_japanese": bool(JAPANESE_RE.search(rendered_body)),
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
    headings = ATX_HEADING_RE.findall(rendered_body) + SETEXT_HEADING_RE.findall(
        rendered_body
    )
    english_only = [
        heading
        for heading in headings
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
