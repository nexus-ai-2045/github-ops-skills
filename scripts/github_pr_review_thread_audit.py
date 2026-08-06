#!/usr/bin/env python3
"""Read-only PR review thread audit CLI.

Existing helper absorbed into this Core Suite. Does not merge, approve, or
mutate GitHub state.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.output import configure_utf8_stdout
from github_ops.review_threads import error_result, fetch, summarize


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Repository in owner/name format.")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdout()
    args = parse_args(argv)
    try:
        result = summarize(fetch(args.repo, args.pr))
    except ValueError as exc:
        result = error_result(str(exc))
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        result = error_result(f"gh_api_failed: {detail}")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        result = error_result(f"unexpected_github_response: {exc}")

    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "decision={decision} unresolved_current={current} unresolved_outdated={outdated}".format(
                decision=result.decision,
                current=result.unresolved_current,
                outdated=result.unresolved_outdated,
            )
        )
        for thread in result.threads:
            if thread.state != "resolved":
                print(f"{thread.state}: {thread.path}:{thread.line or '-'} {thread.title}")
    return 0 if result.decision == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
