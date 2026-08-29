# ADR 0008: 検査は「対象が無い / 空」を合格にしない。それを機械で確認する

- status: accepted
- date: 2026-08-29

## 背景

2026-08-29 に出した検査 3 本（repo-preflight #45 / #46、この repository の #21）を
敵対的にレビューし直したところ、実バグが **9 件**出た。CI はいずれも green だった。

**9 件中 8 件が同じ形**だった。

> 検査対象が空、または想定と違う場所にあるのに、`status: pass` を返す。

`docs/pr-self-review.md` の **R1「検査は未確定を合格にしない」** そのものであり、
**R14「指摘は型で再発する」** の実例でもある。実際、`verify_skill_manifests.py`
(ADR-0005) と `verify_adr_numbering.py` (ADR-0007) は**独立に同じ 0 件 fail-open**
を持っていた。1 本を直すだけでは同じ型が残る。

現行 `main` を実測したところ、既存 3 本のすべてに穴があった。

| checker | 対象が無い | 対象が空 |
|---|---|---|
| `verify_invariant_registry.py` | `FileNotFoundError` で死ぬ | `JSONDecodeError` で死ぬ |
| `verify_skill_manifests.py` | 拒否する | **素通り**（所見 0 件で pass） |
| `verify_source_manifest_targets.py` | 拒否する | `JSONDecodeError` で死ぬ |

例外で死ぬのも同じ問題である。所見を `list` で返す契約が破れ、呼び出し側は
JSON ではなく traceback を受け取る。

## 決定

1. `scripts/verify_*.py`（`verify_checker_contracts.py` 自身を除く）は `SUBJECT`
   （検査対象の repo 相対 path。実在すること・相対であること・`..` を含まないこと）
   と `verify(repo) -> list[str]` を公開する。
2. 対象が**存在しない** repo、対象は存在するが**空**の repo のどちらでも、
   所見を返す（＝合格にしない）。例外を投げない。`sys.exit` もしない。
   所見の各要素は空でない `str` とする。
3. `scripts/verify_checker_contracts.py` を追加し、`core-suite-ci.yml` で必須化する。
   この検査は**宣言を読むのではなく、実際に `verify()` を呼ぶ**。
4. 上表の 3 件を修正する。

### probe は空 repo ではなく「正常な複製」から作る

当初は空の tmp ディレクトリを repo に見立てて probe していたが、Codex review
(2026-08-29) の指摘で**偽陰性**になることが分かった。実測で確認している。

- 対象を一切見ない checker が、無関係な「あれが無い」という所見だけで
  両方の probe を満たして合格する
- 対象が file か dir かを suffix から推測していたため、`LICENSE` のような
  拡張子無しの file が dir として作られ、checker が型違いで拒否した結果
  「空の対象を拒否した」と誤判定される

よって repo の正常な複製を作り、**先に所見ゼロを確認してから、宣言された対象
だけを壊す**。file / dir の別も実在するエントリから決める。こうすると所見が
変異に起因すると言い切れる。

## 代替案と却下理由

- **「negative テストを持っているか」を検査する**（ESLint の `RuleTester` が
  `invalid` ケースを必須にするのと同じ発想）: **実測で効かないことを確認した**ので
  却下。バグ 4 件を抱えていた `verify_adr_numbering.py` の初版にも negative テストは
  **6 件あった**。既存 3 本にも 2 / 5 / 4 件ある。この検査では上記 9 件を**1 件も
  捕まえられない**。効かない検査を足すのは、この ADR が塞ごうとしている問題の
  再生産にあたる。
- **チェックリストに項目を足して遵守を求める**: `docs/pr-self-review.md` は
  この repository に配布済みで、CI が改竄まで検出している。その状態で 8 件の
  R1 違反が出た。「書いて読ませる」の保証価値は実測でゼロだった。
  そもそも「守りましたか」と尋ねて「はい」を合格にするのは R1 違反そのものである。
- **汎用の変異テスト（mutation testing）を導入する**: 対象が checker に限られる
  この repository では過剰。実行時間も増える。壊れた入力を 2 通り食わせるだけで、
  実測された型は塞げる。
- **各 checker に個別の空振りテストを書く**: 書き忘れを止められない。
  新しい checker を足した人が忘れた瞬間に穴が開く。列挙して機械で回すほうが強い。

## 保証と非保証

- 保証: `scripts/verify_*.py`（`verify_checker_contracts.py` 自身を除く）が、
  対象の不在と対象の空を合格にしないこと。例外でも `sys.exit` でもなく、空でない
  `str` の list で所見を返すこと。`SUBJECT` と `verify()` を公開し、`SUBJECT` が
  repo 内に実在すること。所見が変異に起因すること（正常な複製で所見ゼロである
  ことを先に確認する）。`verify_checker_contracts.py` 自身は glob から自己除外し、
  `verify_*.py` が 0 件なら合格にしないこと。CI で必須。
- 保証: probe が複製の外へ書き込まないこと。`SUBJECT` が絶対 path、`..`、
  **途中の symlink** を含む場合は probe を実行せずに落とす。
  変異そのものに失敗した場合も、例外ではなく所見で返す。
- 非保証: `scripts/` 以外の場所にある `verify_*.py`。とくに
  `adapters/*/verify_adapter.py` は名前が一致するが、返り値が `dict` で
  `list[str]` 契約を原理的に満たさないため対象外。
- 非保証: 対象を**正しく列挙できているか**。実測した 9 件のうち、下位ディレクトリの
  取りこぼし・`.MD`・全角数字（ADR-0007 参照）はこの検査では捕まらない。
  これらは各 checker 側のテストが受け持つ。
  検査の**内容**が正しいこと。`scripts/check_*.py` など `verify_` で始まらない
  script（命名規約が宣言を兼ねているため、対象外）。

## 検証

```bash
python scripts/verify_checker_contracts.py
```

修正前の `main` にこの script だけを持ち込んで実行すると、上表の 4 件を検出して
exit 1（`SUBJECT` 宣言のみ先に足した状態で実測）。修正後は exit 0。
回帰は `tests/unit/test_checker_contracts.py` が固定する（本番の `scripts/` を
検査する `test_this_repository_passes` を含む）。

Codex review で見つかった 5 件（`sys.exit` の素通り、probe の複製外への書き込み、
空文字の所見、suffix による型推測、無関係な所見で契約を満たす）も、**修正前の
コードで新テスト 6 件が落ちることを実測してから**塞いでいる。

さらにセルフレビュー第 2 巡で 5 件。とくに重かったのは、`..` と絶対 path を
塞いでも **repo 内の symlink 経由で複製の外へ抜けられた**こと。実測で複製外の
実ディレクトリが `rmtree` された。`src/github_ops/source_manifest.py` の
`_unsafe_component` が同じ脅威を既に扱っていたのに、その防御が probe の
書き込み経路へ適用されていなかった。同時に `_unsafe_component` 側の
「lstat 失敗はすべて unsafe」も直した ── 単なる不在が symlink 攻撃と
同じ signal になっており、`verify_target_hashes` が不在を報告できずに
`"unsafe manifest path"` を返していた（この検査の「対象が無い」probe が
**対象を読む前の別の理由**で満たされていた＝この ADR が塞ごうとしている
偽陰性そのもの）。CI step 自体もテストで固定していなかったので、
`tests/unit/test_core_suite_workflow.py` へ `verify_*` の 5 step を追加した。
