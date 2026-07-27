from pathlib import Path

import pytest

from github_ops.account_map import AccountMapError, load_account_map


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_resolves_account_by_exact_owner_repo() -> None:
    account_map = load_account_map(FIXTURES / "account-map.valid.yaml")
    resolved = account_map.resolve("example-org/tooling")
    assert resolved.expected_owner == "example-org"
    assert resolved.expected_login == "example-user"
    assert resolved.account_label == "work"


def test_unknown_repo_fails_closed() -> None:
    account_map = load_account_map(FIXTURES / "account-map.valid.yaml")
    with pytest.raises(AccountMapError, match="repository is not mapped"):
        account_map.resolve("example-org/unknown")


def test_schema_violation_fails_closed() -> None:
    with pytest.raises(AccountMapError, match="schema validation failed"):
        load_account_map(FIXTURES / "account-map.invalid.yaml")
