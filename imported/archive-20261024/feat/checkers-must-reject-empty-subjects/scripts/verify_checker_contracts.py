"""各 checker が「対象が無い / 空」を pass にしないことを実際に走らせて確認する。

## なぜ必要か

2026-08-29 に出した検査 3 本を敵対的にレビューし直したところ、実バグが 9 件出た。
**9 件中 8 件が同じ形**だった。

    検査対象が空、または想定と違う場所にあるのに、status: pass を返す。

`docs/pr-self-review.md` の R1「検査は未確定を合格にしない」そのものであり、
R14 が言う「型で再発する」の実例でもある。実際 `verify_skill_manifests.py` と
`verify_adr_numbering.py` の 2 本が、独立に同じ 0 件 fail-open を持っていた。

## なぜ「negative テストがあるか」を見ないのか

最初その案を検討したが、**実測で効かないことが分かった**ので採らなかった。
バグ 4 件を抱えていた `verify_adr_numbering.py` の初版にも negative テストは
6 件あった。既存 3 本にも 2 / 5 / 4 件ある。「落ちるテストを持っているか」では
上記の型を 1 件も捕まえられない。

## 何をするか

`scripts/verify_*.py` を列挙し、それぞれについて **repo の正常な複製を作り、
宣言された対象 (`SUBJECT`) だけを壊して** 実際に `verify()` を呼ぶ。
**宣言を読むのではなく実行して確かめる。**

1. 複製に対して `verify()` が所見ゼロを返すことを先に確認する
   (ここが汚れていると、以降の所見が変異のせいだと言えない)
2. 対象を**削除**した複製 → 所見が出ること
3. 対象を**空**にした複製 → 所見が出ること

空 repo をゼロから作ると、対象と無関係な「あれが無い」という所見でも契約を
満たしてしまい、対象を一切見ていない checker が合格する (2026-08-29 Codex review)。
だから正常な複製から**対象だけ**を壊す。対象が file か directory かも、
suffix から推測せず**実在するエントリから決める**。

所見が空なら「空振りを pass にした」として落とす。例外が出た場合も落とす
(所見を list で返す契約が破れているため)。`SystemExit` も捕まえる ──
`sys.exit(0)` は `Exception` を継承しないので、素通りするとこの検査自身が
黙って exit 0 する。所見の要素が空でない str であることも見る。

## checker 側に要求する宣言

- `SUBJECT`: 検査対象の repo 相対 path (str)
- `verify(repo: Path) -> list[str]`

read-only。標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIRNAME = "scripts"
CHECKER_GLOB = "verify_*.py"
SELF_NAME = Path(__file__).name
# 子プロセスが返らないときに CI を止めない上限
PROBE_TIMEOUT_SECONDS = 120
# checker workerから監視processへ返す構造化結果の上限。通常出力は含めない
PROBE_RESULT_MAX_BYTES = 64 * 1024
# 複製に持ち込まないもの。履歴とキャッシュは検査対象ではない
SNAPSHOT_IGNORE_NAMES = (
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "node_modules",
    ".mypy_cache",
)
SNAPSHOT_IGNORE = shutil.ignore_patterns(*SNAPSHOT_IGNORE_NAMES)


def _subject_error(subject: str) -> str | None:
    """SUBJECT が複製の外を指していないか。指していたら書き込み事故になる。"""
    if "\0" in subject:
        return "SUBJECT contains an invalid NUL character"
    if Path(subject).is_absolute():
        return f"SUBJECT must be repo-relative, got an absolute path ({subject})"
    parts = Path(subject).parts
    if not parts:
        return "SUBJECT must not be empty"
    if any(part in {"..", ""} for part in parts):
        return f"SUBJECT must not contain a parent traversal ({subject})"
    if any(part in SNAPSHOT_IGNORE_NAMES for part in parts):
        # 複製に含まれないので、変異を作れない。checker のせいにしない
        return f"SUBJECT is excluded from the probe snapshot ({subject})"
    return None


def _symlink_component(root: Path, subject: str) -> str | None:
    """SUBJECT の途中に symlink が無いか。あると複製の外を消しに行く。

    `..` と絶対 path を塞いでも、repo 内の symlink 経由で外へ抜けられる。
    実測 (2026-08-29 self review) では複製の外の実ディレクトリが rmtree された。
    判定は `src/github_ops/source_manifest.py::_unsafe_component` と同じ考え方で、
    leaf を含む全 component を lstat する。ただし「単に存在しない」は
    symlink ではないので区別する (M3 と同じ取り違えを持ち込まない)。
    """
    current = root
    for part in Path(subject).parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            return f"cannot inspect {subject} ({exc})"
        attributes = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attributes & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            rel = current.relative_to(root).as_posix()
            return (
                f"SUBJECT traverses a symlink ({rel}); the probe would mutate "
                "outside the snapshot"
            )
    return None


# checker を実行する非信頼側 worker。stdout / stderr は fd ごと DEVNULL へ
# 接続し、構造化結果だけを複製済み fd へ 1 回書く。終了handlerの実行前にその
# fdを閉じるため、atexit の通常出力が結果へ混ざらない。
_WORKER = r"""
import importlib.util, json, os, sys
from pathlib import Path

script, repo, src, action = sys.argv[1:5]
sys.path.insert(0, str(Path(script).parent))
if src:
    sys.path.insert(1, src)

result_fd = os.dup(sys.stdout.fileno())
# checkerが共有moduleのos.writeを差し替えても、正規frameを消せないよう先に束縛する。
# 任意悪意codeのsandboxではない。保証境界はADR-0008を参照。
emit_result = os.write
with open(os.devnull, "wb", buffering=0) as null:
    os.dup2(null.fileno(), sys.stdout.fileno())
    os.dup2(null.fileno(), sys.stderr.fileno())

out = {}
try:
    spec = importlib.util.spec_from_file_location(Path(script).stem, script)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot create import spec")
    module = importlib.util.module_from_spec(spec)
    # 通常の import 意味論を保つ。外すと dataclass や pickle が壊れる
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if action == "declare":
        subject = getattr(module, "SUBJECT", None)
        out = {
            "kind": "declaration",
            "subject": subject if isinstance(subject, str) else None,
            "subject_type": type(subject).__name__,
            "has_verify": callable(getattr(module, "verify", None)),
        }
    else:
        errors = module.verify(Path(repo))
except SystemExit as exc:
    out = {"kind": "exit", "code": repr(exc.code)}
except BaseException as exc:
    out = {"kind": "raise", "type": type(exc).__name__}
else:
    if action != "declare":
        if isinstance(errors, list):
            bad = [e for e in errors if not isinstance(e, str) or not e]
            out = {"kind": "ok", "count": len(errors), "bad": repr(bad[0]) if bad else None}
        else:
            out = {"kind": "badtype", "type": type(errors).__name__}
payload = json.dumps(out).encode("utf-8")
emit_result(result_fd, payload)
os.close(result_fd)
"""


# 監視processはcheckerと別processに留まり、worker終了後だけ親へ結果を返す。
# checkerは監視processのstdoutにも結果pathにもaccessできない。worker側pipeは
# 上限までしかbufferせず、超過分は捨てながらdrainしてdeadlockを防ぐ。
_DRIVER = (
    "import json, subprocess, sys, threading\n"
    f"WORKER = {_WORKER!r}\n"
    r"""
script, repo, src, action, timeout_text, limit_text = sys.argv[1:7]
timeout = float(timeout_text)
limit = int(limit_text)
proc = subprocess.Popen(
    [sys.executable, "-c", WORKER, script, repo, src, action],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
)
assert proc.stdout is not None
buffer = bytearray()
oversized = [False]

def drain() -> None:
    while True:
        chunk = proc.stdout.read(8192)
        if not chunk:
            return
        room = limit + 1 - len(buffer)
        if room > 0:
            buffer.extend(chunk[:room])
        if len(buffer) > limit:
            oversized[0] = True

reader = threading.Thread(target=drain, daemon=True)
reader.start()
timed_out = False
try:
    proc.wait(timeout=timeout)
except subprocess.TimeoutExpired:
    timed_out = True
    proc.kill()
    proc.wait()
reader.join()

if timed_out:
    envelope = {"transport": "timeout"}
elif oversized[0]:
    envelope = {"transport": "oversized"}
elif proc.returncode != 0:
    envelope = {"transport": "exit", "code": proc.returncode}
else:
    try:
        result = json.loads(bytes(buffer).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        envelope = {"transport": "unreadable"}
    else:
        envelope = {"transport": "ok", "result": result}
sys.stdout.write(json.dumps(envelope))
"""
)


def _run_driver(
    script: Path,
    src: Path | None,
    root: Path,
    action: str,
    label: str,
) -> tuple[dict[str, object] | None, str | None]:
    """checker と別processのdriverから、上限付き結果だけを読む。"""
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                _DRIVER,
                str(script),
                str(root),
                str(src or ""),
                action,
                str(PROBE_TIMEOUT_SECONDS),
                str(PROBE_RESULT_MAX_BYTES),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=PROBE_TIMEOUT_SECONDS + 5,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out {label} after {PROBE_TIMEOUT_SECONDS} seconds"
    if proc.returncode != 0:
        return None, f"probe supervisor exited with status {proc.returncode} {label}"
    try:
        envelope = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, f"produced an unreadable contract result {label}"
    if not isinstance(envelope, dict):
        return None, f"produced an unreadable contract result {label}"
    transport = envelope.get("transport")
    if transport == "timeout":
        return None, f"timed out {label} after {PROBE_TIMEOUT_SECONDS} seconds"
    if transport == "oversized":
        return None, f"produced an oversized contract result {label}"
    if transport == "exit":
        return None, f"exited with status {envelope.get('code')} {label}"
    if transport != "ok":
        return None, f"produced an unreadable contract result {label}"
    out = envelope.get("result")
    if not isinstance(out, dict):
        return None, f"produced an unreadable contract result {label}"
    return out, None


def _call(
    script: Path, src: Path | None, root: Path, label: str
) -> tuple[int | None, str | None]:
    """verify() を **子プロセスで** 1 回呼ぶ。契約違反があればその説明を返す。

    同一プロセスで呼ぶと何も隔離されない。module 級の状態、`src` 側 helper の
    状態、`sys.modules` 登録、`sys.exit` がすべて probe 間と親へ漏れる。
    実測 (2026-08-29 Codex review 第 3 巡) では、
      - reload 中の `sys.exit(0)` が親を無出力 exit 0 で終わらせ、
      - `src` 側 helper に状態を持つ checker が SUBJECT を一切見ずに合格した。
    子プロセスなら実際の CI 実行と同じ「まっさらな 1 回」になる。
    """
    out, problem = _run_driver(script, src, root, "verify", f"on {label}")
    if problem is not None:
        return None, problem
    assert out is not None

    kind = out.get("kind")
    if kind == "exit":
        return None, (
            f"called sys.exit({out['code']}) on {label} instead of returning findings"
        )
    if kind == "raise":
        return None, f"raised {out['type']} on {label} instead of returning findings"
    if kind == "badtype":
        return None, f"returned {out['type']} on {label} instead of a list"
    if out.get("bad") is not None:
        return None, (
            f"returned a finding that is not a non-empty str on {label} ({out['bad']})"
        )
    return out["count"], None


def _declaration(
    script: Path, src: Path | None, repo: Path
) -> tuple[dict[str, object] | None, str | None]:
    """SUBJECT / verify 宣言も親へimportせず、停止上限付きで読む。"""
    return _run_driver(script, src, repo, "declare", "at import time")


def _snapshot(repo: Path, into: Path) -> Path:
    root = into / "repo"
    shutil.copytree(repo, root, ignore=SNAPSHOT_IGNORE, symlinks=True)
    return root


def _break_subject(root: Path, subject: str, *, empty: bool) -> None:
    """正常な複製の中で、対象だけを壊す。file / dir は実在から判定する。

    空にするときは削除して作り直さない。mode bit を落とすと、権限だけ見て
    中身の空を無視する checker が「空の対象」probe をすり抜けられる。
    """
    target = root / subject
    was_dir = target.is_dir() and not target.is_symlink()
    if not empty:
        if was_dir:
            shutil.rmtree(target)
        else:
            target.unlink()
        return
    if was_dir:
        for child in list(target.iterdir()):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        return
    # 既存 file を truncate すれば mode は残る (作り直しは 0o644 になる)
    target.write_text("", encoding="utf-8")


def _probe(script: Path, src: Path | None, repo: Path, subject: str) -> list[str]:
    """正常な複製から対象だけを壊して食わせる。問題があればその説明を返す。

    variant ごとに **別プロセス** で呼ぶ。同一プロセスで回すと module 級の状態も
    `src` 側 helper の状態も probe 間に漏れ、SUBJECT を一切見ない checker が
    「1 回目は []、以降は拒否」で負例 probe をすり抜ける (実測)。
    """
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        clean = _snapshot(repo, Path(tmp) / "clean")
        errors, problem = _call(script, src, clean, "a valid repository")
        if problem is not None:
            return [problem]
        if errors:
            # ここが汚れていると、以降の所見が変異のせいだと言えない
            return [
                (
                    "reports findings on a valid repository, so the probes below "
                    f"cannot be attributed to the mutation ({errors} finding(s))"
                )
            ]

    for empty in (False, True):
        label = "an empty subject" if empty else "a missing subject"
        with tempfile.TemporaryDirectory() as tmp:
            root = _snapshot(repo, Path(tmp) / str(int(empty)))
            # 複製の中でも改めて見る。repo 側で通っても複製で symlink になりうる
            escape = _symlink_component(root, subject)
            if escape is not None:
                problems.append(escape)
                break
            try:
                _break_subject(root, subject, empty=empty)
            except OSError as exc:
                # ここで例外を上げると、この検査が他へ課している契約
                # (所見を list で返す) を自分で破ることになる
                problems.append(f"the probe could not break {subject} ({exc})")
                continue
            errors, problem = _call(script, src, root, label)
            if problem is not None:
                problems.append(problem)
            elif not errors:
                problems.append(f"accepted {label} (returned no findings)")
    return problems


def verify(repo: Path) -> list[str]:
    errors: list[str] = []
    scripts_root = repo / SCRIPTS_DIRNAME
    if not scripts_root.is_dir():
        return [f"{SCRIPTS_DIRNAME}/ not found"]

    # checker には src/ 側の実装を読むものがある。子プロセスへ渡す
    src_root: Path | None = repo / "src" if (repo / "src").is_dir() else None
    checkers = sorted(
        path for path in scripts_root.glob(CHECKER_GLOB) if path.name != SELF_NAME
    )
    if not checkers:
        # 0 件を pass にすると、この検査自身がまさに塞ごうとしている型になる
        return [f"{SCRIPTS_DIRNAME}/ contains no {CHECKER_GLOB} to check"]

    for path in checkers:
        rel = path.relative_to(repo).as_posix()
        declaration, problem = _declaration(path, src_root, repo)
        if problem is not None:
            errors.append(f"{rel}: {problem}")
            continue
        assert declaration is not None

        kind = declaration.get("kind")
        if kind == "exit":
            errors.append(
                f"{rel}: called sys.exit({declaration.get('code')}) at import time"
            )
            continue
        if kind == "raise":
            errors.append(f"{rel}: cannot be imported ({declaration.get('type')})")
            continue

        subject = declaration.get("subject")
        if not isinstance(subject, str) or not subject:
            errors.append(
                f"{rel}: must declare SUBJECT (the repo-relative path it inspects)"
            )
            continue
        subject_problem = _subject_error(subject)
        if subject_problem is not None:
            errors.append(f"{rel}: {subject_problem}")
            continue
        if not declaration.get("has_verify"):
            errors.append(f"{rel}: must expose verify(repo) -> list[str]")
            continue
        escape = _symlink_component(repo, subject)
        if escape is not None:
            errors.append(f"{rel}: {escape}")
            continue
        if not (repo / subject).exists():
            errors.append(f"{rel}: declares SUBJECT {subject} which is not in this repository")
            continue

        # SUBJECT 等の宣言確認は上で済んだ。probe は変種ごとに別プロセスで走らせる
        errors.extend(
            f"{rel}: {problem}" for problem in _probe(path, src_root, repo, subject)
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    # 宣言 (SUBJECT / verify) を読むための import に必要。probe 側は子プロセスが
    # 自分で解決するので、ここの sys.path は probe の結果に影響しない
    src = str(repo / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    errors = verify(repo)
    if args.json:
        print(
            json.dumps(
                {
                    "schema": "github-ops/checker-contracts/v1",
                    "status": "fail" if errors else "pass",
                    "read_only": True,
                    "error_count": len(errors),
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for error in errors:
            print(error)
        if not errors:
            print("checker contracts: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
