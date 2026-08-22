from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from .command import CommandRunner
from .redaction import redact
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
            redact_stdout=False,
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
        remote_url = remote.stdout.strip()
        try:
            parsed_remote = urlparse(remote_url)
        except ValueError:
            parsed_remote = None
        if parsed_remote is not None and parsed_remote.scheme.casefold() == "https" and (
            parsed_remote.username is not None or parsed_remote.password is not None
        ):
            return Outcome(
                status=Status.BLOCKED,
                code="embedded_remote_credential_unsupported",
                cause="origin URLにcredentialが埋め込まれています",
                impact="remote URLとcredential helperで別identityを使う事故を止めています",
                recovery="credentialをURLから除去し、Git credential helperを使用してください",
                evidence={"remote_kind": "https_with_userinfo"},
            )
        owner, name = parse_github_remote(remote_url)
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

        push_url = remote.stdout.strip()
        if expected_login:
            push_remote = self.runner.run(
                ["git", "remote", "get-url", "--all", "--push", "origin"],
                cwd=resolved_repo,
                redact_stdout=False,
            )
            if push_remote.returncode != 0:
                return Outcome(
                    status=Status.UNKNOWN,
                    code="push_remote_unavailable",
                    cause="originの実効push URLを確認できません",
                    impact="実際のpush先を確定できないため書き込みを止めています",
                    recovery="remote.origin.pushurlとorigin URLを確認してください",
                    evidence={"repository": f"{owner}/{name}"},
                )
            push_urls = [line.strip() for line in push_remote.stdout.splitlines() if line.strip()]
            if len(push_urls) != 1:
                return Outcome(
                    status=Status.BLOCKED,
                    code="push_remote_count_unsupported",
                    cause="originの実効push URLが1つに確定していません",
                    impact="複数または空のpush先への書き込みを止めています",
                    recovery="originのpush URLを対象repository 1件へ限定してください",
                    evidence={"push_url_count": len(push_urls)},
                )
            push_url = push_urls[0]
            try:
                parsed_push_candidate = urlparse(push_url)
            except ValueError:
                parsed_push_candidate = None
            if parsed_push_candidate is not None and parsed_push_candidate.scheme.casefold() == "https" and (
                parsed_push_candidate.username is not None
                or parsed_push_candidate.password is not None
            ):
                return Outcome(
                    status=Status.BLOCKED,
                    code="embedded_push_credential_unsupported",
                    cause="push URLにcredentialが埋め込まれています",
                    impact="push URLとcredential helperで別identityを使う事故を止めています",
                    recovery="credentialをpush URLから除去し、Git credential helperを使用してください",
                    evidence={"push_remote_kind": "https_with_userinfo"},
                )
            push_owner, push_name = parse_github_remote(push_url)
            if not push_owner or not push_name:
                return Outcome(
                    status=Status.BLOCKED,
                    code="unsupported_push_remote",
                    cause="push URLをGitHub owner/nameへ解決できません",
                    impact="未検証のpush先への書き込みを止めています",
                    recovery="HTTPSまたはSSHのGitHub push URLを使用してください",
                    evidence={"push_remote_kind": "unsupported"},
                )
            if (push_owner, push_name) != (owner, name):
                return Outcome(
                    status=Status.BLOCKED,
                    code="push_repository_mismatch",
                    cause="push先repositoryがfetch先と一致しません",
                    impact="別repositoryへの誤pushを止めています",
                    recovery="remote.origin.pushurlをfetch先と同じrepositoryへ修正してください",
                    evidence={
                        "fetch_repository": f"{owner}/{name}",
                        "push_repository": f"{push_owner}/{push_name}",
                    },
                )

        credential_username: str | None = None
        ssh_login: str | None = None
        try:
            parsed_push_transport = urlparse(push_url)
        except ValueError:
            return Outcome(
                status=Status.BLOCKED,
                code="unsupported_push_remote",
                cause="push URLを安全に解析できません",
                impact="未検証のpush先への書き込みを止めています",
                recovery="HTTPSまたはSSHのGitHub push URLを使用してください",
                evidence={"push_remote_kind": "unsupported"},
            )
        push_is_https = parsed_push_transport.scheme.casefold() == "https"
        push_is_ssh = bool(re.fullmatch(r"git@github\.com:.+", push_url)) or (
            parsed_push_transport.scheme.casefold() == "ssh"
            and parsed_push_transport.hostname == "github.com"
            and parsed_push_transport.username == "git"
        )
        if expected_login and push_is_https:
            extra_headers = self.runner.run(
                [
                    "git",
                    "config",
                    "--get-regexp",
                    r"^http\..*\.extraheader$|^http\.extraheader$",
                ],
                cwd=resolved_repo,
            )
            if extra_headers.returncode not in {0, 1}:
                return Outcome(
                    status=Status.UNKNOWN,
                    code="http_auth_override_unverified",
                    cause="Git HTTP header overrideを確認できません",
                    impact="HTTPS pushの実効identityを確定できないため書き込みを止めています",
                    recovery="Git HTTP設定を確認してください",
                    evidence={"repository": f"{owner}/{name}"},
                )
            if extra_headers.returncode == 0 and "authorization:" in extra_headers.stdout.casefold():
                return Outcome(
                    status=Status.BLOCKED,
                    code="http_auth_override_unsupported",
                    cause="Git HTTP Authorization header overrideが設定されています",
                    impact="credential probeと実際のpushで別identityを使う事故を止めています",
                    recovery="対象scopeのhttp.extraHeaderを解除し、検証済みcredential経路を使用してください",
                    evidence={"repository": f"{owner}/{name}"},
                )
            credential_protocol = parsed_push_transport.scheme.casefold()
            credential_host = parsed_push_transport.hostname or "github.com"
            credential_path = parsed_push_transport.path.lstrip("/")
            credential = self.runner.run(
                ["git", "credential", "fill"],
                cwd=resolved_repo,
                input_text=(
                    f"protocol={credential_protocol}\n"
                    f"host={credential_host}\n"
                    f"path={credential_path}\n\n"
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
        elif expected_login and push_is_ssh:
            ssh_command = self.runner.run(
                ["git", "config", "--get", "core.sshCommand"],
                cwd=resolved_repo,
            )
            if ssh_command.returncode not in {0, 1}:
                return Outcome(
                    status=Status.UNKNOWN,
                    code="ssh_transport_config_unverified",
                    cause="GitのSSH transport設定を確認できません",
                    impact="identity probeとgit pushの実効SSH commandを同一と証明できないため書き込みを止めています",
                    recovery="core.sshCommandとGit設定を確認してください",
                    evidence={"repository": f"{owner}/{name}"},
                )
            override_sources = []
            if ssh_command.returncode == 0 and ssh_command.stdout.strip():
                override_sources.append("core.sshCommand")
            override_sources.extend(
                key for key in ("GIT_SSH_COMMAND", "GIT_SSH") if os.environ.get(key)
            )
            if override_sources:
                return Outcome(
                    status=Status.BLOCKED,
                    code="ssh_transport_override_unsupported",
                    cause="git pushが標準ssh以外のtransport設定を使用します",
                    impact="identity probeと実際のpushで別keyを使う事故を止めています",
                    recovery="SSH overrideを解除するか、検証済みHTTPS token経路を使用してください",
                    evidence={"override_sources": override_sources},
                )
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
                "credential_username": redact(credential_username)
                if push_is_https and credential_username is not None
                else None,
                "ssh_login": ssh_login
                if push_is_ssh
                else None,
                "push_repository": f"{owner}/{name}",
            },
        )


def parse_github_remote(remote_url: str) -> tuple[str | None, str | None]:
    ssh_match = re.fullmatch(
        r"git@github\.com:(?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?",
        remote_url,
    )
    if ssh_match:
        return ssh_match.group("owner"), ssh_match.group("name")
    try:
        parsed = urlparse(remote_url)
    except ValueError:
        return None, None
    if (
        parsed.scheme.casefold() == "ssh"
        and parsed.hostname == "github.com"
        and parsed.username == "git"
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    ):
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) == 2:
            return parts[0], parts[1].removesuffix(".git")
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None, None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        return None, None
    return parts[0], parts[1].removesuffix(".git")
