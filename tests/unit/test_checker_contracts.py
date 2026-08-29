"""checker が「対象が無い / 空」を pass にしないことの回帰。

2026-08-29 のセルフレビューで出た実バグ 9 件のうち 8 件がこの型だった
(`docs/pr-self-review.md` R1)。`verify_skill_manifests` と
`verify_adr_numbering` の 2 本が独立に同じ 0 件 fail-open を持っていたので、
R14 に従って機械検査へ昇格させる。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_checker_contracts", ROOT / "scripts" / "verify_checker_contracts.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_this_repository_passes() -> None:
    """本番の checker 群が全部この契約を満たすこと。"""
    assert MODULE.verify(ROOT) == []


def _fake(subject: str, verify) -> SimpleNamespace:
    return SimpleNamespace(SUBJECT=subject, verify=verify)


def test_checker_accepting_an_empty_subject_is_reported() -> None:
    """空の対象を pass にする checker を落とす。実際に起きていた形。"""
    module = _fake("skills", lambda repo: [])
    assert MODULE._probe(module, "skills", present=True) is not None
    assert "accepted an empty subject" in MODULE._probe(module, "skills", present=True)


def test_checker_raising_on_a_missing_subject_is_reported() -> None:
    """対象が無い時に例外で死ぬ checker を落とす。実際に起きていた形。"""

    def boom(repo: Path) -> list[str]:
        raise FileNotFoundError("policy/invariants.json")

    problem = MODULE._probe(_fake("policy/invariants.json", boom), "policy/invariants.json", present=False)
    assert problem is not None and "raised FileNotFoundError" in problem


def test_checker_that_rejects_both_is_accepted() -> None:
    """正しく拒否する checker は通す。過検知で運用を止めない。"""
    module = _fake("skills", lambda repo: ["skills/ not found"])
    assert MODULE._probe(module, "skills", present=False) is None
    assert MODULE._probe(module, "skills", present=True) is None


def test_checker_returning_a_non_list_is_reported() -> None:
    module = _fake("skills", lambda repo: "broken")
    problem = MODULE._probe(module, "skills", present=True)
    assert problem is not None and "instead of a list" in problem


def test_checker_without_subject_is_reported(tmp_path: Path) -> None:
    """宣言が無い checker を黙って飛ばさない。飛ばすとこの検査自体が空振りする。"""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "verify_nothing.py").write_text(
        "from pathlib import Path\n\n\ndef verify(repo: Path) -> list[str]:\n    return []\n",
        encoding="utf-8",
    )
    errors = MODULE.verify(tmp_path)
    assert any("must declare SUBJECT" in e for e in errors)


def test_checker_without_verify_is_reported(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "verify_nothing.py").write_text('SUBJECT = "docs"\n', encoding="utf-8")
    errors = MODULE.verify(tmp_path)
    assert any("must expose verify(repo)" in e for e in errors)


def test_no_checkers_found_is_not_a_pass(tmp_path: Path) -> None:
    """0 件を pass にすると、この検査自身が塞ごうとしている型になる。"""
    (tmp_path / "scripts").mkdir()
    errors = MODULE.verify(tmp_path)
    assert any("contains no verify_*.py" in e for e in errors)


def test_missing_scripts_directory_is_reported(tmp_path: Path) -> None:
    assert MODULE.verify(tmp_path) == ["scripts/ not found"]


def test_unimportable_checker_is_reported(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "verify_broken.py").write_text("def (\n", encoding="utf-8")
    errors = MODULE.verify(tmp_path)
    assert any("cannot be imported" in e for e in errors)
