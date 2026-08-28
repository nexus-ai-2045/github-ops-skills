"""skills/*/manifest.yaml の ssot_pointers 検査の回帰。

manifest は正本の所在を宣言するが、その宣言を検証する lint は
nexus-ai-skills 側にあり、この repository へ配布されていない。
宣言だけ移植されて宣言先が存在しない状態が実際に起きていたため、
ここで機械検査に落とす。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_skill_manifests", ROOT / "scripts" / "verify_skill_manifests.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _skill(repo: Path, name: str, manifest_body: str) -> Path:
    skill_dir = repo / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    (skill_dir / "manifest.yaml").write_text(manifest_body, encoding="utf-8")
    return skill_dir


def test_this_repository_passes() -> None:
    """本番の skills/ が通ること。"""
    assert MODULE.verify(ROOT) == []


def test_pointer_that_does_not_exist_is_reported(tmp_path: Path) -> None:
    _skill(
        tmp_path,
        "demo",
        "name: demo\nowner_kind: skill\nssot_pointers:\n  - shared/scripts/absent.py\n",
    )
    errors = MODULE.verify(tmp_path)
    assert any("does not exist (shared/scripts/absent.py)" in e for e in errors)


def test_pointer_that_exists_is_accepted(tmp_path: Path) -> None:
    _skill(
        tmp_path,
        "demo",
        "name: demo\nowner_kind: skill\nssot_pointers:\n  - skills/demo/SKILL.md\n",
    )
    assert MODULE.verify(tmp_path) == []


def test_empty_pointer_list_is_accepted(tmp_path: Path) -> None:
    _skill(tmp_path, "demo", "name: demo\nowner_kind: skill\nssot_pointers: []\n")
    assert MODULE.verify(tmp_path) == []


def test_header_claiming_a_foreign_ssot_is_reported(tmp_path: Path) -> None:
    """移植元のヘッダをそのまま持ち込むと、存在しない正本を名乗る。"""
    _skill(
        tmp_path,
        "demo",
        "# SSOT: shared/skills/demo/ (唯一の正本)\n"
        "name: demo\nowner_kind: skill\nssot_pointers: []\n",
    )
    errors = MODULE.verify(tmp_path)
    assert any("declares an SSOT outside this repository" in e for e in errors)


def test_header_declaring_this_repository_is_accepted(tmp_path: Path) -> None:
    _skill(
        tmp_path,
        "demo",
        "# SSOT in this repository: skills/demo/\n"
        "name: demo\nowner_kind: skill\nssot_pointers: []\n",
    )
    assert MODULE.verify(tmp_path) == []


def test_pointer_escaping_the_repository_is_reported(tmp_path: Path) -> None:
    _skill(
        tmp_path,
        "demo",
        "name: demo\nowner_kind: skill\nssot_pointers:\n  - ../outside.py\n",
    )
    errors = MODULE.verify(tmp_path)
    assert any("escapes the repository" in e for e in errors)


def test_inline_list_form_is_rejected_rather_than_silently_skipped(tmp_path: Path) -> None:
    """検査漏れを黙って作らないこと。"""
    _skill(
        tmp_path,
        "demo",
        "name: demo\nowner_kind: skill\nssot_pointers: [shared/x.py]\n",
    )
    errors = MODULE.verify(tmp_path)
    assert any("block list form" in e for e in errors)
