from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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


def scan_git_tree(runner: CommandRunner, repo: Path, revision: str) -> Outcome:
    listing = runner.run(
        ["git", "ls-tree", "-r", "--name-only", revision],
        cwd=repo,
        timeout=30,
    )
    if listing.returncode != 0:
        return Outcome(
            status=Status.UNKNOWN,
            code="git_range_unverified",
            cause="指定Git treeを確認できません",
            impact="公開・pushへ進めません",
            recovery="revisionとrepositoryを確認してください",
            evidence={"returncode": listing.returncode},
        )
    rules: set[str] = set()
    for relative in listing.stdout.splitlines():
        blob = runner.run(
            ["git", "show", f"{revision}:{relative}"],
            cwd=repo,
            timeout=30,
        )
        if blob.returncode != 0:
            continue
        scanned = scan_text(blob.stdout)
        rules.update(scanned.evidence.get("rules", []))
    if rules:
        return Outcome(
            status=Status.BLOCKED,
            code="identity_exposure_detected",
            cause="公開候補treeにidentityまたはsecretのpatternがあります",
            impact="公開・pushへ進めません",
            recovery="該当ruleを除去して再検査してください",
            evidence={"rules": sorted(rules)},
        )
    return Outcome(
        status=Status.READY,
        code="identity_scan_ready",
        cause="公開候補treeにblocked patternはありません",
        impact="次の公開準備checkへ進めます",
        recovery="none",
        evidence={"revision": revision},
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = CommandRunner()
    outcome = scan_git_tree(runner, args.repo, args.range)
    if outcome.status is not Status.UNKNOWN:
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
