from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from github_ops.output import configure_utf8_stdout
from github_ops.public_identity import scan_text
from github_ops.result import Status


SKILL_SOURCES = {
    "github-cli-ops-guard": ("shared", "skills/github-cli-ops-guard"),
    "commit-push-pr": ("shared", "skills/commit-push-pr"),
    "pr-status": ("shared", "skills/pr-status"),
    "review-pr": ("shared", "skills/review-pr"),
    "public-repo-readiness": ("agent-skills", "public-repo-readiness"),
    "post-merge-closeout": ("shared", "skills/post-merge-closeout"),
    "pr-convergence-loop": ("shared", "skills/pr-convergence-loop"),
    "cross-repo-wip-ownership": ("shared", "skills/cross-repo-wip-ownership"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="既存Core Suiteを非破壊importします")
    parser.add_argument("--shared-root", type=Path, required=True)
    parser.add_argument("--agent-skills-root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    roots = {
        "shared": args.shared_root.resolve(),
        "agent-skills": args.agent_skills_root.resolve(),
    }
    manifest_path = args.repo / "migration" / "source-manifest.json"
    mappings = list(_expand_skill_mappings(roots))
    configure_utf8_stdout()
    if args.dry_run:
        print(json.dumps({"status": "dry-run", "files": mappings}, ensure_ascii=False, indent=2))
        return 0
    if args.verify_only:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        errors = verify_records(payload["sources"], roots, args.repo)
        print(json.dumps({"status": "ok" if not errors else "error", "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    records = import_sources(
        mappings=mappings,
        source_roots=roots,
        target_root=args.repo,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "github-ops/source-manifest/v1",
                "sources": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "imported", "file_count": len(records)}, ensure_ascii=False))
    return 0


def import_sources(
    *,
    mappings: list[tuple[str, str, str]],
    source_roots: dict[str, Path],
    target_root: Path,
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for root_name, source_rel, target_rel in mappings:
        source = _safe_child(source_roots[root_name], source_rel)
        target = _safe_child(target_root, target_rel)
        if source.is_symlink():
            raise ValueError(f"symlink source is not allowed: {source_rel}")
        if not source.is_file():
            raise FileNotFoundError(source)
        source_text = source.read_text(encoding="utf-8")
        text = _normalize_private_identity(source_text)
        scan = scan_text(text)
        if scan.status is Status.BLOCKED:
            raise ValueError(
                f"normalized source contains blocked identity patterns: {source_rel}: "
                f"{','.join(scan.evidence['rules'])}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        source_digest = _sha256(source)
        target_digest = _portable_sha256(target)
        records.append(
            {
                "source_root": root_name,
                "source_path": source_rel.replace("\\", "/"),
                "target_path": target_rel.replace("\\", "/"),
                "sha256": target_digest,
                "source_sha256": source_digest,
                "target_sha256": target_digest,
                "normalized": source_text != text,
            }
        )
    return records


def verify_records(
    records: list[dict[str, str]],
    source_roots: dict[str, Path],
    target_root: Path,
) -> list[str]:
    errors: list[str] = []
    for record in records:
        source = _safe_child(
            source_roots[record["source_root"]],
            record["source_path"],
        )
        target = _safe_child(target_root, record["target_path"])
        expected_source = record.get("source_sha256", record["sha256"])
        expected_target = record.get("target_sha256", record["sha256"])
        if not source.is_file() or _sha256(source) != expected_source:
            errors.append(f"source hash mismatch: {record['source_path']}")
        if not target.is_file() or _portable_sha256(target) != expected_target:
            errors.append(f"target hash mismatch: {record['target_path']}")
    return errors


def _expand_skill_mappings(
    roots: dict[str, Path],
):
    for skill_name, (root_name, source_rel) in SKILL_SOURCES.items():
        source_dir = _safe_child(roots[root_name], source_rel)
        if not source_dir.is_dir():
            raise FileNotFoundError(source_dir)
        for source in sorted(source_dir.rglob("*")):
            if source.is_symlink():
                raise ValueError(f"symlink source is not allowed: {source}")
            if not source.is_file() or "__pycache__" in source.parts:
                continue
            relative = source.relative_to(source_dir).as_posix()
            yield (
                root_name,
                f"{source_rel}/{relative}",
                f"skills/{skill_name}/{relative}",
            )


def _safe_child(root: Path, relative: str) -> Path:
    """Return a child path under root without following intermediate symlinks.

    Symlink components are rejected before resolve. The returned path is the
    non-resolved child so callers can still observe symlink status if needed.
    """
    resolved_root = root.resolve()
    current = resolved_root
    parts = Path(relative).parts
    if not parts:
        raise ValueError("relative path is required")
    for index, part in enumerate(parts):
        nxt = current / part
        if nxt.is_symlink():
            raise ValueError(f"symlink source is not allowed: {relative}")
        if nxt.exists():
            current = nxt
            continue
        # Remaining components do not exist yet (import target creation).
        candidate = nxt.joinpath(*parts[index + 1 :])
        resolved_candidate = candidate.resolve()
        if (
            resolved_candidate != resolved_root
            and resolved_root not in resolved_candidate.parents
        ):
            raise ValueError(f"path escapes root: {relative}")
        return candidate
    resolved = current.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"path escapes root: {relative}")
    return current


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _normalize_private_identity(text: str) -> str:
    usernames = {
        match.group("username")
        for match in re.finditer(
            r"(?i)C:\\Users\\(?P<username>[^\\/\s`]+)",
            text,
        )
    }
    normalized = re.sub(
        r"(?i)C:\\Users\\[^\\/\s`]+",
        "<USER_HOME>",
        text,
    )
    for username in sorted(usernames, key=len, reverse=True):
        normalized = re.sub(
            rf"(?i)(?<![A-Za-z0-9_]){re.escape(username)}(?![A-Za-z0-9_])",
            "<PRIVATE_IDENTIFIER>",
            normalized,
        )
    return normalized.rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
