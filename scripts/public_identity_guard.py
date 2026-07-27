from __future__ import annotations

import argparse
import json
from pathlib import Path

from github_ops.command import CommandRunner
from github_ops.output import configure_utf8_stdout
from github_ops.public_identity import scan_text
from github_ops.result import Outcome, Status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="公開候補のidentity露出を検査します")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--range", default="HEAD")
    parser.add_argument("--artifact", action="append", type=Path, default=[])
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = CommandRunner()
    show = runner.run(
        ["git", "show", "--format=fuller", "--find-renames", args.range],
        cwd=args.repo,
        timeout=30,
    )
    if show.returncode != 0:
        outcome = Outcome(
            status=Status.UNKNOWN,
            code="git_range_unverified",
            cause="指定Git rangeを確認できません",
            impact="公開・pushへ進めません",
            recovery="rangeとrepositoryを確認してください",
            evidence={"returncode": show.returncode},
        )
    else:
        outcome = scan_text(show.stdout)
        artifact_rules: set[str] = set(outcome.evidence.get("rules", []))
        artifact_files: list[str] = []
        for artifact in args.artifact:
            scanned = scan_text(artifact.read_text(encoding="utf-8"))
            if scanned.status is Status.BLOCKED:
                artifact_rules.update(scanned.evidence["rules"])
                artifact_files.append(artifact.name)
        if artifact_rules:
            outcome = Outcome(
                status=Status.BLOCKED,
                code="identity_exposure_detected",
                cause="公開候補にidentityまたはsecretのpatternがあります",
                impact="公開・pushへ進めません",
                recovery="該当ruleを除去して再検査してください",
                evidence={
                    "rules": sorted(artifact_rules),
                    "artifact_files": sorted(artifact_files),
                },
            )
    if args.json:
        configure_utf8_stdout()
        print(json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"{outcome.status.value}: {outcome.cause}")
    return 0 if outcome.status is Status.READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
