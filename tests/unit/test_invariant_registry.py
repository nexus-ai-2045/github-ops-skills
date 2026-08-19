from pathlib import Path

import json

from scripts.verify_invariant_registry import verify


def test_repository_invariant_registry_is_self_consistent() -> None:
    assert verify(Path(__file__).resolve().parents[2]) == []


def test_registry_rejects_external_test_path_and_missing_required_ids(tmp_path: Path) -> None:
    policy = tmp_path / "policy"
    policy.mkdir()
    outside = tmp_path.parent / "outside-test.py"
    outside.write_text("pass\n", encoding="utf-8")
    policy.joinpath("invariants.json").write_text(json.dumps({
        "schema_version": "github-ops/invariants/v1",
        "invariants": [{
            "id": "GHO-TYPE-001",
            "title": "test",
            "enforcement": "test",
            "test_paths": [str(outside)],
        }],
    }), encoding="utf-8")
    errors = verify(tmp_path)
    assert any(error.startswith("test path escapes repository:") for error in errors)
    assert "required invariant missing: GHO-ID-001" in errors
