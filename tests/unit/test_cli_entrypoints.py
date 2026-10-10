from __future__ import annotations

from github_ops.cli import build_check_pr_parser, build_create_pr_parser


def test_check_pr_entrypoint_accepts_file_inputs() -> None:
    args = build_check_pr_parser().parse_args(
        ["--title-file", "title.txt", "--body-file", "body.md", "--json"]
    )
    assert args.title_file.name == "title.txt"


def test_create_pr_entrypoint_keeps_expected_sha_contract() -> None:
    args = build_create_pr_parser().parse_args(
        [
            "--repo",
            "owner/repo",
            "--base",
            "main",
            "--head",
            "feature",
            "--repo-root",
            ".",
            "--account-map",
            "accounts.yaml",
            "--expected-base-sha",
            "a" * 40,
            "--expected-head-sha",
            "b" * 40,
            "--title-file",
            "title.txt",
            "--body-file",
            "body.md",
            "--confirm",
            "--json",
        ]
    )
    assert args.confirm is True
    assert args.expected_visibility == "PRIVATE"


def test_create_pr_accepts_explicit_resident_adaptation_purpose() -> None:
    args = build_create_pr_parser().parse_args([
        "--repo", "owner/repo", "--base", "main", "--head", "resident",
        "--repo-root", ".", "--account-map", "accounts.yaml",
        "--expected-base-sha", "a" * 40, "--expected-head-sha", "b" * 40,
        "--title", "適応確認", "--body-file", "body.md",
        "--branch-purpose", "resident_adaptation",
    ])
    assert args.branch_purpose == "resident_adaptation"
