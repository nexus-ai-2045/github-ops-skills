from __future__ import annotations

import importlib.util
import json
from pathlib import Path


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


def test_resolve_cli_ready_exits_zero(monkeypatch, capsys) -> None:
    cli = _load_cli()
    payload = {
        "decision": "ready",
        "applied": True,
        "resolved": [],
        "materials": [],
        "errors": [],
        "audit": {"decision": "pass"},
    }
    monkeypatch.setattr(cli, "run_resolve", lambda *args, **kwargs: payload)
    assert cli.main(["--repo", "owner/name", "--pr", "3", "--apply", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "ready"
    assert out["materials"] == []
