import json
import shutil
from pathlib import Path

import pytest

from scripts.verify_invariant_registry import verify


@pytest.mark.parametrize("identifier", ["GHO-EXEC-001", "GHO-SCAN-001"])
def test_adopted_execution_contract_cannot_be_removed(tmp_path: Path, identifier: str) -> None:
    root = Path(__file__).resolve().parents[2]
    shutil.copytree(root / "policy", tmp_path / "policy")
    shutil.copytree(root / "tests", tmp_path / "tests")
    registry = tmp_path / "policy/invariants.json"
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["invariants"] = [item for item in payload["invariants"] if item["id"] != identifier]
    registry.write_text(json.dumps(payload), encoding="utf-8")
    assert f"required invariant missing: {identifier}" in verify(tmp_path)


def test_repository_invariant_registry_is_self_consistent() -> None:
    assert verify(Path(__file__).resolve().parents[2]) == []


def test_checker_execution_boundary_is_registered_as_an_invariant() -> None:
    payload = json.loads(
        (Path(__file__).resolve().parents[2] / "policy" / "invariants.json").read_text(
            encoding="utf-8"
        )
    )
    checker = next(
        item for item in payload["invariants"] if item["id"] == "GHO-CHECKER-001"
    )
    assert checker["enforcement"] == "ci"
    assert checker["title"].startswith("R14:")
    assert "tests/unit/test_checker_contracts.py" in checker["test_paths"]


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


def test_registry_rejects_existing_non_test_path(tmp_path: Path) -> None:
    policy = tmp_path / "policy"
    tests = tmp_path / "tests"
    policy.mkdir()
    tests.mkdir()
    (tmp_path / "README.md").write_text("not a test module\n", encoding="utf-8")
    policy.joinpath("invariants.json").write_text(json.dumps({
        "schema_version": "github-ops/invariants/v1",
        "invariants": [{
            "id": "GHO-TYPE-001",
            "title": "test",
            "enforcement": "test",
            "test_paths": ["README.md"],
        }],
    }), encoding="utf-8")
    errors = verify(tmp_path)
    assert any(error.startswith("test path outside collected tests:") for error in errors)
