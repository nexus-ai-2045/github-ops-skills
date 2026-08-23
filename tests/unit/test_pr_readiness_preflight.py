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


def test_worktree_reader_preserves_raw_output_and_fails_closed() -> None:
    class Runner:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.calls = []

        def run(self, command, **kwargs):
            self.calls.append((command, kwargs))
            return type("Result", (), {"returncode": self.returncode, "stdout": self.stdout})()

    raw = " M ghp_" + ("A" * 24) + "\0"
    ready = Runner(0, raw)
    assert MODULE._read_worktree_paths(ready, Path(".")) == (raw[3:-1],)
    assert ready.calls[0][1]["redact_stdout"] is False
    assert MODULE._read_worktree_paths(Runner(1, ""), Path(".")) is None
