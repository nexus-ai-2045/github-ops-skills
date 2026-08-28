from __future__ import annotations

import re

from .result import Outcome, Status

Visibility = str

_STATUS_LINE = re.compile(r"^状態:\s*(.+)$", re.MULTILINE)


def parse_public_ready_visibility(text: str) -> Visibility:
    match = _STATUS_LINE.search(text)
    if match is None:
        return "UNKNOWN"
    line = match.group(1)
    # Negated / private wording first: 「非公開（公開済みではない）」 must not
    # match the positive 「公開済み」 token.
    if "PRIVATE" in line or "非公開" in line:
        return "PRIVATE"
    if "公開済み" in line:
        return "PUBLIC"
    return "UNKNOWN"


def classify_unauthenticated_http(status_code: int) -> Visibility:
    if status_code == 200:
        return "PUBLIC"
    if status_code == 404:
        return "PRIVATE"
    return "UNKNOWN"


def compare_visibility_claim(claim: Visibility, observed: Visibility) -> Outcome:
    evidence = {"claim": claim, "observed": observed}
    if claim == "UNKNOWN" or observed == "UNKNOWN":
        return Outcome(
            status=Status.UNKNOWN,
            code="visibility_claim_unknown",
            cause="PUBLIC_READYの宣言または未ログイン観測を確定できません",
            impact="公開状態の一致は保証できません",
            recovery="状態行と未ログインHTTPのstatus codeを確認してください",
            evidence=evidence,
        )
    if claim != observed:
        return Outcome(
            status=Status.BLOCKED,
            code="visibility_claim_mismatch",
            cause="PUBLIC_READYのvisibility宣言と未ログイン観測が一致しません",
            impact="文書の公開済みをliveのpublicとして扱いません",
            recovery="未ログインHTTPを正としてPUBLIC_READYを直すか、visibility操作を別承認してください",
            evidence=evidence,
        )
    return Outcome(
        status=Status.READY,
        code="visibility_claim_match",
        cause="PUBLIC_READYの宣言と未ログイン観測が一致しました",
        impact="文書のvisibility宣言をliveとして記録できます",
        recovery="none",
        evidence=evidence,
    )


def evaluate_visibility_claim(text: str, status_code: int) -> Outcome:
    claim = parse_public_ready_visibility(text)
    observed = classify_unauthenticated_http(status_code)
    outcome = compare_visibility_claim(claim, observed)
    evidence = dict(outcome.evidence)
    evidence["status_code"] = status_code
    return Outcome(
        status=outcome.status,
        code=outcome.code,
        cause=outcome.cause,
        impact=outcome.impact,
        recovery=outcome.recovery,
        evidence=evidence,
    )
