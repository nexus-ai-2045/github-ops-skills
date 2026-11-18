"""雛形の文書 CI と、既存 commit の再開時に守る境界。"""

import textwrap

import pytest

from test_new_repo_bootstrap import TODAY, FakeRunner, _git, _load_module, _plan, _run_real, _scan


def test_first_commit_tracks_workflow_and_runs_its_document_check(tmp_path):
    module = _load_module()
    plan = _plan(module, tmp_path)
    bootstrap = module.Bootstrapper(plan, module.SubprocessRunner(), today=TODAY)
    assert bootstrap._prepare_local()[0] == "ok"
    assert bootstrap._set_identity()[0] == "ok"
    assert bootstrap._scaffold()[0] == "ok"
    assert bootstrap._initial_commit()[0] == "ok"
    workflow = _git(plan.repo_dir, "show", f"HEAD:{module.BOOTSTRAP_WORKFLOW}")
    assert "contents: read" in workflow
    script = textwrap.dedent(workflow.split("      - run: |\n")[1])
    assert _run_real(["sh", "-ec", script], cwd=plan.repo_dir)[0] == 0
    (plan.repo_dir / "SECURITY.md").write_text("", encoding="utf-8")
    assert _run_real(["sh", "-ec", script], cwd=plan.repo_dir)[0] != 0


def test_existing_workflow_is_preserved(tmp_path):
    module = _load_module()
    plan = _plan(module, tmp_path)
    bootstrap = module.Bootstrapper(plan, module.SubprocessRunner(), today=TODAY)
    assert bootstrap._prepare_local()[0] == "ok"
    assert bootstrap._set_identity()[0] == "ok"
    existing = plan.repo_dir / ".github/workflows/custom.yaml"
    existing.parent.mkdir(parents=True)
    content = "name: 既存\non: push\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - run: git --version\n"
    existing.write_text(content, encoding="utf-8")
    assert module.BOOTSTRAP_WORKFLOW not in module.scaffold_docs(plan, today=TODAY)
    assert list(existing.parent.iterdir()) == [existing]
    unrelated = existing.parent / "notes.txt"
    unrelated.write_text("作業メモ", encoding="utf-8")
    assert bootstrap._initial_commit()[0] == "fail"
    assert ".github/workflows/notes.txt" not in _git(plan.repo_dir, "ls-files").splitlines()
    unrelated.unlink()
    assert bootstrap._initial_commit()[0] == "ok"
    assert _git(plan.repo_dir, "show", "HEAD:.github/workflows/custom.yaml") == content.strip()


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_non_regular_workflows_are_rejected(tmp_path, kind):
    module = _load_module()
    plan = _plan(module, tmp_path)
    workflow = plan.repo_dir / ".github/workflows/invalid.yml"
    workflow.parent.mkdir(parents=True)
    if kind == "directory":
        workflow.mkdir()
    else:
        workflow.symlink_to(tmp_path / "outside")
    with pytest.raises(module.BootstrapError, match="通常ファイル"):
        module.scaffold_docs(plan, today=TODAY)


def test_resume_leaves_existing_commit_clean_and_reports_missing_ci(tmp_path):
    module = _load_module()
    plan = _plan(module, tmp_path, preflight_script=tmp_path / "readiness_scan.py")
    bootstrap = module.Bootstrapper(plan, module.SubprocessRunner(), today=TODAY, resume=True)
    assert bootstrap._prepare_local()[0] == "ok"
    assert bootstrap._set_identity()[0] == "ok"
    (plan.repo_dir / "README.md").write_text("既存の初期版", encoding="utf-8")
    _git(plan.repo_dir, "add", "README.md")
    _git(plan.repo_dir, "commit", "-qm", "初期版")
    before = _git(plan.repo_dir, "rev-parse", "HEAD")
    assert bootstrap._scaffold()[0] == "skipped"
    assert bootstrap._initial_commit()[0] == "skipped"
    bootstrap.runner = FakeRunner({("python3",): (1, _scan(False, ci_configuration="unknown"), "")})
    status, detail = bootstrap._readiness_scan()
    assert status == "fail" and "ci_configuration" in detail and "--dry-run" in detail
    assert _git(plan.repo_dir, "rev-parse", "HEAD") == before
    assert _git(plan.repo_dir, "status", "--porcelain") == ""
