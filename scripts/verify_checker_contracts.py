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

`scripts/verify_*.py` を列挙し、それぞれについて 2 つの壊れた repo を作って
実際に `verify()` を呼ぶ。**宣言を読むのではなく実行して確かめる。**

1. 対象 (`SUBJECT`) が存在しない repo
2. 対象は存在するが空 (空ディレクトリ / 空ファイル) の repo

どちらでも所見が空なら「空振りを pass にした」として落とす。
例外が出た場合も落とす (所見を list で返す契約が破れているため)。

## checker 側に要求する宣言

- `SUBJECT`: 検査対象の repo 相対 path (str)
- `verify(repo: Path) -> list[str]`

read-only。標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType


SCRIPTS_DIRNAME = "scripts"
CHECKER_GLOB = "verify_*.py"
SELF_NAME = Path(__file__).name


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot create a spec for {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_broken_repo(root: Path, subject: str, *, present: bool) -> None:
    """対象が無い repo / 対象はあるが空の repo を作る。"""
    if not present:
        return
    target = root / subject
    if target.suffix:
        # file 形式の対象は空ファイルにする
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    else:
        target.mkdir(parents=True, exist_ok=True)


def _probe(module: ModuleType, subject: str, *, present: bool) -> str | None:
    """壊れた repo を 1 つ食わせる。問題があればその説明を返す。"""
    label = "an empty subject" if present else "a missing subject"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_broken_repo(root, subject, present=present)
        try:
            errors = module.verify(root)
        except Exception as exc:  # noqa: BLE001 - 例外の種類ではなく契約を見る
            return (
                f"raised {type(exc).__name__} on {label} "
                "instead of returning findings"
            )
        if not isinstance(errors, list):
            return f"returned {type(errors).__name__} on {label} instead of a list"
        if not errors:
            return f"accepted {label} (returned no findings)"
    return None


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
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{rel}: cannot be imported ({type(exc).__name__}: {exc})")
            continue

        subject = getattr(module, "SUBJECT", None)
        if not isinstance(subject, str) or not subject:
            errors.append(
                f"{rel}: must declare SUBJECT (the repo-relative path it inspects)"
            )
            continue
        if not callable(getattr(module, "verify", None)):
            errors.append(f"{rel}: must expose verify(repo) -> list[str]")
            continue

        for present in (False, True):
            problem = _probe(module, subject, present=present)
            if problem is not None:
                errors.append(f"{rel}: {problem}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    # checker は src/ の実装を読むものがあるので、import path を揃える
    sys.path.insert(0, str(repo / "src"))
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
