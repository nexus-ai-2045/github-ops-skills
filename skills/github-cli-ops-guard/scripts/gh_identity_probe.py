#!/usr/bin/env python3
"""Read-only GitHub CLI identity probe for multi-account gh workflows."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, shell=False)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def git_value(cwd: Path, *args: str) -> str | None:
    code, out, _ = run(["git", *args], cwd)
    return out if code == 0 and out else None


def git_value_with_origin(cwd: Path, key: str) -> tuple[str | None, str | None]:
    code, out, _ = run(["git", "config", "--show-origin", "--get", key], cwd)
    if code != 0 or not out:
        return None, None
    origin, _, value = out.partition("\t")
    return value or out, origin or None


def parse_remote_owner(remote_url: str | None) -> tuple[str | None, str | None]:
    if not remote_url:
        return None, None
    patterns = [
        r"github\.com[:/](?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?$",
        r"https://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, remote_url)
        if match:
            return match.group("owner"), match.group("repo")
    return None, None


def gh_active_login(cwd: Path) -> tuple[str | None, str | None]:
    code, out, err = run(["gh", "api", "user", "--jq", ".login"], cwd)
    if code == 0 and out:
        return out, None
    status_code, status_out, status_err = run(["gh", "auth", "status", "--hostname", "github.com"], cwd)
    combined = "\n".join(part for part in [status_out, status_err] if part)
    active = None
    for line in combined.splitlines():
        if "Logged in to github.com account" in line:
            match = re.search(r"account\s+([^\s(]+)", line)
            candidate = match.group(1) if match else None
        else:
            candidate = None
        if "Active account: true" in line and active:
            return active, None
        if candidate:
            active = candidate
    return None, err or status_err or f"gh auth status exited {status_code}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe gh active identity against a local GitHub repo.")
    parser.add_argument("--repo", default=".", help="local repository root")
    parser.add_argument("--expected-owner", help="expected GitHub owner/login; defaults to remote owner")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    cwd = Path(args.repo).resolve()
    remote_url = git_value(cwd, "remote", "get-url", "origin")
    remote_owner, remote_repo = parse_remote_owner(remote_url)
    expected_owner = args.expected_owner or remote_owner
    credential_username, credential_origin = git_value_with_origin(cwd, "credential.https://github.com.username")
    branch = git_value(cwd, "branch", "--show-current")
    git_author_name = git_value(cwd, "config", "--get", "user.name")
    git_author_email = git_value(cwd, "config", "--get", "user.email")
    active_login, active_error = gh_active_login(cwd)

    repo_full_name = f"{remote_owner}/{remote_repo}" if remote_owner and remote_repo else None
    repo_view_ok = False
    repo_view_error = None
    visibility = None
    if repo_full_name:
        code, out, err = run(["gh", "repo", "view", repo_full_name, "--json", "nameWithOwner,visibility"], cwd)
        if code == 0 and out:
            repo_view_ok = True
            try:
                repo_json = json.loads(out)
                visibility = repo_json.get("visibility")
            except json.JSONDecodeError:
                repo_view_error = "repo view returned non-json output"
        else:
            repo_view_error = err or "gh repo view failed"

    token_env_present = any(os.environ.get(name) for name in ["GITHUB_TOKEN", "GH_TOKEN"])
    checks = {
        "remote_url": {"status": "ok" if remote_url else "error", "value": remote_url},
        "remote_owner": {"status": "ok" if remote_owner else "error", "value": remote_owner},
        "expected_owner": {"status": "ok" if expected_owner else "error", "value": expected_owner},
        "gh_active_login": {
            "status": "ok" if active_login and (not expected_owner or active_login == expected_owner) else "error",
            "value": active_login,
            "detail": active_error,
        },
        "credential_username": {
            "status": "ok" if not credential_username or not expected_owner or credential_username == expected_owner else "error",
            "value": credential_username,
            "detail": credential_origin,
        },
        "repo_view": {
            "status": "ok" if repo_view_ok else "error",
            "value": repo_full_name,
            "detail": repo_view_error,
        },
        "repo_visibility": {"status": "ok" if visibility else "warning", "value": visibility},
        "token_env": {
            "status": "warning" if token_env_present else "ok",
            "value": "present" if token_env_present else "absent",
            "detail": "GITHUB_TOKEN/GH_TOKEN can override expected gh auth behavior; do not print token values.",
        },
    }
    status = "ok"
    if any(item["status"] == "error" for item in checks.values()):
        status = "error"
    elif any(item["status"] == "warning" for item in checks.values()):
        status = "warning"

    next_command = None
    if expected_owner and active_login and active_login != expected_owner:
        next_command = f"gh auth switch --hostname github.com --user {expected_owner}"
    elif expected_owner and credential_username and credential_username != expected_owner:
        next_command = f"git config --local credential.https://github.com.username {expected_owner}"
    elif expected_owner and not active_login:
        next_command = f"gh auth login --hostname github.com --git-protocol https  # then select/login {expected_owner}"

    result = {
        "status": status,
        "repo": str(cwd),
        "branch": branch,
        "repo_full_name": repo_full_name,
        "checks": checks,
        "git_author": {"name": git_author_name, "email_present": bool(git_author_email)},
        "external_send": False,
        "external_mutation": False,
        "secret_values_printed": False,
        "next_command": next_command,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"gh identity probe: {status}")
        for name, item in checks.items():
            line = f"- {item['status']} {name}: {item.get('value')}"
            if item.get("detail"):
                line += f" ({item['detail']})"
            print(line)
        if next_command:
            print(f"next command: {next_command}")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
