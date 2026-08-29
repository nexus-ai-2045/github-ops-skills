"""各 checker が「対象が無い / 空」を pass にしないことを実際に走らせて確認する。

## なぜ必要か

2026-08-29 に出した検査 3 本を敵対的にレビューし直したところ、実バグが 9 件出た。
**9 件中 8 件が同じ形**だった。

    検査対象が空、または想定と違う場所にあるのに、status: pass を返す。

`docs/pr-self-review.md` の R1「検査は未確定を合格にしない」そのものであり、
R14 が言う「型で再発する」の実例でもある。実際 `verify_skill_manifests.py` と
`verify_adr_numbering.py` の 2 本が、独立に同じ 0 件 fail-open を持っていた。

## なぜ「negative テストがあるか」を見ないのか

最初その案を検討したが、**実測で効かないことが分かった**ので採らなかった。
バグ 4 件を抱えていた `verify_adr_numbering.py` の初版にも negative テストは
6 件あった。既存 3 本にも 2 / 5 / 4 件ある。「落ちるテストを持っているか」では
上記の型を 1 件も捕まえられない。

## 何をするか

`scripts/verify_*.py` を列挙し、それぞれについて **repo の正常な複製を作り、
宣言された対象 (`SUBJECT`) だけを壊して** 実際に `verify()` を呼ぶ。
**宣言を読むのではなく実行して確かめる。**

1. 複製に対して `verify()` が所見ゼロを返すことを先に確認する
   (ここが汚れていると、以降の所見が変異のせいだと言えない)
2. 対象を**削除**した複製 → 所見が出ること
3. 対象を**空**にした複製 → 所見が出ること

空 repo をゼロから作ると、対象と無関係な「あれが無い」という所見でも契約を
満たしてしまい、対象を一切見ていない checker が合格する (2026-08-29 Codex review)。
だから正常な複製から**対象だけ**を壊す。対象が file か directory かも、
suffix から推測せず**実在するエントリから決める**。

所見が空なら「空振りを pass にした」として落とす。例外が出た場合も落とす
(所見を list で返す契約が破れているため)。`SystemExit` も捕まえる ──
`sys.exit(0)` は `Exception` を継承しないので、素通りするとこの検査自身が
黙って exit 0 する。所見の要素が空でない str であることも見る。

## checker 側に要求する宣言

- `SUBJECT`: 検査対象の repo 相対 path (str)
- `verify(repo: Path) -> list[str]`

read-only。標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import stat
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType


SCRIPTS_DIRNAME = "scripts"
CHECKER_GLOB = "verify_*.py"
SELF_NAME = Path(__file__).name
# 複製に持ち込まないもの。履歴とキャッシュは検査対象ではない
SNAPSHOT_IGNORE_NAMES = (
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "node_modules",
    ".mypy_cache",
)
SNAPSHOT_IGNORE = shutil.ignore_patterns(*SNAPSHOT_IGNORE_NAMES)


def _load(path: Path) -> ModuleType:
    """checker を読み込む。import の副作用を呼び出し側へ漏らさない。

    checker には import 時に無条件で `sys.path.insert` するものがあり
    (`verify_source_manifest_targets.py`)、そのまま呼ぶと呼び出し側の
    `sys.path` が 1 本ずつ伸びる。pytest プロセスを恒久的に汚すので戻す。

    `from __future__ import annotations` と `@dataclass` など module を見る
    decorator は、exec 中に module が `sys.modules` へ入っていないと
    Python 3.11 で AttributeError になる。通常の import と同じく一時登録する。
    """
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot create a spec for {path.name}")
    module = importlib.util.module_from_spec(spec)
    name = spec.name
    saved = list(sys.path)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


def _subject_error(subject: str) -> str | None:
    """SUBJECT が複製の外を指していないか。指していたら書き込み事故になる。"""
    if Path(subject).is_absolute():
        return f"SUBJECT must be repo-relative, got an absolute path ({subject})"
    parts = Path(subject).parts
    if not parts:
        return "SUBJECT must not be empty"
    if any(part in {"..", ""} for part in parts):
        return f"SUBJECT must not contain a parent traversal ({subject})"
    if any(part in SNAPSHOT_IGNORE_NAMES for part in parts):
        # 複製に含まれないので、変異を作れない。checker のせいにしない
        return f"SUBJECT is excluded from the probe snapshot ({subject})"
    return None


def _symlink_component(root: Path, subject: str) -> str | None:
    """SUBJECT の途中に symlink が無いか。あると複製の外を消しに行く。

    `..` と絶対 path を塞いでも、repo 内の symlink 経由で外へ抜けられる。
    実測 (2026-08-29 self review) では複製の外の実ディレクトリが rmtree された。
    判定は `src/github_ops/source_manifest.py::_unsafe_component` と同じ考え方で、
    leaf を含む全 component を lstat する。ただし「単に存在しない」は
    symlink ではないので区別する (M3 と同じ取り違えを持ち込まない)。
    """
    current = root
    for part in Path(subject).parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            return f"cannot inspect {subject} ({exc})"
        attributes = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attributes & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            rel = current.relative_to(root).as_posix()
            return (
                f"SUBJECT traverses a symlink ({rel}); the probe would mutate "
                "outside the snapshot"
            )
    return None


def _call(module: ModuleType, root: Path, label: str) -> tuple[list[str] | None, str | None]:
    """verify() を 1 回呼ぶ。契約違反があればその説明を返す。"""
    try:
        errors = module.verify(root)
    except SystemExit as exc:
        # sys.exit は BaseException 側なので except Exception を素通りする。
        # 通すとこの検査自身が黙って終了コード 0 で終わる
        return None, (
            f"called sys.exit({exc.code!r}) on {label} instead of returning findings"
        )
    except Exception as exc:  # noqa: BLE001 - 例外の種類ではなく契約を見る
        return None, f"raised {type(exc).__name__} on {label} instead of returning findings"
    if not isinstance(errors, list):
        return None, f"returned {type(errors).__name__} on {label} instead of a list"
    bad = [item for item in errors if not isinstance(item, str) or not item]
    if bad:
        return None, (
            f"returned a finding that is not a non-empty str on {label} ({bad[0]!r})"
        )
    return errors, None


def _snapshot(repo: Path, into: Path) -> Path:
    root = into / "repo"
    shutil.copytree(repo, root, ignore=SNAPSHOT_IGNORE, symlinks=True)
    return root


def _break_subject(root: Path, subject: str, *, empty: bool) -> None:
    """正常な複製の中で、対象だけを壊す。file / dir は実在から判定する。

    空にするときは削除して作り直さない。mode bit を落とすと、権限だけ見て
    中身の空を無視する checker が「空の対象」probe をすり抜けられる。
    """
    target = root / subject
    was_dir = target.is_dir() and not target.is_symlink()
    if not empty:
        if was_dir:
            shutil.rmtree(target)
        else:
            target.unlink()
        return
    if was_dir:
        for child in list(target.iterdir()):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        return
    # 既存 file を truncate すれば mode は残る (作り直しは 0o644 になる)
    target.write_text("", encoding="utf-8")


def _probe(load: Callable[[], ModuleType], repo: Path, subject: str) -> list[str]:
    """正常な複製から対象だけを壊して食わせる。問題があればその説明を返す。

    変種ごとに `load()` で新しい module を取る。同一 instance を使い回すと、
    module 級の呼び出し状態を持つ checker が「1 回目は []、以降は拒否」で
    負例 probe をすり抜けられる。
    """
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        clean = _snapshot(repo, Path(tmp) / "clean")
        errors, problem = _call(load(), clean, "a valid repository")
        if problem is not None:
            return [problem]
        if errors:
            # ここが汚れていると、以降の所見が変異のせいだと言えない
            return [
                "reports findings on a valid repository, so the probes below "
                f"cannot be attributed to the mutation ({errors[0]})"
            ]

    for empty in (False, True):
        label = "an empty subject" if empty else "a missing subject"
        with tempfile.TemporaryDirectory() as tmp:
            root = _snapshot(repo, Path(tmp) / str(int(empty)))
            # 複製の中でも改めて見る。repo 側で通っても複製で symlink になりうる
            escape = _symlink_component(root, subject)
            if escape is not None:
                problems.append(escape)
                break
            try:
                _break_subject(root, subject, empty=empty)
            except OSError as exc:
                # ここで例外を上げると、この検査が他へ課している契約
                # (所見を list で返す) を自分で破ることになる
                problems.append(f"the probe could not break {subject} ({exc})")
                continue
            errors, problem = _call(load(), root, label)
            if problem is not None:
                problems.append(problem)
            elif not errors:
                problems.append(f"accepted {label} (returned no findings)")
    return problems


def verify(repo: Path) -> list[str]:
    errors: list[str] = []
    scripts_root = repo / SCRIPTS_DIRNAME
    if not scripts_root.is_dir():
        return [f"{SCRIPTS_DIRNAME}/ not found"]

    checkers = sorted(
        path for path in scripts_root.glob(CHECKER_GLOB) if path.name != SELF_NAME
    )
    if not checkers:
        # 0 件を pass にすると、この検査自身がまさに塞ごうとしている型になる
        return [f"{SCRIPTS_DIRNAME}/ contains no {CHECKER_GLOB} to check"]

    for path in checkers:
        rel = path.relative_to(repo).as_posix()
        try:
            module = _load(path)
        except SystemExit as exc:
            errors.append(f"{rel}: called sys.exit({exc.code!r}) at import time")
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel}: cannot be imported ({type(exc).__name__}: {exc})")
            continue

        subject = getattr(module, "SUBJECT", None)
        if not isinstance(subject, str) or not subject:
            errors.append(
                f"{rel}: must declare SUBJECT (the repo-relative path it inspects)"
            )
            continue
        subject_problem = _subject_error(subject)
        if subject_problem is not None:
            errors.append(f"{rel}: {subject_problem}")
            continue
        if not callable(getattr(module, "verify", None)):
            errors.append(f"{rel}: must expose verify(repo) -> list[str]")
            continue
        escape = _symlink_component(repo, subject)
        if escape is not None:
            errors.append(f"{rel}: {escape}")
            continue
        if not (repo / subject).exists():
            errors.append(f"{rel}: declares SUBJECT {subject} which is not in this repository")
            continue

        # SUBJECT 等の宣言確認は上で済んだ。probe は変種ごとに再読込する
        errors.extend(
            f"{rel}: {problem}"
            for problem in _probe(lambda p=path: _load(p), repo, subject)
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    # checker は src/ の実装を読むものがあるので、import path を揃える
    src = str(repo / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    errors = verify(repo)
    if args.json:
        print(
            json.dumps(
                {
                    "schema": "github-ops/checker-contracts/v1",
                    "status": "fail" if errors else "pass",
                    "read_only": True,
                    "error_count": len(errors),
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for error in errors:
            print(error)
        if not errors:
            print("checker contracts: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
