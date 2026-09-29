from pathlib import Path


def test_push_wrapper_discovery_uses_portable_home_path() -> None:
    skill = Path(__file__).resolve().parents[2] / "skills" / "commit-push-pr" / "SKILL.md"
    body = skill.read_text(encoding="utf-8")

    assert "`$HOME/Projects/shared/scripts/cc-push-resolved.sh`" in body
    assert "`~/Projects/shared/scripts/cc-push-resolved.sh`" not in body
