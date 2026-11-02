from pathlib import Path

import pytest

from github_ops.account_map import AccountMap, AccountMapError, load_account_map


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


def test_unmapped_own_repo_derives_account_from_registered_owner() -> None:
    account_map = AccountMap(
        accounts={"nexus": {"expected_login": "nexus-ai-2045"}},
        repositories={},
    )

    resolved = account_map.resolve("nexus-ai-2045/nexus-ai-skills")

    assert resolved.account_label == "nexus"
    assert resolved.expected_owner == "nexus-ai-2045"
    assert resolved.expected_login == "nexus-ai-2045"


def test_unmapped_owner_derivation_fails_closed_when_login_is_ambiguous() -> None:
    account_map = AccountMap(
        accounts={
            "first": {"expected_login": "nexus-ai-2045"},
            "second": {"expected_login": "nexus-ai-2045"},
        },
        repositories={},
    )

    with pytest.raises(AccountMapError, match="matches multiple accounts"):
        account_map.resolve("nexus-ai-2045/nexus-ai-skills")


def test_schema_violation_fails_closed() -> None:
    with pytest.raises(AccountMapError, match="schema validation failed"):
        load_account_map(FIXTURES / "account-map.invalid.yaml")
