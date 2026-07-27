from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


class AccountMapError(ValueError):
    pass


@dataclass(frozen=True)
class AccountResolution:
    repository: str
    account_label: str
    expected_owner: str
    expected_login: str


@dataclass(frozen=True)
class AccountMap:
    accounts: dict[str, dict[str, str]]
    repositories: dict[str, dict[str, str]]

    def resolve(self, repository: str) -> AccountResolution:
        repo_entry = self.repositories.get(repository)
        if repo_entry is None:
            raise AccountMapError(f"repository is not mapped: {repository}")
        label = repo_entry["account"]
        account = self.accounts.get(label)
        if account is None:
            raise AccountMapError(
                f"repository references an unknown account label: {label}"
            )
        return AccountResolution(
            repository=repository,
            account_label=label,
            expected_owner=repo_entry["expected_owner"],
            expected_login=account["expected_login"],
        )


def load_account_map(
    path: Path,
    *,
    schema_path: Path | None = None,
) -> AccountMap:
    schema_file = schema_path or _default_schema_path()
    try:
        payload = _load_yaml(path)
        schema = _load_yaml(schema_file)
    except (OSError, yaml.YAMLError) as exc:
        raise AccountMapError(f"account map could not be loaded: {exc}") from exc

    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        summary = "; ".join(error.message for error in errors)
        raise AccountMapError(f"schema validation failed: {summary}")

    account_map = AccountMap(
        accounts=dict(payload["accounts"]),
        repositories=dict(payload["repositories"]),
    )
    for repository in account_map.repositories:
        account_map.resolve(repository)
    return account_map


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AccountMapError(f"YAML root must be a mapping: {path.name}")
    return payload


def _default_schema_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "schemas"
        / "account-repo-map.schema.yaml"
    )
