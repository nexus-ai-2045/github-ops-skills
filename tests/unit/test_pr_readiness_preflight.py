from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "github_pr_readiness_preflight.py"
SPEC = spec_from_file_location("github_pr_readiness_preflight", SCRIPT)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_porcelain_paths_preserve_leading_and_trailing_spaces() -> None:
    assert MODULE._porcelain_paths(" M  leading and trailing \u0000") == (
        " leading and trailing ",
    )


def test_porcelain_paths_include_both_rename_names() -> None:
    assert MODULE._porcelain_paths("R  new name\u0000old name\u0000") == (
        "new name",
        "old name",
    )


def test_porcelain_paths_reject_malformed_record() -> None:
    try:
        MODULE._porcelain_paths("bad\u0000")
    except ValueError as exc:
        assert "porcelain" in str(exc)
    else:
        raise AssertionError("malformed porcelain must fail closed")
