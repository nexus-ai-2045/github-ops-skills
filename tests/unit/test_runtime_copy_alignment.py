from pathlib import Path

import yaml


def test_every_skill_copies_the_same_files_to_grok_as_claude() -> None:
    root = Path(__file__).resolve().parents[2] / "skills"
    skills = sorted(path for path in root.iterdir() if path.is_dir())
    assert [path.name for path in skills] == [
        "commit-push-pr",
        "cross-repo-wip-ownership",
        "github-cli-ops-guard",
        "post-merge-closeout",
        "pr-convergence-loop",
        "pr-status",
        "public-repo-readiness",
        "review-pr",
    ]
    for skill in skills:
        manifest_path = skill / "manifest.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        runtimes = data["runtimes"]
        claude = runtimes["claude"]
        grok = runtimes["grok"]
        assert claude["mode"] == "copy"
        assert grok["mode"] == "copy"
        assert grok.get("files") == claude.get("files")
