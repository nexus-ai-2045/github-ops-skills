from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "github-ops/private-canary-approval/v1"


class ApprovalError(ValueError):
    pass


def _canonical(payload: Mapping[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_approval(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    if len(key.encode("utf-8")) < 32:
        raise ApprovalError("approval key must be at least 32 bytes")
    signed = dict(payload)
    signed["signature"] = hmac.new(
        key.encode("utf-8"), _canonical(payload), hashlib.sha256
    ).hexdigest()
    return signed


def validate_approval(
    path: Path,
    *,
    key: str,
    now: datetime,
    expected: Mapping[str, str],
) -> dict[str, Any]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ApprovalError("now must be timezone-aware")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApprovalError(f"approval artifact unreadable: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise ApprovalError("approval artifact must be an object")
    signature = payload.get("signature")
    if not isinstance(signature, str):
        raise ApprovalError("approval signature missing")
    expected_signature = sign_approval(payload, key)["signature"]
    if not hmac.compare_digest(signature, expected_signature):
        raise ApprovalError("approval signature mismatch")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ApprovalError("approval schema mismatch")
    for name, value in expected.items():
        if payload.get(name) != value:
            raise ApprovalError(f"approval field mismatch: {name}")
    try:
        expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    except (KeyError, ValueError) as exc:
        raise ApprovalError("approval expiry invalid") from exc
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ApprovalError("approval expiry must be timezone-aware")
    if expires_at <= now:
        raise ApprovalError("approval expired")
    if payload.get("consumed") is not False:
        raise ApprovalError("approval already consumed")
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or len(nonce) < 32:
        raise ApprovalError("approval nonce invalid")
    return payload


def consume_approval(path: Path, payload: Mapping[str, Any], *, now: datetime) -> Path:
    consumed = dict(payload)
    consumed["consumed"] = True
    consumed["consumed_at"] = now.isoformat()
    consumed.pop("signature", None)
    destination = path.with_name(path.name + ".consumed")
    temp = destination.with_name(destination.name + ".tmp")
    temp.write_text(
        json.dumps(consumed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, destination)
    path.unlink()
    return destination
