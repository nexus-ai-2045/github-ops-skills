from __future__ import annotations

import re
from pathlib import Path

from .result import Outcome, Status


RULES = {
    "windows_home_path": re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\/\s]+"),
    "macos_home_path": re.compile(r"/Users/[^/\s]+"),
    "linux_home_path": re.compile(r"/home/[^/\s]+"),
    "classic_github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "fine_grained_github_token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "bearer_token": re.compile(r"(?i)Authorization:\s*Bearer\s+\S+"),
}


def scan_text(text: str) -> Outcome:
    matched = sorted(name for name, pattern in RULES.items() if pattern.search(text))
    if matched:
        return Outcome(
            status=Status.BLOCKED,
            code="identity_exposure_detected",
            cause="公開候補にidentityまたはsecretのpatternがあります",
            impact="公開・pushへ進めません",
            recovery="rule名に対応する値を除去または匿名化してください",
            evidence={"rules": matched},
        )
    return Outcome(
        status=Status.READY,
        code="identity_scan_ready",
        cause="identityとsecretのpatternは検出されませんでした",
        impact="次の公開準備checkへ進めます",
        recovery="none",
        evidence={"rules_scanned": sorted(RULES)},
    )


def scan_repository_for_personal_paths(root: Path) -> list[str]:
    names = {"windows_home_path", "macos_home_path", "linux_home_path"}
    return _scan_repository(root, names)


def scan_repository_for_token_shapes(root: Path) -> list[str]:
    names = {
        "classic_github_token",
        "fine_grained_github_token",
        "bearer_token",
    }
    return _scan_repository(root, names)


def _scan_repository(root: Path, rule_names: set[str]) -> list[str]:
    offenders: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(
            part in {".git", ".venv", "__pycache__", ".pytest_cache"}
            for part in path.parts
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(RULES[name].search(text) for name in rule_names):
            offenders.append(path.relative_to(root).as_posix())
    return offenders
