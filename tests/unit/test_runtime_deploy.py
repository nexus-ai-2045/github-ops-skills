from __future__ import annotations

import json
from pathlib import Path

import pytest

from github_ops.runtime_deploy import deploy_skills, plan_skills, rollback_deployment


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    skill = repo / "skills" / "demo"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("new skill\n", encoding="utf-8")
    (skill / "references" / "contract.md").write_text("contract\n", encoding="utf-8")
    (skill / "manifest.yaml").write_text(
        """
name: demo
runtimes:
  codex:
    mode: copy
    files:
      - SKILL.md
      - references/contract.md
""".lstrip(),
        encoding="utf-8",
    )
    return repo


def test_plan_reports_drift_without_writing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    target = tmp_path / "home" / "skills"
    target.mkdir(parents=True)

    result = plan_skills(repo, target, runtime="codex", selected_skills=["demo"])

    assert result["status"] == "drift"
    assert result["summary"] == {"match": 0, "drift": 0, "missing": 2}
    assert not (target / "demo").exists()


def test_deploy_preserves_unmanaged_files_and_writes_receipt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    target = tmp_path / "home" / "skills"
    demo = target / "demo"
    demo.mkdir(parents=True)
    (demo / "SKILL.md").write_text("old skill\n", encoding="utf-8")
    (demo / "local-note.md").write_text("preserve\n", encoding="utf-8")

    result = deploy_skills(
        repo,
        target,
        runtime="codex",
        selected_skills=["demo"],
        backup_root=tmp_path / "backups",
        approval_ref="test-approval",
        confirmed=True,
    )

    assert result["status"] == "verified"
    assert (demo / "SKILL.md").read_text(encoding="utf-8") == "new skill\n"
    assert (demo / "references" / "contract.md").is_file()
    assert (demo / "local-note.md").read_text(encoding="utf-8") == "preserve\n"
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["approval_ref"] == "test-approval"
    assert receipt["verified"] is True


def test_rollback_restores_old_and_removes_new_managed_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    target = tmp_path / "home" / "skills"
    demo = target / "demo"
    demo.mkdir(parents=True)
    (demo / "SKILL.md").write_text("old skill\n", encoding="utf-8")
    result = deploy_skills(
        repo,
        target,
        runtime="codex",
        selected_skills=["demo"],
        backup_root=tmp_path / "backups",
        approval_ref="test-approval",
        confirmed=True,
    )

    rolled_back = rollback_deployment(Path(result["receipt_path"]))

    assert rolled_back["status"] == "rolled_back"
    assert (demo / "SKILL.md").read_text(encoding="utf-8") == "old skill\n"
    assert not (demo / "references" / "contract.md").exists()


def test_deploy_requires_explicit_confirmation(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="confirm"):
        deploy_skills(
            _repo(tmp_path),
            tmp_path / "home" / "skills",
            runtime="codex",
            selected_skills=["demo"],
            backup_root=tmp_path / "backups",
            approval_ref="test-approval",
            confirmed=False,
        )


def test_rollback_rejects_path_traversal_in_receipt(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "github-ops-runtime-deploy/v1",
                "status": "verified",
                "target_root": str(tmp_path / "target"),
                "backup_path": str(tmp_path / "backup"),
                "files": [
                    {
                        "skill": "demo",
                        "relative_path": "../../outside.txt",
                        "existed_before": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsafe receipt path"):
        rollback_deployment(receipt)
