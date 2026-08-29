"""skills/*/manifest.yaml の ssot_pointers がこの repository に実在するか検査する。

manifest は正本の所在を宣言する。しかし宣言を検証する lint
(nexus-ai-skills の shared/scripts/skills_lint.py の L3) はこの repository へ
配布されていない。結果として manifest だけが移植され、宣言先が存在しないまま
CI を通っていた。宣言が届いて執行が届かない、という穴を塞ぐ。

この repository の ssot_pointers は「この repository 内で、その skill の正本に
あたる file」を指す。host workspace 側の script は正本ではなく実行前提なので、
ssot_pointers ではなく SKILL.md の前提条件として書く。

read-only。標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


SKILLS_DIRNAME = "skills"
# 検査対象。verify_checker_contracts.py が空振りを機械で確認する
SUBJECT = SKILLS_DIRNAME
MANIFEST_NAME = "manifest.yaml"
# manifest ヘッダが「この repository の外」を正本と名乗っていないか見る。
# 移植元のヘッダをそのまま持ち込むと、存在しない配布エンジンや lint を指す
FOREIGN_SSOT_RE = re.compile(r"^#.*SSOT:\s*(?!in this repository)(\S+)", re.MULTILINE)


def _pointer_lines(text: str) -> list[str]:
    """ssot_pointers の要素を YAML パーサ無しで拾う。

    このキーは `- value` の平坦なリストだけを取る約束なので、
    依存を増やさずに読む。想定外の入れ子は値として拾わない。
    """
    pointers: list[str] = []
    inside = False
    for raw in text.splitlines():
        if raw.startswith("ssot_pointers:"):
            inside = True
            rest = raw.split(":", 1)[1].strip()
            if rest and rest != "[]":
                # インライン記法は使わない約束。使われたら検査漏れになるので落とす
                raise ValueError("ssot_pointers must use block list form")
            continue
        if not inside:
            continue
        if raw.startswith("  - "):
            pointers.append(raw[4:].strip().strip("\"'"))
            continue
        if raw.strip() and not raw.startswith(" "):
            inside = False
    return pointers


def verify(repo: Path) -> list[str]:
    errors: list[str] = []
    skills_root = repo / SKILLS_DIRNAME
    if not skills_root.is_dir():
        return [f"{SKILLS_DIRNAME}/ not found"]

    manifests = sorted(skills_root.glob(f"*/{MANIFEST_NAME}"))
    if not manifests:
        # 0 件を pass にすると、skill を別の場所へ移した瞬間に保証が空虚に
        # 満たされる。verify_adr_numbering と同じ型 (2026-08-29 review)
        return [f"{SKILLS_DIRNAME}/ contains no {MANIFEST_NAME}"]

    for manifest in manifests:
        rel = manifest.relative_to(repo).as_posix()
        try:
            text = manifest.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{rel}: unreadable ({exc})")
            continue

        for match in FOREIGN_SSOT_RE.finditer(text):
            errors.append(
                f"{rel}: header declares an SSOT outside this repository "
                f"({match.group(1)}). Use '# SSOT in this repository: ...'"
            )

        try:
            pointers = _pointer_lines(text)
        except ValueError as exc:
            errors.append(f"{rel}: {exc}")
            continue

        for pointer in pointers:
            if not pointer:
                continue
            target = (repo / pointer).resolve()
            try:
                target.relative_to(repo.resolve())
            except ValueError:
                errors.append(f"{rel}: ssot_pointer escapes the repository ({pointer})")
                continue
            if not target.exists():
                errors.append(f"{rel}: ssot_pointer does not exist ({pointer})")
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
                    "schema": "github-ops/skill-manifest-pointers/v1",
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
            print("skill manifest pointers: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
