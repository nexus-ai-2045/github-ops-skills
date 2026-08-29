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


def _repo_with_subject(tmp_path: Path, subject: str, *, is_dir: bool) -> Path:
    """SUBJECT が実在する最小の repo。_probe はここから複製して壊す。"""
    target = tmp_path / subject
    if is_dir:
        target.mkdir(parents=True)
        (target / "keep.txt").write_text("x\n", encoding="utf-8")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n", encoding="utf-8")
    return tmp_path


def test_checker_accepting_an_empty_subject_is_reported(tmp_path: Path) -> None:
    """空の対象を pass にする checker を落とす。実際に起きていた形。"""
    repo = _repo_with_subject(tmp_path, "skills", is_dir=True)
    module = _fake("skills", lambda r: [] if (r / "skills").exists() else ["gone"])
    problems = MODULE._probe(module, repo, "skills")
    assert any("accepted an empty subject" in p for p in problems), problems


def test_checker_raising_on_a_missing_subject_is_reported(tmp_path: Path) -> None:
    """対象が無い時に例外で死ぬ checker を落とす。実際に起きていた形。"""
    repo = _repo_with_subject(tmp_path, "policy/invariants.json", is_dir=False)

    def boom(r: Path) -> list[str]:
        return [] if (r / "policy/invariants.json").is_file() else _raise()

    def _raise():
        raise FileNotFoundError("policy/invariants.json")

    problems = MODULE._probe(_fake("policy/invariants.json", boom), repo, "policy/invariants.json")
    assert any("raised FileNotFoundError" in p for p in problems), problems


def test_checker_that_rejects_both_is_accepted(tmp_path: Path) -> None:
    """正しく拒否する checker は通す。過検知で運用を止めない。"""
    repo = _repo_with_subject(tmp_path, "skills", is_dir=True)

    def ok(r: Path) -> list[str]:
        target = r / "skills"
        if not target.is_dir():
            return ["skills/ not found"]
        if not any(target.iterdir()):
            return ["skills/ is empty"]
        return []

    assert MODULE._probe(_fake("skills", ok), repo, "skills") == []


def test_checker_returning_a_non_list_is_reported(tmp_path: Path) -> None:
    repo = _repo_with_subject(tmp_path, "skills", is_dir=True)
    problems = MODULE._probe(_fake("skills", lambda r: "broken"), repo, "skills")
    assert any("instead of a list" in p for p in problems), problems


# --- 2026-08-29 Codex review で見つかった 5 件の回帰 --------------------------


def test_sys_exit_does_not_silently_end_the_run(tmp_path: Path) -> None:
    """sys.exit は BaseException 側。素通りするとこの検査自身が黙って exit 0 する。"""
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)

    def exiter(r: Path) -> list[str]:
        raise SystemExit(0)

    problems = MODULE._probe(_fake("docs", exiter), repo, "docs")
    assert any("called sys.exit(0)" in p for p in problems), problems


def test_subject_escaping_the_probe_root_is_rejected(tmp_path: Path) -> None:
    """絶対 path / 親への遡上を probe に渡すと、複製の外へ書き込む事故になる。"""
    assert MODULE._subject_error("../escape") is not None
    assert MODULE._subject_error("/etc/passwd") is not None
    assert MODULE._subject_error("docs/adr") is None


def test_subject_escape_is_caught_before_any_write(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "verify_escape.py").write_text(
        'from pathlib import Path\n'
        'SUBJECT = "../escaped"\n\n\n'
        'def verify(repo: Path) -> list[str]:\n    return ["always"]\n',
        encoding="utf-8",
    )
    errors = MODULE.verify(tmp_path)
    assert any("parent traversal" in e for e in errors), errors
    assert not (tmp_path.parent / "escaped").exists()


def test_finding_that_is_not_a_non_empty_string_is_reported(tmp_path: Path) -> None:
    """契約は list[str]。[""] や [None] を通すと呼び出し側が壊れる。"""
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)
    problems = MODULE._probe(_fake("docs", lambda r: [""]), repo, "docs")
    assert any("not a non-empty str" in p for p in problems), problems


def test_subject_type_comes_from_the_real_entry_not_the_suffix(tmp_path: Path) -> None:
    """suffix 無しの file (LICENSE) を dir と誤認すると、空 file を試せない。"""
    repo = _repo_with_subject(tmp_path, "LICENSE", is_dir=False)

    def only_checks_type(r: Path) -> list[str]:
        # 空の LICENSE は素通りする checker。dir を作られると型違いで拒否になり
        # 「拒否した」と誤判定されてしまう
        return [] if (r / "LICENSE").is_file() else ["LICENSE is not a file"]

    problems = MODULE._probe(_fake("LICENSE", only_checks_type), repo, "LICENSE")
    assert any("accepted an empty subject" in p for p in problems), problems


def test_findings_on_a_valid_repository_are_reported(tmp_path: Path) -> None:
    """SUBJECT を一切見ない checker が、無関係な所見で契約を満たすのを防ぐ。"""
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)

    def ignores_subject(r: Path) -> list[str]:
        return [] if (r / "unrelated.json").is_file() else ["unrelated.json not found"]

    problems = MODULE._probe(_fake("docs", ignores_subject), repo, "docs")
    assert any("cannot be attributed to the mutation" in p for p in problems), problems


def test_subject_not_present_in_the_repository_is_reported(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "verify_absent.py").write_text(
        'from pathlib import Path\n'
        'SUBJECT = "docs/nope"\n\n\n'
        'def verify(repo: Path) -> list[str]:\n    return ["x"]\n',
        encoding="utf-8",
    )
    errors = MODULE.verify(tmp_path)
    assert any("is not in this repository" in e for e in errors), errors


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
