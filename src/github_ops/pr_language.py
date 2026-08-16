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
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(")


def _rendered_text(body: str) -> str:
    visible: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    for line in body.splitlines():
        if fence_char:
            if re.fullmatch(
                rf"[ \t]{{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*",
                line,
            ):
                fence_char = None
            continue
        opening = FENCE_OPEN_RE.match(line) if len(line) - len(line.lstrip(" \t")) <= 3 else None
        if opening:
            marker = opening.group(1)
            fence_char, fence_length = marker[0], len(marker)
            continue
        visible.append(line)
    return HTML_COMMENT_RE.sub("", "\n".join(visible))


def check_pr_metadata(title: str, body: str) -> Outcome:
    visible_title = _rendered_text(title)
    rendered_body = _rendered_text(body)
    atx_headings = ATX_HEADING_RE.findall(rendered_body)
    headings = atx_headings + SETEXT_HEADING_RE.findall(rendered_body)
    evidence = {
        "title_has_japanese": bool(JAPANESE_RE.search(visible_title)),
        "body_has_japanese_heading": any(
            JAPANESE_RE.search(item) for item in atx_headings
        ),
    }
    if MARKDOWN_LINK_RE.search(visible_title):
        return _blocked("title_markdown_link_not_allowed", "PR titleにMarkdown linkがあります", evidence)
    if not evidence["title_has_japanese"]:
        return _blocked(
            "title_not_japanese",
            "PR titleに日本語がありません",
            evidence,
        )
    if any(MARKDOWN_LINK_RE.search(item) for item in headings):
        return _blocked("heading_markdown_link_not_allowed", "見出しにMarkdown linkがあります", evidence)
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
    if not evidence["body_has_japanese_heading"]:
        return _blocked(
            "japanese_heading_required",
            "PR bodyに日本語の見出しがありません",
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
