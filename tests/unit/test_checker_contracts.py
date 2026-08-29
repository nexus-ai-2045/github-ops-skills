"""checker が「対象が無い / 空」を pass にしないことの回帰。

2026-08-29 のセルフレビューで出た実バグの大半がこの型だった
(`docs/pr-self-review.md` R1)。`verify_skill_manifests` と
`verify_adr_numbering` の 2 本が独立に同じ 0 件 fail-open を持っていたので、
R14 に従って機械検査へ昇格させた。

probe は **子プロセス** で走る。checker の fixture を module object ではなく
実ファイルで書いているのはそのため ── 本番と同じ経路を通る。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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


# --- fixture ヘルパ ----------------------------------------------------------


def _repo_with_subject(tmp_path: Path, subject: str, *, is_dir: bool) -> Path:
    """SUBJECT が実在する最小の repo。probe はここから複製して壊す。"""
    target = tmp_path / subject
    if is_dir:
        target.mkdir(parents=True)
        (target / "keep.txt").write_text("x\n", encoding="utf-8")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir(exist_ok=True)
    return tmp_path


def _write_checker(repo: Path, name: str, source: str) -> Path:
    scripts = repo / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    path = scripts / f"verify_{name}.py"
    path.write_text(source, encoding="utf-8")
    return path


def _checker(repo: Path, name: str, subject: str, body: str) -> Path:
    """`verify()` の本体だけを渡して checker を書く。"""
    indented = "".join(f"    {line}\n" for line in body.strip("\n").splitlines())
    return _write_checker(
        repo,
        name,
        "from pathlib import Path\n\n"
        f"SUBJECT = {subject!r}\n\n\n"
        "def verify(repo: Path) -> list[str]:\n" + indented,
    )


def _problems(repo: Path, name: str, subject: str, body: str) -> list[str]:
    return MODULE._probe(_checker(repo, name, subject, body), None, repo, subject)


# --- 契約の中核 --------------------------------------------------------------


def test_checker_accepting_an_empty_subject_is_reported(tmp_path: Path) -> None:
    """空の対象を pass にする checker を落とす。実際に起きていた形。"""
    repo = _repo_with_subject(tmp_path, "skills", is_dir=True)
    problems = _problems(
        repo, "empty_ok", "skills", 'return [] if (repo / "skills").exists() else ["gone"]'
    )
    assert any("accepted an empty subject" in p for p in problems), problems


def test_checker_raising_on_a_missing_subject_is_reported(tmp_path: Path) -> None:
    """対象が無い時に例外で死ぬ checker を落とす。実際に起きていた形。"""
    repo = _repo_with_subject(tmp_path, "policy/invariants.json", is_dir=False)
    problems = _problems(
        repo,
        "boom",
        "policy/invariants.json",
        'if not (repo / "policy/invariants.json").is_file():\n'
        '    raise FileNotFoundError("policy/invariants.json")\n'
        "return []",
    )
    assert any("raised FileNotFoundError" in p for p in problems), problems


def test_checker_that_rejects_both_is_accepted(tmp_path: Path) -> None:
    """正しく拒否する checker は通す。過検知で運用を止めない。"""
    repo = _repo_with_subject(tmp_path, "skills", is_dir=True)
    problems = _problems(
        repo,
        "good",
        "skills",
        't = repo / "skills"\n'
        "if not t.is_dir():\n"
        '    return ["skills/ not found"]\n'
        "if not any(t.iterdir()):\n"
        '    return ["skills/ is empty"]\n'
        "return []",
    )
    assert problems == []


def test_checker_returning_a_non_list_is_reported(tmp_path: Path) -> None:
    repo = _repo_with_subject(tmp_path, "skills", is_dir=True)
    problems = _problems(repo, "notalist", "skills", 'return "broken"')
    assert any("instead of a list" in p for p in problems), problems


def test_finding_that_is_not_a_non_empty_string_is_reported(tmp_path: Path) -> None:
    """契約は list[str]。[""] や [None] を通すと呼び出し側が壊れる。"""
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)
    problems = _problems(repo, "blankstr", "docs", 'return [""]')
    assert any("not a non-empty str" in p for p in problems), problems


def test_findings_on_a_valid_repository_are_reported(tmp_path: Path) -> None:
    """SUBJECT を一切見ない checker が、無関係な所見で契約を満たすのを防ぐ。"""
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)
    problems = _problems(
        repo,
        "ignores",
        "docs",
        'return [] if (repo / "unrelated.json").is_file() else ["unrelated.json not found"]',
    )
    assert any("cannot be attributed to the mutation" in p for p in problems), problems


# --- 宣言の検査 --------------------------------------------------------------


def test_checker_without_subject_is_reported(tmp_path: Path) -> None:
    """宣言が無い checker を黙って飛ばさない。飛ばすとこの検査自体が空振りする。"""
    _write_checker(
        tmp_path,
        "nothing",
        "from pathlib import Path\n\n\ndef verify(repo: Path) -> list[str]:\n    return []\n",
    )
    assert any("must declare SUBJECT" in e for e in MODULE.verify(tmp_path))


def test_checker_without_verify_is_reported(tmp_path: Path) -> None:
    _write_checker(tmp_path, "nothing", 'SUBJECT = "docs"\n')
    assert any("must expose verify(repo)" in e for e in MODULE.verify(tmp_path))


def test_subject_not_present_in_the_repository_is_reported(tmp_path: Path) -> None:
    _checker(tmp_path, "absent", "docs/nope", 'return ["x"]')
    assert any("is not in this repository" in e for e in MODULE.verify(tmp_path))


def test_no_checkers_found_is_not_a_pass(tmp_path: Path) -> None:
    """0 件を pass にすると、この検査自身が塞ごうとしている型になる。"""
    (tmp_path / "scripts").mkdir()
    assert any("contains no verify_*.py" in e for e in MODULE.verify(tmp_path))


def test_missing_scripts_directory_is_reported(tmp_path: Path) -> None:
    assert MODULE.verify(tmp_path) == ["scripts/ not found"]


def test_unimportable_checker_is_reported(tmp_path: Path) -> None:
    _write_checker(tmp_path, "broken", "def (\n")
    assert any("cannot be imported" in e for e in MODULE.verify(tmp_path))


# --- probe が複製の外を壊さないこと ------------------------------------------


def test_subject_escaping_the_probe_root_is_rejected() -> None:
    assert MODULE._subject_error("../escape") is not None
    assert MODULE._subject_error("/etc/passwd") is not None
    assert MODULE._subject_error("docs/adr") is None


def test_subject_escape_is_caught_before_any_write(tmp_path: Path) -> None:
    _checker(tmp_path, "escape", "../escaped", 'return ["always"]')
    errors = MODULE.verify(tmp_path)
    assert any("parent traversal" in e for e in errors), errors
    assert not (tmp_path.parent / "escaped").exists()


def test_subject_traversing_a_symlink_is_rejected_before_any_write(tmp_path: Path) -> None:
    """`..` と絶対 path を塞いでも、repo 内 symlink 経由で外へ抜けられた。

    実測では複製の外の実ディレクトリが rmtree された。read-only 契約の違反。
    """
    outside = tmp_path / "outside"
    (outside / "precious").mkdir(parents=True)
    (outside / "precious" / "a.txt").write_text("a\n", encoding="utf-8")

    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "link").symlink_to(outside, target_is_directory=True)
    _checker(repo, "rmtree", "docs/link/precious", 'return [] if (repo / SUBJECT).is_dir() else ["gone"]')

    errors = MODULE.verify(repo)
    assert any("traverses a symlink" in e for e in errors), errors
    assert (outside / "precious" / "a.txt").is_file()


def test_symlink_component_ignores_a_merely_absent_path(tmp_path: Path) -> None:
    """「単に存在しない」を symlink 扱いにしない。過検知を持ち込まない。"""
    assert MODULE._symlink_component(tmp_path, "docs/absent") is None


def test_subject_excluded_from_the_snapshot_gets_its_own_message() -> None:
    """複製に含まれない対象を、checker のせいにしない。"""
    problem = MODULE._subject_error("node_modules/pkg")
    assert problem is not None and "excluded from the probe snapshot" in problem


def test_a_probe_that_cannot_mutate_is_a_finding_not_a_traceback(tmp_path: Path) -> None:
    """変異に失敗しても、この検査が他へ課している契約を自分で破らないこと。"""
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)
    path = _checker(repo, "fine", "docs", 'return [] if (repo / "docs").is_dir() else ["gone"]')

    def boom(root: Path, subject: str, *, empty: bool) -> None:
        raise PermissionError("cannot remove")

    original = MODULE._break_subject
    MODULE._break_subject = boom
    try:
        problems = MODULE._probe(path, None, repo, "docs")
    finally:
        MODULE._break_subject = original
    assert any("could not break docs" in p for p in problems), problems


# --- 変異が「対象だけ」であること --------------------------------------------


def test_subject_type_comes_from_the_real_entry_not_the_suffix(tmp_path: Path) -> None:
    """suffix 無しの file (LICENSE) を dir と誤認すると、空 file を試せない。"""
    repo = _repo_with_subject(tmp_path, "LICENSE", is_dir=False)
    problems = _problems(
        repo,
        "licensetype",
        "LICENSE",
        'return [] if (repo / "LICENSE").is_file() else ["LICENSE is not a file"]',
    )
    assert any("accepted an empty subject" in p for p in problems), problems


def test_empty_subject_probe_preserves_file_mode(tmp_path: Path) -> None:
    """空 probe で mode を落とすと、権限だけ見て中身を無視する checker がすり抜ける。"""
    repo = _repo_with_subject(tmp_path, "bin/tool", is_dir=False)
    (repo / "bin" / "tool").chmod(0o755)
    problems = _problems(
        repo,
        "permfile",
        "bin/tool",
        't = repo / "bin" / "tool"\n'
        "if not t.is_file():\n"
        '    return ["bin/tool is missing"]\n'
        "if t.stat().st_mode & 0o777 != 0o755:\n"
        '    return ["bin/tool has the wrong mode"]\n'
        "return []",
    )
    assert any("accepted an empty subject" in p for p in problems), problems


def test_empty_subject_probe_preserves_directory_mode(tmp_path: Path) -> None:
    """dir を作り直すと mode が変わり、権限だけ見る checker が空 dir をすり抜ける。"""
    repo = _repo_with_subject(tmp_path, "skills", is_dir=True)
    (repo / "skills").chmod(0o700)
    problems = _problems(
        repo,
        "permdir",
        "skills",
        't = repo / "skills"\n'
        "if not t.is_dir():\n"
        '    return ["skills/ is missing"]\n'
        "if t.stat().st_mode & 0o777 != 0o700:\n"
        '    return ["skills/ has the wrong mode"]\n'
        "return []",
    )
    assert any("accepted an empty subject" in p for p in problems), problems


# --- probe 間の隔離（2026-08-29 Codex review 第 3 巡）-------------------------


def test_module_level_state_does_not_leak_across_probes(tmp_path: Path) -> None:
    """同一 module を使い回すと、1 回目の [] のあと拒否する checker がすり抜ける。"""
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)
    _write_checker(
        repo,
        "oneshot",
        "from pathlib import Path\n\n"
        'SUBJECT = "docs"\n'
        "_called = False\n\n\n"
        "def verify(repo: Path) -> list[str]:\n"
        "    global _called\n"
        "    if not _called:\n"
        "        _called = True\n"
        "        return []\n"
        '    return ["already called"]\n',
    )
    errors = MODULE.verify(repo)
    assert any("accepted" in e for e in errors), errors
    assert not any("cannot be imported" in e for e in errors), errors


def test_state_in_an_imported_helper_does_not_leak_across_probes(tmp_path: Path) -> None:
    """状態が checker ではなく src 側 helper にある場合も隔離すること。

    module を読み直しても、import 済み helper は sys.modules に残る。
    実測ではこれで SUBJECT を一切見ない checker が合格した。
    """
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)
    (repo / "src").mkdir()
    (repo / "src" / "leakystate.py").write_text(
        "SEEN = False\n\n\n"
        "def first_time() -> bool:\n"
        "    global SEEN\n"
        "    was = SEEN\n"
        "    SEEN = True\n"
        "    return not was\n",
        encoding="utf-8",
    )
    _write_checker(
        repo,
        "leaky",
        "import sys\n"
        "from pathlib import Path\n"
        'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))\n'
        "import leakystate\n\n"
        'SUBJECT = "docs"\n\n\n'
        "def verify(repo: Path) -> list[str]:\n"
        '    return [] if leakystate.first_time() else ["already called"]\n',
    )
    errors = MODULE.verify(repo)
    assert any("accepted" in e for e in errors), errors


def test_sys_exit_does_not_silently_end_the_run(tmp_path: Path) -> None:
    """sys.exit は BaseException 側。素通りするとこの検査自身が黙って exit 0 する。"""
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)
    problems = _problems(repo, "exiter", "docs", "raise SystemExit(0)")
    assert any("called sys.exit(0)" in p for p in problems), problems


def test_sys_exit_during_a_later_load_is_reported(tmp_path: Path) -> None:
    """最初の import は通るが、後の読み直しで exit する checker。

    子プロセスで走らせないと、この exit が親を無出力 exit 0 で終わらせる。
    """
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)
    (repo / "src").mkdir()
    (repo / "src" / "loadcount.py").write_text(
        "CALLS = 0\n\n\ndef bump() -> int:\n"
        "    global CALLS\n"
        "    CALLS += 1\n"
        "    return CALLS\n",
        encoding="utf-8",
    )
    _write_checker(
        repo,
        "exit_on_reload",
        "import sys\n"
        "from pathlib import Path\n"
        'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))\n'
        "import loadcount\n\n"
        'SUBJECT = "docs"\n'
        "if loadcount.bump() > 1:\n"
        "    sys.exit(0)\n\n\n"
        "def verify(repo: Path) -> list[str]:\n"
        '    return [] if (repo / "docs").is_dir() else ["gone"]\n',
    )
    errors = MODULE.verify(repo)
    # 無出力 exit 0 にならず、所見として返ること
    assert errors, errors


def test_checker_using_pickle_is_not_broken_by_the_loader(tmp_path: Path) -> None:
    """module を sys.modules に登録しないと、正常な checker が PicklingError で落ちる。"""
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)
    _write_checker(
        repo,
        "pickles",
        "from __future__ import annotations\n"
        "import pickle\n"
        "from dataclasses import dataclass\n"
        "from pathlib import Path\n\n"
        'SUBJECT = "docs"\n\n\n'
        "@dataclass\n"
        "class Finding:\n"
        "    text: str\n\n\n"
        "def verify(repo: Path) -> list[str]:\n"
        '    pickle.dumps(Finding("x"))\n'
        '    t = repo / "docs"\n'
        "    if not t.is_dir():\n"
        '        return ["docs/ not found"]\n'
        '    return [] if any(t.iterdir()) else ["docs/ is empty"]\n',
    )
    assert MODULE.verify(repo) == []


def test_future_annotations_dataclass_checker_can_be_imported(tmp_path: Path) -> None:
    """sys.modules 未登録のまま exec すると @dataclass + future annotations が落ちる。"""
    repo = _repo_with_subject(tmp_path, "docs", is_dir=True)
    _write_checker(
        repo,
        "future_dc",
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n"
        "from pathlib import Path\n\n"
        "@dataclass\n"
        "class Item:\n"
        "    name: str\n\n"
        'SUBJECT = "docs"\n\n\n'
        "def verify(repo: Path) -> list[str]:\n"
        '    _ = Item("x")\n'
        '    t = repo / "docs"\n'
        "    if not t.is_dir():\n"
        '        return ["docs missing"]\n'
        '    return [] if any(t.iterdir()) else ["docs empty"]\n',
    )
    assert MODULE.verify(repo) == []


def test_sys_path_does_not_grow_on_repeated_runs() -> None:
    """テストプロセスの sys.path を恒久的に汚さないこと。"""
    before = len(sys.path)
    for _ in range(3):
        MODULE.verify(ROOT)
    assert len(sys.path) == before
