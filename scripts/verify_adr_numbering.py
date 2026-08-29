"""docs/adr/ の ADR 番号が一意で、file 名と本文見出しが一致するか検査する。

ADR は `ADR-0002` のように **path 無しの番号だけ** で参照される
(`PREFLIGHT.md`, `PUBLIC_READY.md`, 他の ADR 本文)。番号が重複すると、
その参照がどちらを指すのか読み手にも機械にも決定できない。
決定記録の同定不能は、記録が無いのとほぼ同じ危険度になる。

nexus-ai-skills の shared/scripts/skills_lint.py と同様、採番を検査する lint は
この repository へ配布されていない。宣言 (docs/adr/) だけが移植されて執行が
届いていない、という穴を塞ぐ。

検査するもの:
  - `NNNN-slug.md` の `NNNN` が重複していないこと
  - 本文 1 行目の見出しが名乗る番号が file 名の番号と一致すること
  - file 名が `NNNN-slug.md` の形をしていること

検査しないもの (非保証):
  - 番号の欠番 (0001, 0003 のような飛びは異常ではない)
  - ADR の内容・Status・相互参照の正しさ
  - path 無し参照がどの ADR を指すつもりだったかの推定

read-only。標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


ADR_DIRNAME = "docs/adr"
# `\d` は Unicode 数字にマッチするため使わない。全角 `０００２` が `\d{4}` を通ると
# key の文字列比較で "0002" とは別番号になり、この検査が塞ぐはずの
# 「番号で同定できない」状態そのものを素通りさせる (2026-08-29 review)
FILENAME_RE = re.compile(r"^([0-9]{4})-(?P<slug>[a-z0-9][a-z0-9-]*)\.md$")
# `# ADR-0002: ...` と `# ADR 0002: ...` の両方が現用。区切りを許容して番号だけ取る
HEADING_RE = re.compile(r"^#\s*ADR[\s-]*([0-9]{4})\b")


def verify(repo: Path) -> list[str]:
    errors: list[str] = []
    adr_root = repo / ADR_DIRNAME
    if not adr_root.is_dir():
        return [f"{ADR_DIRNAME}/ not found"]

    by_number: dict[str, list[str]] = defaultdict(list)
    # glob("*.md") では拾えないものが多すぎる。`0002-B.MD` は Linux の
    # case-sensitive glob で列挙されず (macOS では列挙される = 判定が OS で割れる)、
    # 下位ディレクトリの ADR も見えない。iterdir で全部見て、形が違えば落とす
    entries = sorted(adr_root.iterdir())
    for path in entries:
        rel = path.relative_to(repo).as_posix()
        if path.is_dir():
            errors.append(
                f"{rel}/: ADR must live directly under {ADR_DIRNAME}/, "
                "not in a subdirectory"
            )
            continue
        match = FILENAME_RE.match(path.name)
        if match is None:
            errors.append(f"{rel}: file name must be NNNN-slug.md (lowercase .md)")
            continue
        number = match.group(1)
        by_number[number].append(rel)

        try:
            # BOM を付けるエディタがある。BOM 無しの UTF-8 もこの指定で読める
            first_line = path.read_text(encoding="utf-8-sig").splitlines()[0]
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{rel}: unreadable ({exc})")
            continue
        except IndexError:
            errors.append(f"{rel}: empty file, no ADR heading")
            continue

        heading = HEADING_RE.match(first_line)
        if heading is None:
            errors.append(
                f"{rel}: the first line must be an 'ADR-NNNN:' heading "
                "(no leading blank line)"
            )
        elif heading.group(1) != number:
            errors.append(
                f"{rel}: heading says ADR-{heading.group(1)} "
                f"but the file name says {number}"
            )

    if not entries:
        # 0 件を pass にすると、ADR を別の場所へ移した瞬間に保証が空虚に満たされる
        errors.append(f"{ADR_DIRNAME}/ contains no files")

    for number, paths in sorted(by_number.items()):
        if len(paths) > 1:
            errors.append(
                f"ADR-{number} is claimed by {len(paths)} files ({', '.join(paths)}). "
                "A path-less 'ADR-NNNN' reference cannot resolve"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    errors = verify(repo)
    if args.json:
        print(
            json.dumps(
                {
                    "schema": "github-ops/adr-numbering/v1",
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
            print("adr numbering: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
