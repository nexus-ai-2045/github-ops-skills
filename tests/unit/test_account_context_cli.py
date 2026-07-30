from scripts.github_account_context import build_parser
from scripts.github_pr_readiness_preflight import build_parser as build_preflight_parser


def test_account_context_parser_has_no_switch_option() -> None:
    parser = build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--switch-if-needed" not in option_strings


def test_preflight_requires_operation_choice() -> None:
    args = build_preflight_parser().parse_args(["--operation", "draft-pr"])
    assert args.operation == "draft-pr"
