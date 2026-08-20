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
from urllib.parse import urlparse


COMMAND_TIMEOUT_SECONDS = 30


def run(
    cmd: list[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            input=input_text,
            env=env,
            shell=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        return (
            124,
            stdout.strip(),
            f"command timed out after {COMMAND_TIMEOUT_SECONDS}s",
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return 127, "", f"command failed: {exc}"
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

    def owner_repo(path: str) -> tuple[str | None, str | None]:
        if path.startswith("/"):
            path = path[1:]
        if path.endswith("/"):
            return None, None
        parts = path.split("/")
        if len(parts) != 2 or any(
            not part or any(char.isspace() for char in part) for part in parts
        ):
            return None, None
        owner, repo = parts
        if repo.endswith(".git"):
            repo = repo[:-4]
        return (owner, repo) if owner and repo else (None, None)

    # The scp-like SSH form is not a URL, so parse it with a strict full match.
    scp_match = re.fullmatch(r"git@github\.com:(?P<path>[^\s?#]+)", remote_url)
    if scp_match:
        return owner_repo(scp_match.group("path"))

    try:
        parsed = urlparse(remote_url)
        hostname = parsed.hostname
    except ValueError:
        return None, None
    if hostname != "github.com" or parsed.query or parsed.fragment:
        return None, None
    if (
        parsed.scheme.lower() == "https"
        and not parsed.username
        and not parsed.password
    ):
        return owner_repo(parsed.path)
    if (
        parsed.scheme.lower() == "ssh"
        and parsed.username == "git"
        and not parsed.password
    ):
        return owner_repo(parsed.path)
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


def git_credential_login(
    cwd: Path, remote_url: str | None
) -> tuple[str | None, str | None, str | None]:
    parsed = urlparse(remote_url or "")
    if parsed.scheme.casefold() != "https" or parsed.hostname != "github.com":
        return None, None, None
    code, out, err = run(
        ["git", "credential", "fill"],
        cwd,
        input_text=(
            f"protocol=https\nhost=github.com\npath={parsed.path.lstrip('/')}\n\n"
        ),
    )
    if code != 0:
        return None, None, err or "git credential fill failed"
    fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    token = fields.get("password")
    if not token:
        return fields.get("username"), None, "credential token is unavailable"
    token_env = os.environ.copy()
    token_env.pop("GITHUB_TOKEN", None)
    token_env["GH_TOKEN"] = token
    token_env["GH_HOST"] = "github.com"
    code, login, err = run(
        ["gh", "api", "user", "--jq", ".login"], cwd, env=token_env
    )
    if code != 0 or not login:
        return fields.get("username"), None, err or "credential identity lookup failed"
    return fields.get("username"), login, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe gh active identity against a local GitHub repo.")
    parser.add_argument("--repo", default=".", help="local repository root")
    parser.add_argument("--expected-owner", help="expected GitHub repository owner; defaults to remote owner")
    parser.add_argument("--expected-login", help="expected authenticated GitHub login")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    cwd = Path(args.repo).resolve()
    remote_url = git_value(cwd, "remote", "get-url", "origin")
    remote_owner, remote_repo = parse_remote_owner(remote_url)
    expected_owner = args.expected_owner or remote_owner
    expected_login = args.expected_login
    credential_username, credential_login, credential_error = git_credential_login(
        cwd, remote_url
    )
    credential_required = bool(
        expected_login and urlparse(remote_url or "").scheme.casefold() == "https"
    )
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
        # Never expose URL userinfo, query, or fragments. The strict parser
        # already reduced a supported remote to owner/repository.
        "remote_url": {"status": "ok" if remote_url else "error", "value": repo_full_name},
        "remote_owner": {
            "status": "ok" if remote_owner and remote_owner == expected_owner else "error",
            "value": remote_owner,
        },
        "expected_owner": {"status": "ok" if expected_owner else "error", "value": expected_owner},
        "gh_active_login": {
            "status": "ok" if active_login and (not expected_login or active_login == expected_login) else "error",
            "value": active_login,
            "detail": active_error,
        },
        "credential_username": {
            # HTTPS usernames (including x-access-token) are not identities;
            # verify the effective credential token through the API instead.
            "status": "ok" if (
                not credential_required or credential_login == expected_login
            ) else "error",
            "value": credential_username,
            "detail": credential_error,
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
    if expected_login and active_login and active_login != expected_login:
        next_command = f"gh auth switch --hostname github.com --user {expected_login}"
    elif expected_login and not active_login:
        next_command = f"gh auth login --hostname github.com --git-protocol https  # then select/login {expected_login}"

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
