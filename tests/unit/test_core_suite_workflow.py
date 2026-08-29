import re
from pathlib import Path

import yaml


def test_core_suite_workflow_covers_local_verification_without_write_permissions() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / ".github" / "workflows" / "core-suite-ci.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)

    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"tests", "contracts"}
    for required in (
        "python -m pytest -q",
        "python -m compileall -q src scripts tests",
        'git diff --check "$BEFORE_SHA"..HEAD',
        'git diff --check "$BASE_SHA"..HEAD',
        "python adapters/codex/verify_adapter.py",
        "python adapters/claude/verify_adapter.py",
        "python adapters/grok/verify_adapter.py",
        # verify_* の CI step を固定する。テストが無いと step を消しても
        # 誰も気づかない = 宣言だけ残って執行が消える (ADR-0005 / 0007 と同じ型)
        "python scripts/verify_source_manifest_targets.py",
        "python scripts/verify_invariant_registry.py",
        "python scripts/verify_skill_manifests.py",
        "python scripts/verify_adr_numbering.py",
        "python scripts/verify_checker_contracts.py",
    ):
        assert required in text
    action_refs = re.findall(r"uses:\s*[^@\s]+@([^\s]+)", text)
    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)
    assert "pull_request_target" not in text
    assert "write" not in text
    assert "secrets." not in text
    assert text.count("persist-credentials: false") == 2
