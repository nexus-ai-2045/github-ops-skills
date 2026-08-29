"""docs/adr/ の採番検査の回帰。

ADR は path 無しの `ADR-NNNN` で参照される。番号が重複すると参照が
どちらを指すのか決定できない。実際に 0002 が 2 file に割り当てられていた
(2026-08-29 実測) ため、機械検査に落とす。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_adr_numbering", ROOT / "scripts" / "verify_adr_numbering.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _adr(repo: Path, name: str, heading: str) -> Path:
    adr_dir = repo / "docs" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    path = adr_dir / name
    path.write_text(f"{heading}\n\n- Status: accepted\n", encoding="utf-8")
    return path


def test_this_repository_passes() -> None:
    """本番の docs/adr/ が通ること。"""
    assert MODULE.verify(ROOT) == []


def test_duplicate_number_is_reported(tmp_path: Path) -> None:
    _adr(tmp_path, "0002-first.md", "# ADR-0002: first")
    _adr(tmp_path, "0002-second.md", "# ADR 0002: second")
    errors = MODULE.verify(tmp_path)
    assert any("ADR-0002 is claimed by 2 files" in e for e in errors)


def test_distinct_numbers_are_accepted(tmp_path: Path) -> None:
    _adr(tmp_path, "0002-first.md", "# ADR-0002: first")
    _adr(tmp_path, "0006-second.md", "# ADR 0006: second")
    assert MODULE.verify(tmp_path) == []


def test_gaps_in_numbering_are_not_an_error(tmp_path: Path) -> None:
    """欠番は異常ではない。過検知で運用が止まらないこと。"""
    _adr(tmp_path, "0001-a.md", "# ADR-0001: a")
    _adr(tmp_path, "0009-b.md", "# ADR-0009: b")
    assert MODULE.verify(tmp_path) == []


def test_heading_disagreeing_with_the_file_name_is_reported(tmp_path: Path) -> None:
    """rename しただけで見出しを直し忘れる事故を拾う。"""
    _adr(tmp_path, "0006-renamed.md", "# ADR 0002: renamed")
    errors = MODULE.verify(tmp_path)
    assert any("heading says ADR-0002" in e and "0006" in e for e in errors)


def test_both_heading_separators_are_accepted(tmp_path: Path) -> None:
    """`ADR-0002:` と `ADR 0002:` はどちらも現用の書き方。"""
    _adr(tmp_path, "0001-hyphen.md", "# ADR-0001: hyphen")
    _adr(tmp_path, "0002-space.md", "# ADR 0002: space")
    assert MODULE.verify(tmp_path) == []


def test_file_name_without_a_number_is_reported(tmp_path: Path) -> None:
    _adr(tmp_path, "no-number.md", "# ADR-0001: x")
    errors = MODULE.verify(tmp_path)
    assert any("must be NNNN-slug.md" in e for e in errors)


def test_missing_heading_is_reported(tmp_path: Path) -> None:
    _adr(tmp_path, "0001-a.md", "# 見出しに番号が無い")
    errors = MODULE.verify(tmp_path)
    assert any("must be an 'ADR-NNNN:' heading" in e for e in errors)


def test_empty_file_is_reported(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-empty.md").write_text("", encoding="utf-8")
    errors = MODULE.verify(tmp_path)
    assert any("empty file" in e for e in errors)


def test_missing_adr_directory_is_reported(tmp_path: Path) -> None:
    assert MODULE.verify(tmp_path) == ["docs/adr/ not found"]
