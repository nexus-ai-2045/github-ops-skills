"""Verify the generated PR self-review document and its packaged copy.

The candidate-side check proves only internal consistency.  The trusted
base-side check also requires the candidate artifact to match the artifact
from the base tree; this prevents a pull request from changing its own
canonical input and verifier at the same time.
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


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise VerificationError(f"{path} is unreadable as UTF-8: {exc}") from exc


def verify_artifact(root: Path) -> tuple[str, str]:
    """Return (declared version, computed version) after pair verification."""
    document_path = root / _DOC_RELATIVE
    package_path = root / _PACKAGE_RELATIVE
    document = _read(document_path)
    package = _read(package_path)
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


def verify_candidate(candidate_root: Path, base_root: Path | None = None) -> tuple[str, str]:
    """Verify a candidate, optionally against a trusted base tree.

    A missing base artifact is accepted only by the explicit candidate-side
    bootstrap check.  The trusted workflow never passes that option, so a
    newly introduced artifact cannot self-authorize in the base-side gate.
    """
    candidate_version = verify_artifact(candidate_root)
    if base_root is None:
        return candidate_version
    base_document = base_root / _DOC_RELATIVE
    base_package = base_root / _PACKAGE_RELATIVE
    if not base_document.is_file() or not base_package.is_file():
        raise VerificationError(
            "trusted base has no PR self-review artifact; bootstrap requires human review"
        )
    base_version = verify_artifact(base_root)
    if _read(candidate_root / _DOC_RELATIVE) != _read(base_document):
        raise VerificationError(
            "candidate PR self-review differs from trusted base; regenerate from the source repository"
        )
    if candidate_version != base_version:
        raise VerificationError("candidate and trusted-base rules_version values differ")
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
    scope = "trusted base" if args.base_root else "candidate"
    print(f"READY: {scope} PR self-review artifact matches {computed} ({declared})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
