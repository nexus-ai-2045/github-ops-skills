from __future__ import annotations

import argparse
import json
from pathlib import Path

from github_ops.account_map import AccountMapError, load_account_map
from github_ops.identity import IdentityProbe, parse_github_remote
from github_ops.output import configure_utf8_stdout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GitHub account contextをread-onlyで確認します。"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--map-file", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        account_map = load_account_map(args.map_file)
        remote = IdentityProbe().runner.run(
            ["git", "remote", "get-url", "origin"],
            cwd=args.repo,
        )
        owner, name = parse_github_remote(remote.stdout.strip())
        if remote.returncode != 0 or not owner or not name:
            raise AccountMapError("originをowner/nameへ解決できません")
        resolution = account_map.resolve(f"{owner}/{name}")
        outcome = IdentityProbe().probe(
            args.repo,
            expected_owner=resolution.expected_owner,
            expected_login=resolution.expected_login,
        )
        payload = outcome.to_dict()
        payload["account_label"] = resolution.account_label
    except AccountMapError as exc:
        payload = {
            "status": "BLOCKED",
            "code": "account_context_invalid",
            "cause": str(exc),
            "impact": "GitHub操作は実行しません",
            "recovery": "overlayとoriginを確認してください",
            "evidence": {},
        }
    if args.json:
        configure_utf8_stdout()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{payload['status']}: {payload['cause']}")
    return 0 if payload["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
