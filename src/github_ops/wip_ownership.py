from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class OwnershipDecision:
    path: str
    classification: str
    reason_code: str
    owner: str | None = None


def _normalized(path: str | Path) -> Path:
    return Path(os.path.normcase(os.path.abspath(os.fspath(path))))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _matches(
    entry: Mapping[str, object],
    changed_path: Path,
    repository_context: str | Path | None,
) -> bool:
    repository_raw = entry.get("repository")
    path_raw = entry.get("path")
    if not isinstance(repository_raw, str) or not repository_raw.strip():
        return False
    if not isinstance(path_raw, str) or not path_raw.strip():
        return False
    try:
        repository_value = repository_raw
        owned_path = _normalized(path_raw)
    except (TypeError, ValueError):
        return False
    if Path(repository_value).is_absolute():
        repository = _normalized(repository_value)
        if not _is_within(owned_path, repository) or not _is_within(
            changed_path, repository
        ):
            return False
    elif repository_context is None or os.path.normcase(
        str(repository_context)
    ) != os.path.normcase(repository_value):
        return False
    mode = entry.get("match_mode", "exact")
    if mode == "exact":
        return changed_path == owned_path
    if mode == "prefix":
        return _is_within(changed_path, owned_path)
    return False


def _parse_expiry(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _evaluate_entry(
    entry: Mapping[str, object],
    changed_path: Path,
    now: datetime,
    recorded_at: datetime,
    evidence: Mapping[str, object] | None,
) -> OwnershipDecision:
    owner_value = entry.get("owner")
    owner = owner_value.strip() if isinstance(owner_value, str) else ""
    if not owner or owner.lower() == "unknown":
        return OwnershipDecision(str(changed_path), "block", "owner_unknown")

    if any(
        not isinstance(entry.get(field), str) or not str(entry[field]).strip()
        for field in ("scope", "reason", "return_path")
    ):
        return OwnershipDecision(
            str(changed_path), "block", "invalid_registry_entry", owner
        )

    expected_fingerprint = entry.get("diff_sha256")
    if not isinstance(expected_fingerprint, str) or not SHA256_RE.fullmatch(
        expected_fingerprint
    ):
        return OwnershipDecision(
            str(changed_path), "block", "invalid_registry_entry", owner
        )

    expiry = _parse_expiry(entry.get("expires_at"))
    if expiry is None:
        return OwnershipDecision(str(changed_path), "block", "invalid_expiry", owner)
    if expiry <= now:
        return OwnershipDecision(str(changed_path), "block", "ownership_expired", owner)
    if expiry > recorded_at + timedelta(hours=24):
        return OwnershipDecision(str(changed_path), "block", "lease_exceeds_24h", owner)

    if evidence is None:
        return OwnershipDecision(
            str(changed_path), "block", "measured_evidence_missing", owner
        )
    measured_fingerprint = evidence.get("diff_sha256")
    if measured_fingerprint != expected_fingerprint:
        return OwnershipDecision(
            str(changed_path), "block", "diff_fingerprint_mismatch", owner
        )
    if evidence.get("secret_scan") != "clear":
        return OwnershipDecision(
            str(changed_path), "block", "measured_secret_scan_not_clear", owner
        )

    if entry.get("secret_risk") != "clear":
        return OwnershipDecision(str(changed_path), "block", "secret_risk", owner)
    if entry.get("dependency") != "independent":
        return OwnershipDecision(
            str(changed_path), "block", "dependency_not_independent", owner
        )

    classification = entry.get("classification")
    if classification == "block":
        return OwnershipDecision(str(changed_path), "block", "registry_block", owner)
    if classification == "allow":
        if entry.get("known_generated") is not True:
            return OwnershipDecision(
                str(changed_path), "block", "allow_requires_known_generated", owner
            )
        return OwnershipDecision(str(changed_path), "allow", "known_generated", owner)
    if classification == "warn":
        return OwnershipDecision(
            str(changed_path), "warn", "active_independent_owner", owner
        )
    return OwnershipDecision(
        str(changed_path), "block", "invalid_classification", owner
    )


def evaluate_changes(
    entries: Sequence[Mapping[str, object]],
    changed_paths: Iterable[str | Path],
    *,
    now: datetime,
    repository: str | Path | None = None,
    recorded_at: datetime,
    recorded_by: object,
    evidence_by_path: Mapping[str, Mapping[str, object]],
) -> list[OwnershipDecision]:
    """Classify changed paths without allowing ambiguous ownership to pass."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    registry_metadata_valid = (
        isinstance(recorded_by, str)
        and bool(recorded_by.strip())
        and recorded_at <= now
    )
    normalized_evidence = {
        _normalized(path): evidence for path, evidence in evidence_by_path.items()
    }

    decisions: list[OwnershipDecision] = []
    for raw_path in changed_paths:
        changed_path = _normalized(raw_path)
        if not registry_metadata_valid:
            decisions.append(
                OwnershipDecision(
                    str(changed_path), "block", "invalid_registry_metadata"
                )
            )
            continue
        matches = [
            entry for entry in entries if _matches(entry, changed_path, repository)
        ]
        if not matches:
            decisions.append(
                OwnershipDecision(str(changed_path), "block", "ownership_missing")
            )
        elif len(matches) > 1:
            decisions.append(
                OwnershipDecision(str(changed_path), "block", "ownership_ambiguous")
            )
        else:
            decisions.append(
                _evaluate_entry(
                    matches[0],
                    changed_path,
                    now,
                    recorded_at,
                    normalized_evidence.get(changed_path),
                )
            )
    return decisions
