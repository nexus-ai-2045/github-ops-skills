from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from github_ops.result import Outcome, Status


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "github_pr_review_thread_resolve.py"
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("resolve_cli", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_cli_surfaces_materials_without_mutating(monkeypatch, capsys) -> None:
    cli = _load_cli()
    payload = {
        "decision": "hold",
        "applied": False,
        "resolved": [],
        "materials": [
            {
                "id": "thread-1",
                "state": "unresolved_current",
                "title": "P1 finding",
            }
        ],
        "errors": [],
        "audit": {"decision": "warn"},
    }
    monkeypatch.setattr(cli, "run_resolve", lambda *args, **kwargs: payload)
    assert cli.main(["--repo", "owner/name", "--pr", "3", "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "hold"
    assert out["applied"] is False
    assert out["materials"][0]["id"] == "thread-1"


def test_resolve_cli_apply_requires_confirm(monkeypatch, capsys) -> None:
    cli = _load_cli()
    called = {"count": 0}

    def fake_run_resolve(*args, **kwargs):
        called["count"] += 1
        return {
            "decision": "ready",
            "applied": True,
            "resolved": [],
            "materials": [],
            "errors": [],
            "audit": {"decision": "pass"},
        }

    monkeypatch.setattr(cli, "run_resolve", fake_run_resolve)
    assert cli.main(["--repo", "owner/name", "--pr", "3", "--apply", "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "error"
    assert out["errors"] == ["approval_missing"]
    assert called["count"] == 0


def test_resolve_cli_apply_runs_identity_preflight(monkeypatch, capsys, tmp_path) -> None:
    cli = _load_cli()
    seen: dict = {}

    class FakeProbe:
        def probe(self, repo, **kwargs):
            seen["repo"] = repo
            seen["kwargs"] = kwargs
            return Outcome(
                status=Status.READY,
                code="identity_verified",
                cause="ok",
                impact="ok",
                recovery="none",
                evidence={"repository": "owner/name", "login": "example-user"},
            )

    monkeypatch.setattr(cli, "IdentityProbe", FakeProbe)

    def fake_run_resolve(*args, **kwargs):
        seen["run"] = kwargs
        return {
            "decision": "ready",
            "applied": True,
            "resolved": [],
            "materials": [],
            "errors": [],
            "audit": {"decision": "pass"},
        }

    monkeypatch.setattr(cli, "run_resolve", fake_run_resolve)
    assert (
        cli.main(
            [
                "--repo",
                "owner/name",
                "--pr",
                "3",
                "--apply",
                "--confirm",
                "--repo-root",
                str(tmp_path),
                "--expected-owner",
                "owner",
                "--expected-login",
                "example-user",
                "--json",
            ]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "ready"
    assert seen["kwargs"]["expected_login"] == "example-user"
    assert seen["run"]["apply"] is True


def test_resolve_cli_ready_exits_zero(monkeypatch, capsys) -> None:
    cli = _load_cli()
    payload = {
        "decision": "ready",
        "applied": False,
        "resolved": [],
        "materials": [],
        "errors": [],
        "audit": {"decision": "pass"},
    }
    monkeypatch.setattr(cli, "run_resolve", lambda *args, **kwargs: payload)
    assert cli.main(["--repo", "owner/name", "--pr", "3", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "ready"
    assert out["materials"] == []
