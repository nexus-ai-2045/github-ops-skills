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


# --- 2026-08-29 セルフレビューで見つかった 4 件の回帰 --------------------------
#
# いずれも「検査が空振りしたのに status: pass を返す」型 (docs/pr-self-review.md R1)。
# ADR を再編した瞬間に音もなく無効化される経路だった。


def test_empty_adr_directory_is_not_a_pass(tmp_path: Path) -> None:
    """0 件を pass にすると保証が空虚に満たされる。"""
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    errors = MODULE.verify(tmp_path)
    assert any("contains no files" in e for e in errors)


def test_adr_in_a_subdirectory_is_reported(tmp_path: Path) -> None:
    """下位ディレクトリへ整理し直すと検査対象が 0 になる経路を塞ぐ。"""
    _adr(tmp_path, "0002-a.md", "# ADR-0002: a")
    nested = tmp_path / "docs" / "adr" / "2026"
    nested.mkdir()
    (nested / "0002-b.md").write_text("# ADR-0002: b\n", encoding="utf-8")
    errors = MODULE.verify(tmp_path)
    assert any("not in a subdirectory" in e for e in errors)


def test_uppercase_md_extension_is_reported(tmp_path: Path) -> None:
    """`.MD` は Linux の glob("*.md") で列挙されず、判定が OS で割れる。"""
    _adr(tmp_path, "0002-a.md", "# ADR-0002: a")
    (tmp_path / "docs" / "adr" / "0002-B.MD").write_text(
        "# ADR-0002: b\n", encoding="utf-8"
    )
    errors = MODULE.verify(tmp_path)
    assert any("0002-B.MD" in e and "lowercase .md" in e for e in errors)


def test_fullwidth_digits_do_not_create_a_second_numbering_space(tmp_path: Path) -> None:
    """`\\d` は Unicode 数字を拾う。全角が別番号として素通りしないこと。"""
    _adr(tmp_path, "0002-ascii.md", "# ADR-0002: ascii")
    (tmp_path / "docs" / "adr" / "０００２-zenkaku.md").write_text(
        "# ADR-０００２: zenkaku\n", encoding="utf-8"
    )
    errors = MODULE.verify(tmp_path)
    assert any("zenkaku" in e for e in errors)


def test_bom_does_not_hide_a_correct_heading(tmp_path: Path) -> None:
    """BOM を付けるエディタで、正しい ADR が見出し無しと誤判定されないこと。"""
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-a.md").write_text(
        "# ADR-0001: 正しい見出し\n", encoding="utf-8-sig"
    )
    assert MODULE.verify(tmp_path) == []


def test_non_adr_file_in_the_directory_is_reported(tmp_path: Path) -> None:
    """docs/adr/ は ADR だけを置く。形が違うものは黙って無視しない。"""
    _adr(tmp_path, "0001-a.md", "# ADR-0001: a")
    (tmp_path / "docs" / "adr" / "notes.txt").write_text("x\n", encoding="utf-8")
    errors = MODULE.verify(tmp_path)
    assert any("notes.txt" in e for e in errors)
