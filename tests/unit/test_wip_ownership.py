from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from github_ops.wip_ownership import evaluate_changes as _evaluate_changes


NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
DIFF_SHA256 = "a" * 64


def evaluate_changes(
    entries: list[dict[str, object]],
    changed_paths: list[Path],
    *,
    now: datetime,
    repository: str | Path | None = None,
):
    evidence = {
        str(path): {"diff_sha256": DIFF_SHA256, "secret_scan": "clear"}
        for path in changed_paths
    }
    return _evaluate_changes(
        entries,
        changed_paths,
        now=now,
        repository=repository,
        recorded_at=NOW,
        recorded_by="codex-task-123",
        evidence_by_path=evidence,
    )


def _entry(root: Path, **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "repository": str(root),
        "path": str(root / "runtime"),
        "match_mode": "prefix",
        "owner": "task-123",
        "scope": "runtime configuration",
        "reason": "parallel task owns this WIP",
        "dependency": "independent",
        "classification": "warn",
        "secret_risk": "clear",
        "known_generated": False,
        "diff_sha256": DIFF_SHA256,
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "return_path": "tasks/task-123.md",
    }
    entry.update(overrides)
    return entry


def test_active_independent_owned_wip_is_warn(tmp_path: Path) -> None:
    changed = tmp_path / "runtime" / "settings.json"

    result = evaluate_changes([_entry(tmp_path)], [changed], now=NOW)

    assert result[0].classification == "warn"
    assert result[0].owner == "task-123"


def test_known_generated_entry_is_allow(tmp_path: Path) -> None:
    entry = _entry(tmp_path, classification="allow", known_generated=True)

    result = evaluate_changes([entry], [tmp_path / "runtime" / "cache.json"], now=NOW)

    assert result[0].classification == "allow"


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        ({"owner": "unknown"}, "owner_unknown"),
        ({"expires_at": (NOW - timedelta(seconds=1)).isoformat()}, "ownership_expired"),
        ({"secret_risk": "suspected"}, "secret_risk"),
        ({"secret_risk": "unknown"}, "secret_risk"),
        ({"dependency": "target"}, "dependency_not_independent"),
        ({"dependency": "unknown"}, "dependency_not_independent"),
        ({"classification": "block"}, "registry_block"),
        (
            {"classification": "allow", "known_generated": False},
            "allow_requires_known_generated",
        ),
    ],
)
def test_unsafe_or_unowned_entries_block(
    tmp_path: Path, overrides: dict[str, object], reason_code: str
) -> None:
    result = evaluate_changes(
        [_entry(tmp_path, **overrides)],
        [tmp_path / "runtime" / "settings.json"],
        now=NOW,
    )

    assert result[0].classification == "block"
    assert result[0].reason_code == reason_code


def test_prefix_matching_respects_path_component_boundaries(tmp_path: Path) -> None:
    result = evaluate_changes(
        [_entry(tmp_path)],
        [tmp_path / "runtime-copy" / "settings.json"],
        now=NOW,
    )

    assert result[0].classification == "block"
    assert result[0].reason_code == "ownership_missing"


def test_overlapping_prefix_entries_are_ambiguous_and_block(tmp_path: Path) -> None:
    entries = [
        _entry(tmp_path),
        _entry(tmp_path, path=str(tmp_path / "runtime" / "nested"), owner="task-456"),
    ]

    result = evaluate_changes(
        entries,
        [tmp_path / "runtime" / "nested" / "state.json"],
        now=NOW,
    )

    assert result[0].classification == "block"
    assert result[0].reason_code == "ownership_ambiguous"


def test_exact_entry_does_not_match_descendants(tmp_path: Path) -> None:
    entry = _entry(
        tmp_path, path=str(tmp_path / "runtime" / "settings.json"), match_mode="exact"
    )

    exact = evaluate_changes([entry], [tmp_path / "runtime" / "settings.json"], now=NOW)
    descendant = evaluate_changes(
        [entry], [tmp_path / "runtime" / "settings.json" / "child"], now=NOW
    )

    assert exact[0].classification == "warn"
    assert descendant[0].reason_code == "ownership_missing"


def test_naive_expiry_is_rejected_fail_closed(tmp_path: Path) -> None:
    entry = _entry(tmp_path, expires_at="2026-07-31T13:00:00")

    result = evaluate_changes(
        [entry], [tmp_path / "runtime" / "settings.json"], now=NOW
    )

    assert result[0].classification == "block"
    assert result[0].reason_code == "invalid_expiry"


def test_stable_repository_id_requires_explicit_matching_context(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path, repository="github-repository-id:12345")
    changed = tmp_path / "runtime" / "settings.json"

    matching = evaluate_changes(
        [entry], [changed], now=NOW, repository="github-repository-id:12345"
    )
    mismatched = evaluate_changes(
        [entry], [changed], now=NOW, repository="github-repository-id:99999"
    )

    assert matching[0].classification == "warn"
    assert mismatched[0].reason_code == "ownership_missing"


@pytest.mark.parametrize("field", ["repository", "path"])
@pytest.mark.parametrize("invalid_value", [None, 123, ""])
def test_malformed_repository_or_path_never_matches(
    tmp_path: Path, field: str, invalid_value: object
) -> None:
    entry = _entry(tmp_path, **{field: invalid_value})
    repository = "None" if field == "repository" and invalid_value is None else None

    result = evaluate_changes(
        [entry],
        [tmp_path / "runtime" / "settings.json"],
        now=NOW,
        repository=repository,
    )

    assert result[0].classification == "block"
    assert result[0].reason_code == "ownership_missing"


def test_now_must_be_timezone_aware(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_changes(
            [_entry(tmp_path)],
            [tmp_path / "runtime" / "settings.json"],
            now=datetime(2026, 7, 31, 12, 0),
        )


def test_measured_evidence_is_required_and_bound_to_diff(tmp_path: Path) -> None:
    changed = tmp_path / "runtime" / "settings.json"
    entry = _entry(tmp_path)

    missing = _evaluate_changes(
        [entry],
        [changed],
        now=NOW,
        recorded_at=NOW,
        recorded_by="codex-task-123",
        evidence_by_path={},
    )
    mismatch = _evaluate_changes(
        [entry],
        [changed],
        now=NOW,
        recorded_at=NOW,
        recorded_by="codex-task-123",
        evidence_by_path={
            str(changed): {"diff_sha256": "b" * 64, "secret_scan": "clear"}
        },
    )

    assert missing[0].reason_code == "measured_evidence_missing"
    assert mismatch[0].reason_code == "diff_fingerprint_mismatch"


@pytest.mark.parametrize("secret_scan", ["suspected", "unknown", None])
def test_measured_secret_scan_must_be_clear(
    tmp_path: Path, secret_scan: object
) -> None:
    changed = tmp_path / "runtime" / "settings.json"
    result = _evaluate_changes(
        [_entry(tmp_path)],
        [changed],
        now=NOW,
        recorded_at=NOW,
        recorded_by="codex-task-123",
        evidence_by_path={
            str(changed): {"diff_sha256": DIFF_SHA256, "secret_scan": secret_scan}
        },
    )

    assert result[0].reason_code == "measured_secret_scan_not_clear"


def test_lease_cannot_exceed_24_hours_from_recorded_at(tmp_path: Path) -> None:
    changed = tmp_path / "runtime" / "settings.json"
    entry = _entry(
        tmp_path, expires_at=(NOW + timedelta(hours=24, seconds=1)).isoformat()
    )

    result = _evaluate_changes(
        [entry],
        [changed],
        now=NOW,
        recorded_at=NOW,
        recorded_by="codex-task-123",
        evidence_by_path={
            str(changed): {"diff_sha256": DIFF_SHA256, "secret_scan": "clear"}
        },
    )

    assert result[0].reason_code == "lease_exceeds_24h"


@pytest.mark.parametrize("recorded_by", ["", "  ", None, 123])
def test_invalid_recorded_by_blocks(tmp_path: Path, recorded_by: object) -> None:
    changed = tmp_path / "runtime" / "settings.json"
    result = _evaluate_changes(
        [_entry(tmp_path)],
        [changed],
        now=NOW,
        recorded_at=NOW,
        recorded_by=recorded_by,
        evidence_by_path={
            str(changed): {"diff_sha256": DIFF_SHA256, "secret_scan": "clear"}
        },
    )

    assert result[0].reason_code == "invalid_registry_metadata"


def test_future_recorded_at_cannot_extend_lease(tmp_path: Path) -> None:
    changed = tmp_path / "runtime" / "settings.json"
    result = _evaluate_changes(
        [_entry(tmp_path)],
        [changed],
        now=NOW,
        recorded_at=NOW + timedelta(hours=1),
        recorded_by="codex-task-123",
        evidence_by_path={
            str(changed): {"diff_sha256": DIFF_SHA256, "secret_scan": "clear"}
        },
    )

    assert result[0].reason_code == "invalid_registry_metadata"


@pytest.mark.parametrize("field", ["scope", "reason", "return_path"])
def test_required_explanatory_fields_are_checked_by_core(
    tmp_path: Path, field: str
) -> None:
    result = evaluate_changes(
        [_entry(tmp_path, **{field: "  "})],
        [tmp_path / "runtime" / "settings.json"],
        now=NOW,
    )

    assert result[0].reason_code == "invalid_registry_entry"


def test_registry_schema_accepts_complete_entry_and_rejects_naive_expiry(
    tmp_path: Path,
) -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "schemas"
        / "wip-ownership-registry.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    registry = {
        "schema_version": "wip-ownership/v1",
        "recorded_at": NOW.isoformat(),
        "recorded_by": "codex-task-123",
        "entries": [_entry(tmp_path)],
    }

    assert list(validator.iter_errors(registry)) == []

    registry["entries"][0]["expires_at"] = "2026-07-31T13:00:00"
    assert list(validator.iter_errors(registry))
