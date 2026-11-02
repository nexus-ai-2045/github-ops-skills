from pathlib import Path

from github_ops.identity import IdentityProbe


def test_local_probe_returns_structured_result() -> None:
    outcome = IdentityProbe().probe(Path.cwd())
    assert outcome.status.value in {"READY", "BLOCKED", "UNKNOWN"}
    assert outcome.code
    assert outcome.cause
    assert outcome.impact
    assert outcome.recovery
