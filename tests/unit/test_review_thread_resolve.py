from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from github_ops import review_thread_resolve as module
from github_ops.review_thread_resolve import (
    CommitFiles,
    Disposition,
    GhLookup,
    LookupFailure,
    NotFound,
    ParseError,
    ThreadComment,
    ThreadRecord,
    ThreadVerdict,
    apply_resolve,
    fetch_thread_records,
    parse_disposition,
    plan_resolve,
    run_resolve,
)
from github_ops.review_threads import AuditResult, ThreadSummary, error_result

REPO = "owner/name"
PR = 7
LOGIN = "example-user"
HEAD = "a" * 40
BASE = "b" * 40
ORIGINAL = "c" * 40
FIX = "d" * 40
PATH = "src/example.py"


def mark(payload: dict) -> str:
    return f"<!-- review-disposition: {json.dumps(payload)} -->"


def fixed_mark(commit: str = FIX) -> str:
    return mark({"v": 1, "kind": "fixed", "commit": commit})


def deferred_mark(ref: str = "owner/name#80") -> str:
    return mark({"v": 1, "kind": "deferred", "ref": ref})


def dismissed_mark() -> str:
    return mark({"v": 1, "kind": "dismissed", "reason": "仕様どおりのため"})


def _thread(*, thread_id: str, state: str, title: str = "finding") -> ThreadSummary:
    return ThreadSummary(
        id=thread_id,
        state=state,
        path=PATH,
        line=10,
        author="review-bot",
        title=title,
        commit="abc",
        original_commit="def",
    )


def _audit(
    *threads: ThreadSummary,
    head: str = HEAD,
    truncated: bool = False,
) -> AuditResult:
    unresolved_current = sum(1 for t in threads if t.state == "unresolved_current")
    unresolved_outdated = sum(1 for t in threads if t.state == "unresolved_outdated")
    resolved = sum(1 for t in threads if t.state == "resolved")
    clean = not (unresolved_current or unresolved_outdated or truncated)
    return AuditResult(
        decision="pass" if clean else "warn",
        head_ref_oid=head,
        base_ref_oid=BASE,
        resolved=resolved,
        unresolved_current=unresolved_current,
        unresolved_outdated=unresolved_outdated,
        threads=list(threads),
        errors=[],
        truncated=truncated,
    )


def _comment(author: str, body: str, *, index: int = 0) -> ThreadComment:
    return ThreadComment(
        id=f"c{index}",
        body=body,
        path=PATH,
        author=author,
        original_commit=ORIGINAL,
    )


def _record(
    *replies: tuple[str, str],
    thread_id: str = "t1",
    first_body: str = "P1 finding",
    truncated: bool = False,
) -> ThreadRecord:
    comments = [_comment("review-bot", first_body)]
    comments += [
        _comment(author, body, index=i + 1) for i, (author, body) in enumerate(replies)
    ]
    return ThreadRecord(thread_id, tuple(comments), truncated)


class FakeLookup:
    def __init__(self) -> None:
        self.compare: dict[tuple[str, str], str | Exception] = {
            (FIX, HEAD): "ahead",
            (ORIGINAL, FIX): "ahead",
            (BASE, FIX): "ahead",
        }
        self.files: dict[str, CommitFiles | Exception] = {
            FIX: CommitFiles(frozenset({PATH}), False)
        }
        self.issues: dict[int, int | Exception] = {80: 80}

    def compare_status(self, repo: str, base: str, head: str) -> str:
        outcome = self.compare.get((base, head), NotFound("404"))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def commit_files(self, repo: str, commit: str) -> CommitFiles:
        outcome = self.files.get(commit, NotFound("404"))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def issue_number(self, repo: str, number: int) -> int:
        outcome = self.issues.get(number, NotFound("404"))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _verdict(
    record: ThreadRecord,
    lookup: FakeLookup | None = None,
    *,
    login: str | None = LOGIN,
    pr_number: int = PR,
) -> ThreadVerdict:
    plan = plan_resolve(
        _audit(_thread(thread_id="t1", state="unresolved_current")),
        records={"t1": record},
        expected_login=login,
        repo=REPO,
        pr_number=pr_number,
        lookup=lookup or FakeLookup(),
    )
    (verdict,) = plan.verdicts
    return verdict


def test_unresolved_threads_are_materials_not_resolved() -> None:
    audit = _audit(
        _thread(thread_id="t1", state="unresolved_current", title="P1 finding"),
        _thread(thread_id="t2", state="resolved", title="done"),
    )
    plan = plan_resolve(audit)
    assert plan.decision == "hold"
    assert plan.resolve_thread_ids == ()
    assert [item["id"] for item in plan.materials] == ["t1"]
    assert plan.materials[0]["reason_code"] == "expected_login_missing"


def test_audit_error_fail_closed_leaves_unresolved() -> None:
    plan = plan_resolve(error_result("gh_api_timeout"))
    assert plan.decision == "error"
    assert plan.resolve_thread_ids == ()
    assert plan.materials
    assert plan.errors == ("gh_api_timeout",)


def test_truncated_audit_cannot_judge() -> None:
    audit = _audit(_thread(thread_id="t1", state="resolved"), truncated=True)
    plan = plan_resolve(audit)
    assert plan.decision == "hold"
    assert plan.resolve_thread_ids == ()
    assert any(item.get("kind") == "audit_truncated" for item in plan.materials)


def test_proposed_unresolved_id_without_record_is_not_closed() -> None:
    audit = _audit(_thread(thread_id="t1", state="unresolved_current", title="open"))
    plan = plan_resolve(audit, proposed_thread_ids=("t1",))
    assert plan.decision == "hold"
    assert plan.resolve_thread_ids == ()
    assert plan.materials[0]["id"] == "t1"


def test_proposed_unknown_thread_is_reported() -> None:
    audit = _audit(_thread(thread_id="t1", state="resolved"))
    plan = plan_resolve(audit, proposed_thread_ids=("ghost",))
    assert plan.decision == "hold"
    assert plan.errors == ("unknown_thread",)
    assert plan.materials[0]["id"] == "ghost"


def test_already_resolved_thread_needs_no_operation() -> None:
    audit = _audit(_thread(thread_id="t1", state="resolved"))
    plan = plan_resolve(audit, proposed_thread_ids=("t1",))
    assert plan.decision == "ready"
    assert plan.resolve_thread_ids == ()
    assert plan.verdicts == (ThreadVerdict("t1", "already_resolved", "already_resolved"),)


def test_apply_does_not_mutate_on_hold() -> None:
    audit = _audit(_thread(thread_id="t1", state="unresolved_current"))
    plan = plan_resolve(audit, proposed_thread_ids=("t1",))
    calls: list[str] = []

    def fake_resolve(thread_id: str) -> dict:
        calls.append(thread_id)
        return {"data": {"resolveReviewThread": {"thread": {"id": thread_id, "isResolved": True}}}}

    result = apply_resolve(plan, apply=True, resolver=fake_resolve)
    assert result["applied"] is False
    assert calls == []
    assert result["materials"]


def test_apply_ready_without_ids_is_noop_success() -> None:
    plan = plan_resolve(_audit())
    assert plan.decision == "ready"
    result = apply_resolve(plan, apply=True, resolver=lambda thread_id: {})
    assert result["applied"] is True
    assert result["resolved"] == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            fixed_mark(),
            Disposition(kind="fixed", commit=FIX, author="u", comment_id="c9"),
        ),
        (
            f"{deferred_mark()}\n#80 で直します。",
            Disposition(kind="deferred", ref="owner/name#80", author="u", comment_id="c9"),
        ),
        (
            dismissed_mark(),
            Disposition(kind="dismissed", reason="仕様どおりのため", author="u", comment_id="c9"),
        ),
    ],
)
def test_parse_disposition_accepts_three_kinds(body: str, expected: Disposition) -> None:
    assert parse_disposition(body, author="u", comment_id="c9") == expected


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("15c9851 で直しました。", "no_mark"),
        (f"{fixed_mark()}\n{dismissed_mark()}", "multiple_marks"),
        ("<!-- review-disposition: {not json} -->", "invalid_json"),
        ("<!-- review-disposition: [1] -->", "invalid_shape"),
        (mark({"v": 2, "kind": "fixed", "commit": FIX}), "invalid_version"),
        (mark({"v": True, "kind": "fixed", "commit": FIX}), "invalid_version"),
        (mark({"v": 1, "kind": "ignored", "commit": FIX}), "invalid_kind"),
        (mark({"v": 1, "kind": "fixed"}), "invalid_keys"),
        (mark({"v": 1, "kind": "fixed", "commit": FIX, "ref": "o/r#1"}), "invalid_keys"),
        (mark({"v": 1, "kind": "fixed", "ref": "o/r#1"}), "invalid_keys"),
        (mark({"v": 1, "kind": "fixed", "commit": "15c9851"}), "invalid_value"),
        (mark({"v": 1, "kind": "fixed", "commit": FIX.upper()}), "invalid_value"),
        (mark({"v": 1, "kind": "deferred", "ref": "owner/name#0"}), "invalid_value"),
        (mark({"v": 1, "kind": "deferred", "ref": "owner/name/x#3"}), "invalid_value"),
        (mark({"v": 1, "kind": "deferred", "ref": 80}), "invalid_value"),
        (mark({"v": 1, "kind": "dismissed", "reason": "  "}), "invalid_value"),
    ],
)
def test_parse_disposition_rejects_malformed_marks(body: str, code: str) -> None:
    assert parse_disposition(body) == ParseError(code)


def test_fixed_record_confirmed_by_github_is_resolvable() -> None:
    assert _verdict(_record((LOGIN, fixed_mark()))) == ThreadVerdict(
        "t1", "resolvable", "fixed_verified"
    )


def test_deferred_record_confirmed_by_github_is_resolvable() -> None:
    assert _verdict(_record((LOGIN, deferred_mark()))) == ThreadVerdict(
        "t1", "resolvable", "deferred_verified"
    )


def test_deferred_ref_owner_and_repo_match_ignores_case() -> None:
    record = _record((LOGIN, deferred_mark("Owner/Name#80")))
    assert _verdict(record).verdict == "resolvable"


def test_dismissed_record_is_left_to_a_human() -> None:
    assert _verdict(_record((LOGIN, dismissed_mark()))) == ThreadVerdict(
        "t1", "human", "dismissed"
    )


def test_thread_without_record_stays_open() -> None:
    assert _verdict(_record()).reason_code == "no_record"
    assert _verdict(_record((LOGIN, "15c9851 で直しました。"))).reason_code == "no_record"


def test_mark_in_bot_comment_is_never_read() -> None:
    record = _record(first_body=fixed_mark())
    assert _verdict(record) == ThreadVerdict("t1", "hold", "no_record")


def test_missing_expected_login_holds_everything() -> None:
    record = _record((LOGIN, fixed_mark()))
    assert _verdict(record, login=None).reason_code == "expected_login_missing"


def test_missing_thread_record_holds() -> None:
    plan = plan_resolve(
        _audit(_thread(thread_id="t1", state="unresolved_current")),
        records={},
        expected_login=LOGIN,
        repo=REPO,
        pr_number=PR,
        lookup=FakeLookup(),
    )
    assert plan.verdicts == (ThreadVerdict("t1", "hold", "record_missing"),)


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        (lambda lk: lk.compare.pop((FIX, HEAD)), "commit_not_found"),
        (lambda lk: lk.compare.update({(FIX, HEAD): "diverged"}), "commit_not_in_head"),
        (lambda lk: lk.compare.update({(FIX, HEAD): "behind"}), "commit_not_in_head"),
        (lambda lk: lk.compare.update({(ORIGINAL, FIX): "identical"}), "commit_not_after_finding"),
        (lambda lk: lk.compare.update({(ORIGINAL, FIX): "behind"}), "commit_not_after_finding"),
        (lambda lk: lk.compare.update({(BASE, FIX): "behind"}), "commit_in_base"),
        (lambda lk: lk.compare.update({(BASE, FIX): "identical"}), "commit_in_base"),
        (
            lambda lk: lk.files.update({FIX: CommitFiles(frozenset({"README.md"}), False)}),
            "commit_misses_path",
        ),
        (
            lambda lk: lk.files.update({FIX: CommitFiles(frozenset({PATH}), True)}),
            "files_truncated",
        ),
        (lambda lk: lk.files.pop(FIX), "commit_not_found"),
        (lambda lk: lk.compare.update({(FIX, HEAD): LookupFailure("500")}), "lookup_failed"),
    ],
)
def test_fixed_claim_github_cannot_confirm_stays_open(setup, code: str) -> None:
    lookup = FakeLookup()
    setup(lookup)
    verdict = _verdict(_record((LOGIN, fixed_mark())), lookup)
    assert verdict == ThreadVerdict("t1", "hold", code)


def test_fixed_claiming_the_finding_commit_itself_stays_open() -> None:
    lookup = FakeLookup()
    lookup.compare[(ORIGINAL, HEAD)] = "ahead"
    lookup.compare[(ORIGINAL, ORIGINAL)] = "identical"
    lookup.compare[(BASE, ORIGINAL)] = "ahead"
    lookup.files[ORIGINAL] = CommitFiles(frozenset({PATH}), False)
    verdict = _verdict(_record((LOGIN, fixed_mark(ORIGINAL))), lookup)
    assert verdict.reason_code == "commit_not_after_finding"


def test_fixed_claiming_an_ancestor_of_the_finding_stays_open() -> None:
    older = "e" * 40
    lookup = FakeLookup()
    lookup.compare[(older, HEAD)] = "ahead"
    lookup.compare[(ORIGINAL, older)] = "behind"
    verdict = _verdict(_record((LOGIN, fixed_mark(older))), lookup)
    assert verdict.reason_code == "commit_not_after_finding"


def test_fixed_commit_may_follow_a_base_that_moved_on() -> None:
    lookup = FakeLookup()
    lookup.compare[(BASE, FIX)] = "diverged"
    assert _verdict(_record((LOGIN, fixed_mark())), lookup).verdict == "resolvable"


def test_fixed_commit_that_renamed_the_file_counts() -> None:
    lookup = FakeLookup()
    lookup.files[FIX] = CommitFiles(frozenset({"src/new.py", PATH}), False)
    assert _verdict(_record((LOGIN, fixed_mark())), lookup).verdict == "resolvable"


@pytest.mark.parametrize(
    ("ref", "code"),
    [
        ("other/repo#80", "ref_other_repo"),
        (f"owner/name#{PR}", "ref_is_self"),
        ("owner/name#81", "ref_not_found"),
    ],
)
def test_deferred_claim_github_cannot_confirm_stays_open(ref: str, code: str) -> None:
    verdict = _verdict(_record((LOGIN, deferred_mark(ref))))
    assert verdict == ThreadVerdict("t1", "hold", code)


def test_deferred_number_must_match_response() -> None:
    lookup = FakeLookup()
    lookup.issues[80] = 79
    assert _verdict(_record((LOGIN, deferred_mark())), lookup).reason_code == "ref_mismatch"


def test_deferred_lookup_failure_holds() -> None:
    lookup = FakeLookup()
    lookup.issues[80] = LookupFailure("timeout")
    assert _verdict(_record((LOGIN, deferred_mark())), lookup).reason_code == "lookup_failed"


def test_record_by_unexpected_author_stays_open() -> None:
    record = _record(("someone-else", fixed_mark()))
    assert _verdict(record).reason_code == "author_mismatch"


def test_author_match_ignores_case() -> None:
    record = _record((LOGIN.upper(), fixed_mark()))
    assert _verdict(record).verdict == "resolvable"


def test_new_comment_by_another_author_after_record_stays_open() -> None:
    record = _record((LOGIN, fixed_mark()), ("review-bot", "まだ直っていません"))
    assert _verdict(record).reason_code == "later_comment_by_other"


def test_later_unmarked_reply_by_same_author_keeps_record() -> None:
    record = _record((LOGIN, fixed_mark()), (LOGIN, "補足です"))
    assert _verdict(record).verdict == "resolvable"


def test_latest_record_replaces_an_earlier_one() -> None:
    record = _record((LOGIN, dismissed_mark()), (LOGIN, fixed_mark()))
    assert _verdict(record).verdict == "resolvable"


def test_malformed_or_double_mark_stays_open() -> None:
    assert _verdict(_record((LOGIN, "<!-- review-disposition: {x} -->"))).reason_code == "invalid_json"
    both = f"{fixed_mark()}\n{deferred_mark()}"
    assert _verdict(_record((LOGIN, both))).reason_code == "multiple_marks"


def test_truncated_comment_page_stays_open() -> None:
    record = _record((LOGIN, fixed_mark()), truncated=True)
    assert _verdict(record).reason_code == "comments_truncated"


def test_lookup_missing_never_closes_a_claim() -> None:
    plan = plan_resolve(
        _audit(_thread(thread_id="t1", state="unresolved_current")),
        records={"t1": _record((LOGIN, fixed_mark()))},
        expected_login=LOGIN,
        repo=REPO,
        pr_number=PR,
    )
    assert plan.verdicts == (ThreadVerdict("t1", "hold", "lookup_unavailable"),)


def test_proposed_filter_keeps_other_resolvable_threads_open() -> None:
    audit = _audit(
        _thread(thread_id="t1", state="unresolved_current"),
        _thread(thread_id="t2", state="unresolved_current"),
    )
    records = {
        "t1": _record((LOGIN, fixed_mark()), thread_id="t1"),
        "t2": _record((LOGIN, fixed_mark()), thread_id="t2"),
    }
    plan = plan_resolve(
        audit,
        records=records,
        expected_login=LOGIN,
        repo=REPO,
        pr_number=PR,
        lookup=FakeLookup(),
        proposed_thread_ids=("t1",),
    )
    assert plan.resolve_thread_ids == ("t1",)
    assert [m["id"] for m in plan.materials] == ["t2"]
    assert plan.materials[0]["reason_code"] == "not_proposed"


def _confirm(thread_id: str) -> dict:
    return {"data": {"resolveReviewThread": {"thread": {"id": thread_id, "isResolved": True}}}}


def _run(
    audits: list[AuditResult],
    records: dict[str, ThreadRecord],
    *,
    lookup: FakeLookup | None = None,
    resolver=None,
    apply: bool = True,
    login: str | None = LOGIN,
    records_source=None,
) -> dict:
    queue = list(audits)

    def audit_source(repo: str, number: int) -> AuditResult:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return run_resolve(
        REPO,
        PR,
        apply=apply,
        resolver=resolver,
        expected_login=login,
        lookup=lookup or FakeLookup(),
        records_source=records_source or (lambda repo, number: records),
        audit_source=audit_source,
    )


def test_run_resolve_closes_only_verified_threads_and_reports_the_rest() -> None:
    audit = _audit(
        _thread(thread_id="t1", state="unresolved_current"),
        _thread(thread_id="t2", state="unresolved_current"),
        _thread(thread_id="t3", state="resolved"),
    )
    records = {
        "t1": _record((LOGIN, fixed_mark()), thread_id="t1"),
        "t2": _record(thread_id="t2"),
    }
    closed: list[str] = []

    def resolver(thread_id: str) -> dict:
        closed.append(thread_id)
        return _confirm(thread_id)

    result = _run([audit], records, resolver=resolver)
    assert closed == ["t1"]
    assert result["decision"] == "hold"
    assert result["applied"] is True
    assert [item["id"] for item in result["resolved"]] == ["t1"]
    assert [item["id"] for item in result["materials"]] == ["t2"]


def test_run_resolve_is_ready_when_every_open_thread_is_closed() -> None:
    audit = _audit(
        _thread(thread_id="t1", state="unresolved_current"),
        _thread(thread_id="t2", state="unresolved_outdated"),
    )
    records = {
        "t1": _record((LOGIN, fixed_mark()), thread_id="t1"),
        "t2": _record((LOGIN, deferred_mark()), thread_id="t2"),
    }
    result = _run([audit], records, resolver=_confirm)
    assert result["decision"] == "ready"
    assert result["materials"] == []
    assert [item["id"] for item in result["resolved"]] == ["t1", "t2"]


def test_run_resolve_dry_run_never_calls_resolver() -> None:
    audit = _audit(_thread(thread_id="t1", state="unresolved_current"))
    records = {"t1": _record((LOGIN, fixed_mark()))}
    calls: list[str] = []
    result = _run(
        [audit],
        records,
        apply=False,
        resolver=lambda thread_id: calls.append(thread_id) or _confirm(thread_id),
    )
    assert calls == []
    assert result["decision"] == "hold"
    assert result["applied"] is False
    assert result["verdicts"][0]["verdict"] == "resolvable"


def test_run_resolve_stops_when_head_moved_before_the_write() -> None:
    before = _audit(_thread(thread_id="t1", state="unresolved_current"))
    after = _audit(_thread(thread_id="t1", state="unresolved_current"), head="e" * 40)
    calls: list[str] = []
    result = _run(
        [before, after],
        {"t1": _record((LOGIN, fixed_mark()))},
        resolver=lambda thread_id: calls.append(thread_id) or _confirm(thread_id),
    )
    assert calls == []
    assert result["decision"] == "error"
    assert result["applied"] is False
    assert "stale_audit:head_changed" in result["errors"]


def test_run_resolve_stops_when_thread_was_closed_meanwhile() -> None:
    before = _audit(_thread(thread_id="t1", state="unresolved_current"))
    after = _audit(_thread(thread_id="t1", state="resolved"))
    calls: list[str] = []
    result = _run(
        [before, after],
        {"t1": _record((LOGIN, fixed_mark()))},
        resolver=lambda thread_id: calls.append(thread_id) or _confirm(thread_id),
    )
    assert calls == []
    assert "stale_audit:thread_no_longer_unresolved" in result["errors"]


def test_run_resolve_stops_when_recheck_fails() -> None:
    before = _audit(_thread(thread_id="t1", state="unresolved_current"))
    result = _run(
        [before, error_result("gh_api_timeout")],
        {"t1": _record((LOGIN, fixed_mark()))},
        resolver=_confirm,
    )
    assert result["applied"] is False
    assert "stale_audit:recheck_failed" in result["errors"]


def test_run_resolve_without_expected_login_never_closes() -> None:
    audit = _audit(_thread(thread_id="t1", state="unresolved_current"))
    result = _run(
        [audit],
        {"t1": _record((LOGIN, fixed_mark()))},
        resolver=_confirm,
        login=None,
    )
    assert result["resolved"] == []
    assert result["materials"][0]["reason_code"] == "expected_login_missing"


def test_run_resolve_records_fetch_failure_holds_everything() -> None:
    audit = _audit(_thread(thread_id="t1", state="unresolved_current"))

    def broken(repo: str, number: int) -> dict:
        raise ValueError("GitHub GraphQL returned errors")

    result = _run([audit], {}, resolver=_confirm, records_source=broken)
    assert result["decision"] == "hold"
    assert result["resolved"] == []
    assert any(err.startswith("records_fetch_failed") for err in result["errors"])


def test_run_resolve_keeps_partial_progress_when_a_mutation_fails() -> None:
    audit = _audit(
        _thread(thread_id="t1", state="unresolved_current"),
        _thread(thread_id="t2", state="unresolved_current"),
    )
    records = {
        "t1": _record((LOGIN, fixed_mark()), thread_id="t1"),
        "t2": _record((LOGIN, fixed_mark()), thread_id="t2"),
    }

    def resolver(thread_id: str) -> dict:
        if thread_id == "t2":
            return {"data": {"resolveReviewThread": {"thread": {"id": "other", "isResolved": True}}}}
        return _confirm(thread_id)

    result = _run([audit], records, resolver=resolver)
    assert result["decision"] == "error"
    assert result["applied"] is True
    assert [item["id"] for item in result["resolved"]] == ["t1"]
    assert any("resolve_apply_failed" in err for err in result["errors"])


def test_run_resolve_converts_audit_failure_to_error(monkeypatch) -> None:
    def broken(repo: str, number: int) -> dict:
        raise subprocess.TimeoutExpired("gh", 30)

    monkeypatch.setattr(module, "fetch", broken)
    result = run_resolve(REPO, PR, expected_login=LOGIN, apply=True, resolver=_confirm)
    assert result["decision"] == "error"
    assert result["resolved"] == []


def _completed(stdout: str) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, stderr="", returncode=0)


def _record_page(
    nodes: list[dict], *, has_next: bool = False, cursor: str | None = None
) -> str:
    return json.dumps(
        {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                            "nodes": nodes,
                        }
                    }
                }
            }
        }
    )


def _record_node(thread_id: str, *, comments_next: bool = False) -> dict:
    return {
        "id": thread_id,
        "comments": {
            "pageInfo": {"hasNextPage": comments_next},
            "nodes": [
                {
                    "id": f"{thread_id}-0",
                    "body": "P1 finding",
                    "path": PATH,
                    "author": {"login": "review-bot"},
                    "originalCommit": {"oid": ORIGINAL},
                },
                {
                    "id": f"{thread_id}-1",
                    "body": fixed_mark(),
                    "path": PATH,
                    "author": None,
                    "originalCommit": None,
                },
            ],
        },
    }


def test_fetch_thread_records_follows_pages_and_marks_truncated_comments(monkeypatch) -> None:
    pages = [
        _record_page([_record_node("t1")], has_next=True, cursor="c1"),
        _record_page([_record_node("t2", comments_next=True)]),
    ]
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return _completed(pages[len(commands) - 1])

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    records = fetch_thread_records(REPO, PR)
    assert set(records) == {"t1", "t2"}
    assert records["t1"].comments_truncated is False
    assert records["t2"].comments_truncated is True
    assert records["t1"].comments[0].original_commit == ORIGINAL
    assert records["t1"].comments[1].author == ""
    assert "cursor=c1" in commands[1]
    assert commands[0][:4] == ["gh", "api", "--hostname", "github.com"]


def test_fetch_thread_records_stops_when_cursor_does_not_advance(monkeypatch) -> None:
    page = _record_page([_record_node("t1")], has_next=True, cursor="same")
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kw: _completed(page))
    with pytest.raises(ValueError, match="did not advance"):
        fetch_thread_records(REPO, PR)


def _gh_failure(stderr: str):
    def fake_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr=stderr)

    return fake_run


def test_gh_lookup_maps_404_to_not_found(monkeypatch) -> None:
    monkeypatch.setattr(module.subprocess, "run", _gh_failure("gh: Not Found (HTTP 404)"))
    with pytest.raises(NotFound):
        GhLookup().compare_status(REPO, FIX, HEAD)


def test_gh_lookup_maps_other_failures_to_lookup_failure(monkeypatch) -> None:
    monkeypatch.setattr(module.subprocess, "run", _gh_failure("gh: Server Error (HTTP 502)"))
    with pytest.raises(LookupFailure) as excinfo:
        GhLookup().issue_number(REPO, 80)
    assert not isinstance(excinfo.value, NotFound)


def test_gh_lookup_rejects_non_oid_before_calling_api(monkeypatch) -> None:
    def forbidden(command, **kwargs):
        raise AssertionError("gh must not be called")

    monkeypatch.setattr(module.subprocess, "run", forbidden)
    with pytest.raises(LookupFailure):
        GhLookup().compare_status(REPO, "main", HEAD)
    with pytest.raises(LookupFailure):
        GhLookup().commit_files(REPO, "../x")


def test_gh_lookup_commit_files_uses_new_and_previous_names(monkeypatch) -> None:
    body = json.dumps(
        {"files": [{"filename": "src/new.py", "previous_filename": PATH}, {"filename": "a"}]}
    )
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kw: _completed(body))
    files = GhLookup().commit_files(REPO, FIX)
    assert files == CommitFiles(frozenset({"src/new.py", PATH, "a"}), False)


def test_gh_lookup_commit_files_at_limit_is_truncated(monkeypatch) -> None:
    body = json.dumps({"files": [{"filename": f"f{i}"} for i in range(300)]})
    monkeypatch.setattr(module.subprocess, "run", lambda command, **kw: _completed(body))
    assert GhLookup().commit_files(REPO, FIX).truncated is True


def test_gh_lookup_compare_status_and_issue_number(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_run(command, **kwargs):
        seen.append(command)
        return _completed("ahead\n" if "compare" in command[4] else "80\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert GhLookup().compare_status(REPO, FIX, HEAD) == "ahead"
    assert GhLookup().issue_number(REPO, 80) == 80
    assert seen[0][4] == f"repos/{REPO}/compare/{FIX}...{HEAD}"
    assert seen[1][4] == f"repos/{REPO}/issues/80"


def test_run_resolve_stops_when_a_new_finding_arrives_before_closing() -> None:
    audit = _audit(_thread(thread_id="t1", state="unresolved_current"))
    snapshots = [
        {"t1": _record((LOGIN, fixed_mark()))},
        {"t1": _record((LOGIN, fixed_mark()), ("review-bot", "still broken"))},
    ]
    closed: list[str] = []

    def resolver(thread_id: str) -> dict:
        closed.append(thread_id)
        return _confirm(thread_id)

    result = _run(
        [audit],
        {},
        resolver=resolver,
        records_source=lambda repo, number: snapshots.pop(0),
    )
    assert closed == []
    assert result["applied"] is False
    assert "stale_audit:verdict_changed" in result["errors"]


def test_run_resolve_stops_when_records_recheck_fails() -> None:
    audit = _audit(_thread(thread_id="t1", state="unresolved_current"))
    calls: list[int] = []

    def records_source(repo: str, number: int) -> dict:
        calls.append(number)
        if len(calls) > 1:
            raise ValueError("GitHub GraphQL returned errors")
        return {"t1": _record((LOGIN, fixed_mark()))}

    result = _run([audit], {}, resolver=_confirm, records_source=records_source)
    assert result["applied"] is False
    assert "stale_audit:recheck_failed" in result["errors"]
