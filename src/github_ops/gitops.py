from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .command import CommandRunner
from .identity import IdentityProbe
from .result import Outcome, Status


class GitOpsConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DesiredRepositoryState:
    repository: str
    settings: dict[str, Any]


FIELD_MAP = {
    "visibility": "visibility",
    "default_branch": "defaultBranchRef.name",
    "description": "description",
    "issues_enabled": "hasIssuesEnabled",
    "wiki_enabled": "hasWikiEnabled",
    "discussions_enabled": "hasDiscussionsEnabled",
    "projects_enabled": "hasProjectsEnabled",
}


def load_desired_state(
    path: Path, *, schema_path: Path | None = None
) -> DesiredRepositoryState:
    schema_file = schema_path or _default_schema_path()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema = yaml.safe_load(schema_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GitOpsConfigError(f"desired stateを読み込めません: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(schema, dict):
        raise GitOpsConfigError("desired stateとschemaのrootはmappingである必要があります")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        summary = "; ".join(error.message for error in errors)
        raise GitOpsConfigError(f"schema検証に失敗しました: {summary}")
    return DesiredRepositoryState(
        repository=payload["repository"], settings=dict(payload["settings"])
    )


def compare_repository_state(
    desired: DesiredRepositoryState, actual: dict[str, Any]
) -> Outcome:
    actual_repository = actual.get("nameWithOwner")
    evidence: dict[str, Any] = {
        "repository": desired.repository,
        "actual_repository": actual_repository,
        "checked_settings": sorted(desired.settings),
    }
    if actual_repository != desired.repository:
        return Outcome(
            status=Status.BLOCKED,
            code="gitops_repository_mismatch",
            cause="観測したrepositoryがdesired stateと一致しません",
            impact="drift判定とGitHub変更案の作成を停止します",
            recovery="設定ファイルと取得対象repositoryを確認してください",
            evidence=evidence,
        )

    drift = []
    for desired_name, desired_value in desired.settings.items():
        actual_value = _read_field(actual, FIELD_MAP[desired_name])
        if actual_value != desired_value:
            drift.append(
                {
                    "setting": desired_name,
                    "desired": desired_value,
                    "actual": actual_value,
                }
            )
    evidence["drift"] = drift
    if drift:
        return Outcome(
            status=Status.BLOCKED,
            code="gitops_drift_detected",
            cause=f"GitHub設定に{len(drift)}件のdriftがあります",
            impact="自動修復せず、承認可能な差分として報告します",
            recovery="差分を人が確認し、別の書き込みpreflightを通してください",
            evidence=evidence,
        )
    return Outcome(
        status=Status.READY,
        code="gitops_in_sync",
        cause="GitHub設定はGit内のdesired stateと一致しています",
        impact="追加の同期操作は不要です",
        recovery="none",
        evidence=evidence,
    )


class RepositoryStateProbe:
    def __init__(
        self,
        runner: CommandRunner | None = None,
        identity_probe: IdentityProbe | None = None,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.identity_probe = identity_probe or IdentityProbe(self.runner)

    def reconcile(self, desired: DesiredRepositoryState, repo: Path) -> Outcome:
        identity = self.identity_probe.probe(
            repo, expected_owner=desired.repository.split("/", 1)[0]
        )
        if identity.status is not Status.READY:
            return identity
        fields = sorted({path.split(".", 1)[0] for path in FIELD_MAP.values()} | {"nameWithOwner"})
        result = self.runner.run(
            [
                "gh",
                "repo",
                "view",
                desired.repository,
                "--json",
                ",".join(fields),
            ],
            cwd=repo,
        )
        if result.returncode != 0:
            return Outcome(
                status=Status.UNKNOWN,
                code="gitops_remote_state_unknown",
                cause="GitHubの現在設定を取得できません",
                impact="drift判定は完了していません",
                recovery="network、権限、GitHub CLIの状態を確認してください",
                evidence={
                    "repository": desired.repository,
                    "api_returncode": result.returncode,
                },
            )
        try:
            actual = json.loads(result.stdout)
        except json.JSONDecodeError:
            return Outcome(
                status=Status.UNKNOWN,
                code="gitops_remote_state_invalid",
                cause="GitHubの応答をJSONとして解釈できません",
                impact="drift判定は完了していません",
                recovery="GitHub CLIの出力とバージョンを確認してください",
                evidence={"repository": desired.repository},
            )
        return compare_repository_state(desired, actual)


def _read_field(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _default_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "github-repository-state.schema.yaml"
