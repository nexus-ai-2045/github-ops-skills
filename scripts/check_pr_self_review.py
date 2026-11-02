"""Verify the generated PR self-review document and its packaged copy.

The candidate-side check proves only internal consistency. The trusted
base-side check requires an allowlisted complete-file digest and unchanged
gate files from the base tree; this prevents a pull request from changing
its own canonical input and verifier at the same time.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path


_VERSION_ROW = re.compile(r"^(\| rules_version \| `)([0-9a-f]{16})(` \|)$", re.MULTILINE)
_DOC_RELATIVE = Path("docs/pr-self-review.md")
_PACKAGE_RELATIVE = Path("skills/commit-push-pr/references/pr-self-review.md")
_TRUSTED_DIGESTS_RELATIVE = Path("docs/pr-self-review-trusted-digests.txt")
_PROTECTED_GATE_RELATIVES = (
    Path(".github/workflows/pr-self-review-trusted.yml"),
    Path("scripts/check_pr_self_review.py"),
    _TRUSTED_DIGESTS_RELATIVE,
)


class VerificationError(ValueError):
    """A generated artifact cannot be trusted for this check."""


def _body_digest(text: str) -> str:
    match = _VERSION_ROW.search(text)
    if match is None:
        raise VerificationError("rules_version row is missing or malformed")
    start = text.find("\n## R1 ")
    if start < 0:
        raise VerificationError("R1 section is missing")
    return hashlib.sha256(text[start + 1 :].encode("utf-8")).hexdigest()[:16]


def _regular_file(root: Path, relative: Path) -> Path:
    """Return a regular file below root without following symlink components."""
    root = root.resolve()
    path = root.joinpath(relative)
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise VerificationError(f"{current} is a symlink")
    if not path.is_file():
        raise VerificationError(f"{path} is not a regular file")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise VerificationError(f"{path} resolves outside candidate root") from exc
    return path


def _read(root: Path, relative: Path) -> str:
    path = _regular_file(root, relative)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise VerificationError(f"{path} is unreadable as UTF-8: {exc}") from exc


def verify_artifact(root: Path) -> tuple[str, str]:
    """Return (declared version, computed version) after pair verification."""
    document_path = _regular_file(root, _DOC_RELATIVE)
    package_path = _regular_file(root, _PACKAGE_RELATIVE)
    document = _read(root, _DOC_RELATIVE)
    package = _read(root, _PACKAGE_RELATIVE)
    if document != package:
        raise VerificationError(f"{package_path} differs from {document_path}")
    match = _VERSION_ROW.search(document)
    if match is None:
        raise VerificationError(f"{document_path} has no valid rules_version row")
    declared = match.group(2)
    computed = _body_digest(document)
    if computed != declared:
        raise VerificationError(
            f"{document_path} declares {declared}, but generated-body digest is {computed}"
        )
    return declared, computed


def _artifact_digest(root: Path) -> str:
    path = _regular_file(root, _DOC_RELATIVE)
    # GitHub checkout uses LF while Windows worktrees may use CRLF; the
    # trusted identity is over canonical UTF-8 content, not checkout style.
    canonical = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(canonical).hexdigest()


def _trusted_digests(base_root: Path) -> set[str]:
    text = _read(base_root, _TRUSTED_DIGESTS_RELATIVE)
    digests = {
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if not digests or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in digests):
        raise VerificationError("trusted digest allowlist is empty or malformed")
    return digests


def _verify_protected_gates(base_root: Path, candidate_root: Path) -> None:
    for relative in _PROTECTED_GATE_RELATIVES:
        base_path = _regular_file(base_root, relative)
        candidate_path = _regular_file(candidate_root, relative)
        if base_path.read_bytes() != candidate_path.read_bytes():
            raise VerificationError(
                f"protected gate changed: {relative}; validate replacement separately"
            )


def verify_candidate(candidate_root: Path, base_root: Path | None = None) -> tuple[str, str]:
    """Verify a candidate, optionally against a trusted base tree.

    The trusted workflow accepts replacements only when their complete-file
    digest is already present in an allowlist from the base tree.  The
    allowlist and protected gate files therefore need a separate trusted
    bootstrap/update before an artifact or gate replacement can land.
    """
    candidate_version = verify_artifact(candidate_root)
    if base_root is None:
        return candidate_version
    try:
        _verify_protected_gates(base_root, candidate_root)
        trusted_digests = _trusted_digests(base_root)
    except VerificationError as exc:
        raise VerificationError(
            f"trusted base bootstrap/update is unavailable: {exc}"
        ) from exc
    digest = _artifact_digest(candidate_root)
    if digest not in trusted_digests:
        raise VerificationError(
            "candidate artifact digest is not in the trusted base allowlist; "
            "update the allowlist in a separate trusted change"
        )
    return candidate_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--base-root", type=Path)
    args = parser.parse_args(argv)
    try:
        declared, computed = verify_candidate(args.candidate_root, args.base_root)
    except VerificationError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    scope = "base-side advisory" if args.base_root else "candidate"
    outcome = "ADVISORY" if args.base_root else "READY"
    print(f"{outcome}: {scope} PR self-review artifact matches {computed} ({declared})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
