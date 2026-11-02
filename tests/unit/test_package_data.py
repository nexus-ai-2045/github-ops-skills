from pathlib import Path

import yaml

from github_ops.account_map import _default_schema_path


def test_packaged_account_map_schema_exists_and_matches_repository_copy() -> None:
    packaged = _default_schema_path()
    repository = Path(__file__).resolve().parents[2] / "schemas" / packaged.name

    assert packaged.is_file()
    assert yaml.safe_load(packaged.read_text(encoding="utf-8")) == yaml.safe_load(
        repository.read_text(encoding="utf-8")
    )
