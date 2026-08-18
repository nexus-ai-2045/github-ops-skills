from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from .command import CommandRunner
from .result import Outcome, Status


TOKEN_ENV_NAMES = {"GH_TOKEN", "GITHUB_TOKEN"}


class IdentityProbe:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner()

    def validate_token_login(
        self,
        *,
        expected_login: str,
        token: str,
        expected_host: str | None = None,
        cwd: Path | str | None = None,
    ) -> Outcome:
        result = self.runner.run(
            ["gh", "api", "user", "--jq", ".login"],
            cwd=cwd,
            scoped_env={
                **({"GH_HOST": expected_host} if expected_host else {}),
                "GH_TOKEN": token,
            },
        )
        if result.returncode != 0:
            return Outcome(
                status=Status.UNKNOWN,
                code="token_login_unverified",
                cause="token loginをGitHub APIで確認できませんでした",
                impact="GitHub書き込みは実行できません",
                recovery="network、token有効性、GitHub CLIを確認してください",
                evidence={"api_returncode": result.returncode},
            )
        token_login = result.stdout.strip()
        if token_login != expected_login:
            return Outcome(
                status=Status.BLOCKED,
                code="token_login_mismatch",
                cause="token loginがexpected loginと一致しません",
                impact="GitHub書き込みは実行しません",
                recovery="expected login用のtokenを対象processだけへ渡してください",
                evidence={
                    "expected_login": expected_login,
                    "token_login": token_login,
                },
            )
        return Outcome(
            status=Status.READY,
            code="token_login_verified",
            cause="token loginを確認しました",
            impact="次のread-only preflightへ進めます",
            recovery="none",
            evidence={
                "expected_login": expected_login,
                "token_login": token_login,
            },
        )

    def active_login(
        self,
        *,
        cwd: Path | str | None = None,
        expected_host: str | None = None,
    ) -> tuple[str | None, str | None]:
        result = self.runner.run(
            ["gh", "api", "user", "--jq", ".login"],
            cwd=cwd,
            unset_env=TOKEN_ENV_NAMES,
            scoped_env={"GH_HOST": expected_host} if expected_host else None,
        )
        if result.returncode != 0:
            return None, result.stderr.strip() or "active loginを確認できません"
        login = result.stdout.strip()
        return (login or None), None if login else "active loginが空です"

    def probe(
        self,
        repo: Path,
        *,
        expected_owner: str | None = None,
        expected_login: str | None = None,
        token: str | None = None,
        expected_host: str | None = None,
    ) -> Outcome:
        resolved_repo = repo.resolve()
        remote = self.runner.run(
            ["git", "remote", "get-url", "origin"],
            cwd=resolved_repo,
        )
        if remote.returncode != 0:
            return Outcome(
                status=Status.UNKNOWN,
                code="remote_unavailable",
                cause="origin remoteを確認できません",
                impact="対象GitHub repositoryを確定できません",
                recovery="originを設定するか、対象repositoryを明示してください",
                evidence={"repo": resolved_repo.name},
            )
        owner, name = parse_github_remote(remote.stdout.strip())
        if not owner or not name:
            return Outcome(
                status=Status.BLOCKED,
                code="unsupported_remote",
                cause="originをGitHub owner/nameへ解決できません",
                impact="GitHub操作は実行しません",
                recovery="HTTPSまたはSSHのGitHub remoteを確認してください",
                evidence={"remote_kind": "unsupported"},
            )
        if expected_owner and owner != expected_owner:
            return Outcome(
                status=Status.BLOCKED,
                code="remote_owner_mismatch",
                cause="remote ownerがexpected ownerと一致しません",
                impact="GitHub操作は実行しません",
                recovery="account mapまたはremoteを確認してください",
                evidence={"expected_owner": expected_owner, "remote_owner": owner},
            )

        credential_username: str | None = None
        ssh_login: str | None = None
        if expected_login and remote.stdout.strip().startswith("https://"):
            credential = self.runner.run(
                ["git", "credential", "fill"],
                cwd=resolved_repo,
                input_text=(
                    "protocol=https\n"
                    "host=github.com\n"
                    f"path={owner}/{name}.git\n\n"
                ),
                redact_stdout=False,
            )
            if credential.returncode != 0:
                return Outcome(
                    status=Status.UNKNOWN,
                    code="credential_unavailable",
                    cause="Git credentialを確認できません",
                    impact="git pushの実行名義を確定できないため書き込みを止めています",
                    recovery="GitHub credential helperを確認してください",
                    evidence={"repository": f"{owner}/{name}"},
                )
            credential_fields = dict(
                line.split("=", 1)
                for line in credential.stdout.splitlines()
                if "=" in line
            )
            credential_username = credential_fields.get("username")
            credential_token = credential_fields.get("password")
            if not credential_token:
                return Outcome(
                    status=Status.UNKNOWN,
                    code="credential_token_unavailable",
                    cause="Git credential tokenを取得できません",
                    impact="git pushの認証accountを確定できないため書き込みを止めています",
                    recovery="GitHub credential helperを確認してください",
                    evidence={"repository": f"{owner}/{name}"},
                )
            credential_token_outcome = self.validate_token_login(
                expected_login=expected_login,
                token=credential_token,
                expected_host=expected_host or "github.com",
                cwd=resolved_repo,
            )
            if credential_token_outcome.status is not Status.READY:
                return credential_token_outcome
        elif expected_login and remote.stdout.strip().startswith("git@github.com:"):
            ssh_identity = self.runner.run(
                [
                    "ssh",
                    "-T",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=10",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "git@github.com",
                ],
                cwd=resolved_repo,
            )
            message = "\n".join((ssh_identity.stdout, ssh_identity.stderr))
            match = re.search(
                r"Hi (?P<login>[^!\r\n]+)! You've successfully authenticated",
                message,
            )
            if not match:
                return Outcome(
                    status=Status.UNKNOWN,
                    code="ssh_login_unverified",
                    cause="SSH pushに使用するGitHub loginを確認できません",
                    impact="git pushの認証accountを確定できないため書き込みを止めています",
                    recovery="ssh -T git@github.com とSSH key設定を確認してください",
                    evidence={"repository": f"{owner}/{name}"},
                )
            ssh_login = match.group("login")
            if ssh_login != expected_login:
                return Outcome(
                    status=Status.BLOCKED,
                    code="ssh_login_mismatch",
                    cause="SSH push loginがexpected loginと一致しません",
                    impact="git pushを別accountで実行する事故を止めています",
                    recovery="対象account用のSSH keyまたはhost設定を使用してください",
                    evidence={
                        "expected_login": expected_login,
                        "ssh_login": ssh_login,
                    },
                )

        if token and expected_login:
            token_outcome = self.validate_token_login(
                expected_login=expected_login,
                token=token,
                expected_host=expected_host,
                cwd=resolved_repo,
            )
            if token_outcome.status is not Status.READY:
                return token_outcome
            login = token_outcome.evidence["token_login"]
            mode = "validated-token"
        else:
            login, error = self.active_login(
                cwd=resolved_repo, expected_host=expected_host
            )
            if error:
                return Outcome(
                    status=Status.UNKNOWN,
                    code="active_login_unverified",
                    cause="global active loginを確認できません",
                    impact="GitHub操作は実行しません",
                    recovery="gh auth statusとkeyringを確認してください",
                    evidence={"repository": f"{owner}/{name}"},
                )
            if expected_login and login != expected_login:
                return Outcome(
                    status=Status.BLOCKED,
                    code="active_login_mismatch",
                    cause="global active loginがexpected loginと一致しません",
                    impact="GitHub操作は実行しません",
                    recovery="validated-token modeを使用してください",
                    evidence={
                        "expected_login": expected_login,
                        "active_login": login,
                    },
                )
            mode = "global-active"

        return Outcome(
            status=Status.READY,
            code="identity_verified",
            cause="repositoryとGitHub loginを確認しました",
            impact="read-only repository preflightへ進めます",
            recovery="none",
            evidence={
                "repository": f"{owner}/{name}",
                "remote_owner": owner,
                "login": login,
                "identity_mode": mode,
                "credential_username": credential_username
                if remote.stdout.strip().startswith("https://")
                else None,
                "ssh_login": ssh_login
                if remote.stdout.strip().startswith("git@github.com:")
                else None,
            },
        )


def parse_github_remote(remote_url: str) -> tuple[str | None, str | None]:
    ssh_match = re.fullmatch(
        r"git@github\.com:(?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?",
        remote_url,
    )
    if ssh_match:
        return ssh_match.group("owner"), ssh_match.group("name")
    parsed = urlparse(remote_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
    ):
        return None, None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1].removesuffix(".git")
