"""gh の書込み操作を、引数だけから許可・拒否する純粋な判定。

正本はこのファイル1つ。入出力（remote の解決、アカウント表、トークン、gh の実行）は
呼び出し側が持ち、ここは引数と対象 repo を受け取って理由コードを返すだけにする。
理由コードは呼び出し側の監査ログと回帰テストが使うので、名前を変えない。

判定は2段に分かれる。呼び出し側はこの順に呼ぶ。
1. classify(gh_args): 操作の種類が許可表にあるか。対象 repo の解決より前に判定する。
2. check_scope(gh_args, target_repo, confirm_repo): 引数が対象 repo の外を指していないか。
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

# 操作の許可表。top-level のコマンドごとに、通してよい subcommand を並べる。
ALLOWED_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "pr": frozenset({"create", "comment", "review", "ready", "close", "reopen", "edit"}),
    "issue": frozenset({"create", "comment", "close", "reopen", "edit"}),
    "repo": frozenset({"rename", "archive", "unarchive"}),
}
# 専用の入口へ回す操作。理由コードで行き先を伝える。
REDIRECTED: dict[tuple[str, str], str] = {
    ("pr", "merge"): "pr_merge_use_pr_merge_guarded",
}
# 本文や値を1つ取るフラグ。値の中の URL や --repo を誤って読まないために使う。
VALUE_FLAGS = frozenset(
    {
        "--body", "-b", "--title", "-t", "--body-file", "-F", "--base", "-B",
        "--head", "-H", "--label", "-l", "--add-label", "--remove-label",
        "--assignee", "-a", "--add-assignee", "--remove-assignee",
        "--reviewer", "-r", "--add-reviewer", "--remove-reviewer",
        "--milestone", "-m", "--project", "-p", "--add-project", "--remove-project",
        "--template", "-T", "--comment", "-c", "--reason", "--jq", "-q",
    }
)

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_API_REPO_PATH_RE = re.compile(r"^/?repos/([^/\s]+)/([^/\s?]+)", re.IGNORECASE)
# gh api で書いてはいけない（専用の入口がある、または影響が大きい）パス。
_API_FORBIDDEN_PATH_RE = re.compile(
    r"/(pulls/\d+/merge|pulls/\d+/update-branch|merges|releases|git|contents|transfer|branches"
    r"|collaborators|hooks|keys|actions|environments|pages|rulesets|topics|vulnerability-alerts)(/|$)",
    re.IGNORECASE,
)
_API_METHOD_RE = re.compile(r"^(?:-X|--method)(?:=)?(.*)$")
# gh api --help (gh 2.96.0) の短いフラグ。値を取る物と取らない物に分ける。
_API_VALUE_SHORTS = frozenset("FHqXpft")
_API_BOOLEAN_SHORTS = frozenset("i")
_REPO_NEW_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_REPO_YES_FLAGS = frozenset({"-y", "--yes"})
_REPO_SELECTOR_FLAGS = frozenset({"-R", "--repo"})


@dataclass(frozen=True)
class Classification:
    subcommand: str | None
    reason: str | None  # None なら操作の種類は許可表にある


def classify(gh_args: list[str]) -> Classification:
    if not gh_args:
        return Classification(None, "empty_gh_command")
    top = gh_args[0]
    if top == "api":
        return Classification("api", None)
    if top == "release":
        sub = gh_args[1] if len(gh_args) > 1 else None
        return Classification(f"release {sub}" if sub else "release", "release_not_allowed")
    allowed = ALLOWED_SUBCOMMANDS.get(top)
    if allowed is None:
        return Classification(top, "subcommand_not_allowlisted")
    if len(gh_args) < 2:
        return Classification(top, f"missing_{top}_subcommand")
    sub = gh_args[1]
    redirect = REDIRECTED.get((top, sub))
    if redirect is not None:
        return Classification(f"{top} {sub}", redirect)
    if sub in allowed:
        return Classification(f"{top} {sub}", None)
    # repo は従来どおり subcommand を伏せて "repo" と記録する。
    return Classification(top if top == "repo" else f"{top} {sub}", "subcommand_not_allowlisted")


def _scan(gh_args: list[str]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    skip_next = False
    for index, token in enumerate(gh_args):
        if skip_next:
            skip_next = False
            looks_like_selector = token.startswith("-") or (
                "://" in token and not any(ch.isspace() for ch in token)
            )
            if not looks_like_selector:
                continue
        out.append((index, token))
        if token in VALUE_FLAGS:
            skip_next = True
    return out


def extract_repo_flags(gh_args: list[str]) -> list[str]:
    values: list[str] = []
    for index, token in _scan(gh_args):
        if token in ("--repo", "-R"):
            values.append(gh_args[index + 1] if index + 1 < len(gh_args) else "")
        elif token.startswith("--repo="):
            values.append(token.split("=", 1)[1])
        elif token.startswith("-R") and len(token) > 2 and not token.startswith("--"):
            values.append(token[2:])
        elif token.startswith("-") and not token.startswith("--") and "R" in token[2:]:
            # -xR のように束ねた短いフラグは値を確かめられないので、一致しない値として扱う。
            values.append("")
    return values


def _url_repo(token: str) -> tuple[str | None, str | None]:
    if "://" not in token:
        return None, None
    try:
        parsed = urllib.parse.urlsplit(token)
        host = (parsed.hostname or "").rstrip(".").casefold()
    except ValueError:
        return None, "url_unparseable"
    if host not in ("github.com", "www.github.com"):
        return None, "url_host_not_github"
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None, "url_without_repo"
    owner, name = parts[0], parts[1].removesuffix(".git")
    if not (_NAME_RE.match(owner) and _NAME_RE.match(name)):
        return None, "url_repo_invalid"
    return f"{owner}/{name}", None


def _api_method(rest: list[str]) -> str:
    """gh api の実効 HTTP メソッドを返す。読めない短いフラグがあれば UNKNOWN を返す。

    短いフラグは gh (pflag) と同じく、`-iXDELETE` のようにまとめて書ける。値を取るフラグの後ろは
    同じ語の残り、無ければ次の語が値になる。
    """
    method = None
    has_fields = False
    index = 0
    while index < len(rest):
        token = rest[index]
        if token.startswith("--"):
            match = _API_METHOD_RE.match(token)
            if match and token != "--method" and match.group(1):
                method = match.group(1)
            elif token == "--method" and index + 1 < len(rest):
                method = rest[index + 1]
            elif token in ("--field", "--raw-field", "--input") or re.match(r"^--(raw-)?field=|^--input=", token):
                has_fields = True
        elif token.startswith("-") and len(token) > 1:
            position = 1
            while position < len(token):
                flag = token[position]
                if flag in _API_BOOLEAN_SHORTS:
                    position += 1
                    continue
                if flag not in _API_VALUE_SHORTS:
                    return "UNKNOWN"
                value = token[position + 1 :]
                if not value and index + 1 < len(rest):
                    index += 1
                    value = rest[index]
                if flag == "X":
                    method = value.removeprefix("=")
                elif flag in "fF":
                    has_fields = True
                break
        index += 1
    if method:
        return method.strip("'\"").upper()
    return "POST" if has_fields else "GET"


def referenced_repos(gh_args: list[str]) -> tuple[list[str], str | None]:
    if not gh_args:
        return [], None
    top, rest = gh_args[0], gh_args[1:]
    if top in ("pr", "issue"):
        repos = []
        for _index, token in _scan(rest):
            repo, reason = _url_repo(token)
            if reason:
                return [], reason
            if repo:
                repos.append(repo)
        return repos, None
    if top == "api":
        for index, token in enumerate(rest):
            if token == "--hostname" and index + 1 < len(rest) and rest[index + 1] != "github.com":
                return [], "api_hostname_not_allowed"
            if token.startswith("--hostname=") and token.split("=", 1)[1] != "github.com":
                return [], "api_hostname_not_allowed"
        if not rest:
            return [], "api_endpoint_missing"
        if rest[0].startswith("-"):
            return [], "api_endpoint_must_come_first"
        endpoint = rest[0]
        if endpoint == "graphql":
            return [], "api_graphql_unscoped"
        if ".." in endpoint or "%" in endpoint or "#" in endpoint or any(ord(c) < 0x20 for c in endpoint):
            return [], "api_endpoint_not_canonical"
        match = _API_REPO_PATH_RE.match(endpoint)
        if not match:
            return [], "api_endpoint_not_repo_scoped"
        owner, name = match.group(1), match.group(2)
        path_tail = endpoint.split("?", 1)[0]
        if _API_FORBIDDEN_PATH_RE.search(path_tail):
            return [], "api_path_needs_dedicated_entrypoint"
        if _api_method(rest) != "GET" and re.fullmatch(r"/?repos/[^/]+/[^/]+(/pulls)?/?", path_tail):
            return [], "api_path_needs_dedicated_entrypoint"
        if (owner, name) == ("{owner}", "{repo}"):
            return [], None
        if not (_NAME_RE.match(owner) and _NAME_RE.match(name)):
            return [], "api_endpoint_not_canonical"
        return [f"{owner}/{name}"], None
    return [], None


def _repo_new_name_ok(name: str) -> bool:
    return (
        bool(_REPO_NEW_NAME_RE.match(name))
        and name not in {".", ".."}
        and not name.casefold().endswith(".git")
    )


def repo_change_problem(gh_args: list[str], target_repo: str, confirm_repo: str | None) -> str | None:
    if gh_args[0] != "repo":
        return None
    if confirm_repo is None or confirm_repo.casefold() != target_repo.casefold():
        return "repo_change_needs_confirm"
    positionals: list[str] = []
    selectors: list[str] = []
    rest = gh_args[2:]
    index = 0
    while index < len(rest):
        token = rest[index]
        if token in _REPO_YES_FLAGS:
            index += 1
            continue
        if token in _REPO_SELECTOR_FLAGS and index + 1 < len(rest):
            selectors.append(rest[index + 1])
            index += 2
            continue
        if token.startswith("--repo=") or (token.startswith("-R") and len(token) > 2):
            selectors.append(token.split("=", 1)[1] if token.startswith("--repo=") else token[2:])
            index += 1
            continue
        if token.startswith("-"):
            return "repo_change_args_invalid"
        positionals.append(token)
        index += 1
    if gh_args[1] == "rename":
        if len(positionals) != 1 or not _repo_new_name_ok(positionals[0]):
            return "repo_change_args_invalid"
        if not selectors:
            return "repo_change_target_not_explicit"
        if any(selector.casefold() != target_repo.casefold() for selector in selectors):
            return "repo_mismatch"
        return None
    if selectors or len(positionals) > 1:
        return "repo_change_args_invalid"
    if not positionals:
        return "repo_change_target_not_explicit"
    if positionals[0].casefold() != target_repo.casefold():
        return "repo_mismatch"
    return None


def check_scope(gh_args: list[str], target_repo: str, confirm_repo: str | None = None) -> str | None:
    """classify を通った引数が、対象 repo の外を指していないかを判定する。"""
    target = target_repo.casefold()
    if any(value.casefold() != target for value in extract_repo_flags(gh_args)):
        return "repo_mismatch"
    problem = repo_change_problem(gh_args, target_repo, confirm_repo)
    if problem is not None:
        return problem
    referenced, scope_reason = referenced_repos(gh_args)
    if scope_reason is not None:
        return scope_reason
    if any(ref.casefold() != target for ref in referenced):
        return "repo_mismatch"
    return None
