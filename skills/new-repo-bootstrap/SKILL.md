---
name: new-repo-bootstrap
description: >
  repo-preflight から委任された新規 GitHub repository 作成の実行担当。
  新規作成の受付は repo-preflight の --create-repo に統一する。
  この skill は委任された作成・初期送信・設定確認と再開を担当する。
  置き場所の固定・commit 名義・公開前文書・repo-preflight 検査・owner の token での作成・公開直後の lockdown・
  canonical wrapper 経由の作業 branch push と API による main 作成・台帳登録 branch の commit・read-back を 1 本の script が順番に行い、
  台帳登録の push と PR は手順 4 で canonical wrapper から出す。
  Do NOT use for: 既存 repo への push / PR (commit-push-pr, github-cli-ops-guard)、公開判定の整備だけ (public-repo-readiness)。
---

# 新規リポジトリ作成の実行担当

## 受付と実行の分担

新規リポジトリ作成の通常の入口は `repo-preflight` の `run_preflight.py --create-repo`。このスキルは、入口から委任された作成・初期送信・設定確認を実行する。コメント禁止と再発防止の検査は `repo-preflight` 正本から導入する。以下の直接呼出しは、この実行担当を検査・再開するときの手順として使う。

## なぜこの skill があるか

push / PR / 公開判定には既に道具があるが、「repo を新しく立てる」瞬間には道具が無く、
場所・名義・台帳・アカウント・安全設定を毎回その場で組み立てて、どれかを落としていた
(2026-09-05 実測: 置き場所違い、Full FDE 未昇格、PUBLIC_READY/PREFLIGHT の食い違い)。
この skill はその工程を 1 本の fail-closed script に固定する。

## FDE Packet

新規 repository の作成は **公開 / 外部送信 / Type1** に当たる。作業前に Full FDE に上げ、次を切る。

```text
entry: new repository bootstrap
repository: <owner>/<name>
visibility: public | private
local_dir: ~/Projects/Documents/.repos/nexus_ai/<name>  (private は /private/<name>)
commit_identity: nexus_ai <273569186+nexus-ai-2045@users.noreply.github.com>  (owner=nexus-ai-2045 の既定)
approval: current_turn_yes | missing   ← visibility と名前を CEO が現在会話で言っていること
registry_pr: 台帳 repo への登録 PR (1 行追加) も同じ承認で出す。merge は人が行う
done_when: script の execute が READY + gh repo view で read-back 一致 + (report に registration がある時は) 台帳登録 PR の URL
```

`approval: missing` なら `--confirm` を付けない (preflight だけ)。

## 開発開始時の静的検査

開発ライフサイクルと検査の正本は `repo-preflight`。新規作成では、その `scripts/install_development_lint.py` を呼び、コメント禁止とバグの再発防止ルールを実行する `tools/development_lint.py`、依存定義、継続検査、開発ルールを雛形に含める。初期コミットの前に検査を実行し、失敗した場合は作成処理を停止する。

既存の独立したアプリ、または開発前のディレクトリには、正本のローカル専用入口で同じ検査を導入する。

```bash
python3 <repo-preflight>/scripts/install_development_lint.py --repo <repo-dir> --json
```

既存呼出しの `bootstrap_repo.py --install-development-lint <repo-dir> --json` も、同じ正本へ委任する。導入処理は `--preflight-script` と同じディレクトリ、`REPO_PREFLIGHT_ROOT`、実行環境の `repo-preflight/checkout`、ローカルの既定正本の順で探す。正本が見つからない場合は停止する。

既存文書は保持し、`AGENTS.md` と `CONTRIBUTING.md` へ管理ブロックを追記する。既存の同名検査ファイルと内容が違う場合は、書込み前に停止して統合対象を示す。再実行で同じ内容を重複追加しない。依存の導入は利用する開発環境で行い、ローカルと継続検査で次の同じコマンドを使う。

```bash
python3 -m pip install -r tools/development-lint-requirements.txt
python3 tools/development_lint.py
```

初期のコメント検査は `Python`、`JavaScript`、`TypeScript`、`JSX`、`TSX` に対応する。他の言語を採用するときは、その言語の構文解析器と正常例・違反例を追加する。バグ修正時は構造・型・既存の検査を優先し、静的に判定できる誤りには `tools/lint_rules/` のルールと元の違反例・近い正常例を追加する。実行順序や結果に依存する不具合はアプリの回帰テストで再現する。

## 手順

1. **preflight (read-only)**。何も書かない。

```bash
python3 <skill dir>/scripts/bootstrap_repo.py --name <name> --visibility <public|private> --description "<一文>" --json
```

   結果の `checks` を見る。`token_login: ok` / `remote_absent: ok` / `commit_identity: ok|n/a` /
   `preflight_script: ok` / `registry_file: ok|skipped` でなければ止めて理由を報告する。よくある止まり方:

   | check | 意味 | 対処 |
   |---|---|---|
   | `token_login: missing` | owner の token が gh の keyring に無い | `gh auth login` は CEO が行う。script は切り替えない |
   | `token_login: mismatch` | token の login が owner と違う | 対象 owner の token を入れ直す。global account は触らない |
   | `remote_absent: exists` | GitHub に同名 repo が既にある | 名前を変えるか、既存 repo を使う (この skill の対象外) |
   | `remote_absent: ok_renamed_away` | 同名の旧 repo が別名へ変えられ、GitHub が転送しているだけ | 止まらない。同名で作り直してよい (作成で転送は終わる) |
   | `local_dir: has_origin` | 手元の directory に origin が既にある | 既存 repo。commit-push-pr を使う |
   | `commit_identity: mismatch` | 既存 commit が個人名義 | 公開 repo には出せない。作り直す |
   | `preflight_script: missing` | repo-preflight の checkout が無い (preflight はここで BLOCKED) | `~/Projects/Documents/.repos/nexus_ai/repo-preflight` を clone する。`--allow-no-preflight` は非推奨 |
   | `local_dir: nested_in_other_repo` | 指定 directory が別 repo の中 | 別の場所を指定する |
   | `remote_absent: exists_visibility_<x>` | `--resume` 先の remote の visibility が指定と違う | 指定を合わせるか、visibility 変更を別承認で行う |
   | `registry_file: not_git` / `no_origin_main` | 台帳の main checkout を特定できない (git の外、submodule 等) / 台帳 repo に origin/main が無い | 台帳は branch → PR でしか更新しない。台帳 repo の checkout を直す |
   | `registry_file: registry_not_on_origin_main` / `registry_anchor_missing` | 指定した台帳 file が origin/main に無い / 挿入位置の行 (公開協業 repo 全般。インラインコードの有無は問わない) が無い | `--registry-file` を見直す。台帳の形が変わったなら script を直す |
   | `registry_file: commit_wrapper_missing` | 台帳 repo の origin/main に `shared/scripts/cc-commit.sh` が無い | 台帳 repo を同期してから再実行する |
   | `registry_file: worktree_dir_not_ignored` | 台帳 repo の `.worktrees/` が ignore されていない (登録用 worktree が main checkout を汚す) | 台帳 repo の `.gitignore` を直す |

2. **CEO の承認を現在会話で確認**する (repo 名 / visibility / 説明)。前の会話や「全部推奨で」の一括承認は
   名前と visibility が言われていれば有効。言われていなければ 1 問だけ聞く。
   この承認には、手順 4 の台帳登録 PR (台帳 repo へ 1 行追加) を出すことも含めて伝える。

3. **execute**。同じ引数に `--confirm` を足す。

```bash
python3 <skill dir>/scripts/bootstrap_repo.py --name <name> --visibility <public|private> --description "<一文>" --confirm --json
```

   step は `preflight → prepare_local → set_identity → scaffold_docs → initial_commit → readiness_scan →
   create_remote → repo_settings → lockdown (public のみ、push より先) → add_remote → push → promote_main → verify → register` の順。
   `repo_settings` は公開・非公開とも、統合後に head branch を自動で消す設定 (`delete_branch_on_merge`) を有効にし、読み戻して確かめる。
   既存の repository にこの設定だけを当てる時は `--name <name> --visibility <public|private> --settings-only --confirm` を使う。作成・push・台帳は触らない。
   途中で `fail` が出たらそれ以降は走らない。`steps` をそのまま報告し、失敗した step の `detail` を人間語に直して伝える。

   push は main に直接行わない。`bootstrap/init` branch を canonical wrapper で push し (両方の push guard が
   branch push だけを許可するため)、GitHub API でその commit から `main` を作って既定 branch にし、`bootstrap/init` を消す。
   `verify` は remote の `main` が local HEAD と同じ sha であることまで確認する。

   `register` は read-back の後に走り、台帳 repo の main checkout に**書かない**。台帳 repo の origin/main を fetch し、
   `.worktrees/register-<owner>-<name>` に `bootstrap/register-<owner>-<name>` branch の worktree を切って、
   台帳の今の書式 (識別子をインラインコードにした行) で 1 行足す。その worktree に `shared/scripts/japanese_gate_autoformat.py`
   があれば `--apply` で日本語ゲート準拠に整え、`shared/scripts/cc-commit.sh` で commit する (push はしない)。
   挿入位置の行と既存行の照合は、インラインコードの記号を外した形で行うので、台帳の表記の整形に左右されない。
   次のどれかなら fail して branch を出さない: 整形に失敗した / branch の差分が台帳 1 file でない / 登録の前後で
   main checkout の HEAD か台帳 file の状態が変わった (commit 入口が worktree の外に書いた)。origin/main の台帳に登録済みなら skipped。
   成功すると report に `registration` (`workspace_repo` / `worktree` / `branch` / `commit` / `file`) と `next` が出る。
   `READY` でも登録はまだ PR になっていない。

   途中で止まった後は、同じ引数に `--resume` を足して再実行する (remote / origin / visibility が一致する時だけ続きから走る)。
   push だけ別経路で済ませた場合は `--resume --skip-push`。`register` の再実行は同じ branch に重ねて commit せず、
   worktree だけ消えていれば branch に付け直す。branch は前回の origin/main を base にしたままなので、PR が BEHIND なら merge 前に追随する。
   commit 前に止まった時の再実行は、前回の未 commit の行を捨て、branch の commit 済みの台帳から今の引数で行を作り直す
   (説明文を直して再実行すれば直した行になる)。差分の検査で fail した branch や、整形ツール自体の修正を取り込みたい branch は
   作り直しが要る。branch の削除は本人の判断に返す。

4. **台帳登録を PR にして、read-back を報告**する。report に `registration` が無い (register が skipped) なら PR は不要。
   ある時は、下の `<worktree>` / `<branch>` に `registration.worktree` / `registration.branch` の値を入れ、次の順に行う。
   wrapper は登録用 worktree の中の版を使う (台帳 repo の main checkout は origin/main より古く、PR 作成入口が無いことがある)。

   1. branch を push する。本文 file はまだ作らない (push の事前検査は未承認の未 commit file があると止まるため)。

```bash
bash <worktree>/shared/scripts/cc-push-resolved.sh --repo <worktree> --branch <branch>
```

   2. PR 本文を `<worktree>/pr-body.md` に日本語で書く (どの repo を何のために登録するか)。
      日本語ゲートはその checkout の中の file しか検査しないので、worktree の中に置く。commit しない。
   3. 本文を検査し、PR を作る。

```bash
python3 <worktree>/shared/scripts/japanese_user_facing_gate.py <worktree>/pr-body.md
python3 <worktree>/shared/scripts/gh_write_guarded.py --repo-root <worktree> -- pr create --base main --head <branch> --title "<日本語の題>" --body-file <worktree>/pr-body.md
```

   4. PR を作ったら本文 file `<worktree>/pr-body.md` を消す。

   - 報告には `verify` の detail (`owner/name (visibility) main=<sha>`) と、登録 PR の URL を書く。merge は人が行う。
     merge 後の worktree と branch の片付けは post-merge-closeout で行う。
   - `push: fail` や登録 PR の push / 作成の拒否は、wrapper の deny 理由をそのまま書く (自分で `git push` / `gh pr create` しない)。
   - 登録 PR の merge を待たずに、新しい repo での作業 (branch push と PR 作成) は始めてよい。push と PR 作成の名義は
     owner から決まり、台帳の表の行には依存しない。

## 前提条件 (この repository の外にある実行前提)

- `gh` に owner の token が入っていること (script は `gh auth token --user <owner>` で取り、対象 process の env にだけ渡す)
- canonical push wrapper `~/Projects/shared/scripts/cc-push-resolved.sh` (無ければ push は fail。`bootstrap/init` を別経路で push して `--resume --skip-push`)
- repo-preflight の checkout `<local-root>/repo-preflight/scripts/readiness_scan.py` (無ければ fail-closed。`--allow-no-preflight` は非推奨)
- account↔repo 台帳 `~/Projects/Documents/references/github-account-repo-map.md` (無ければ register は skip)。
  台帳 repo が origin/main を持ち、そこに台帳 file (挿入位置の行を含む) と `shared/scripts/cc-commit.sh` があり、
  `.worktrees/` が ignore されていること。これらは preflight で BLOCKED にする (repo を作ってから register で止まる主な原因)。
  fetch の失敗や前回の branch の状態は register の時点で初めて分かる
- 手順 4 で使う台帳 repo 側の wrapper (`cc-push-resolved.sh` / `japanese_user_facing_gate.py` / `gh_write_guarded.py`)。
  script は呼ばないので preflight の対象外

script が見つからない・止まった時は、別の手段で同じ操作を組み立てない。止めて報告する。

## やらないこと

- global の `gh auth switch`
- `git push` を直接叩く (wrapper 経由のみ)。main へ push しない (API で作る)
- 台帳 repo の main checkout へ書く (登録は origin/main から切った branch → PR だけ)
- visibility の変更、repo の削除
- 既存 repo への適用 (origin がある directory は対象外)
