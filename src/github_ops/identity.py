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
        # Remote URL may embed a credential. Parse the raw value, never echo it.
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
        # Existing Core Suite contract (ops-hardening): embedded HTTPS userinfo is
        # not identity proof and must not yield READY.
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

        # Existing ops-hardening contract: when expected_login is set (write path),
        # validate the effective push URL(s), not only the fetch URL.
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
            push_urls = [
                line.strip() for line in push_remote.stdout.splitlines() if line.strip()
            ]
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
            if (
                parsed_push_candidate is not None
                and parsed_push_candidate.scheme.casefold() == "https"
                and (
                    parsed_push_candidate.username is not None
                    or parsed_push_candidate.password is not None
                )
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
        # Redacted or otherwise malformed netloc must stay fail-closed.
        return None, None
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
    owner, name = parts[0], parts[1].removesuffix(".git")
    if not owner or not name or any(char.isspace() for char in owner + name):
        return None, None
    return owner, name
