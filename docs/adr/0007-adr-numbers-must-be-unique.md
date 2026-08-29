# ADR 0007: ADR の採番は一意で、機械検査に載せる

- status: accepted
- date: 2026-08-29

## 背景

この repository の ADR は **path 無しの `ADR-NNNN`** で参照される。

| 参照元 | 記述 |
|---|---|
| `PREFLIGHT.md:31` | `required status checks / ruleset（rulesets 空。ADR-0002 の別承認）` |
| `PUBLIC_READY.md:15` | `ruleset は未設定（ADR-0002）` |
| `docs/adr/0003-pr-convergence-bounded-controller.md:65` | `ADR-0002: docs/adr/0002-github-write-review-runtime-fail-closed.md` |

実測（2026-08-29）で `0002` が 2 つの file に割り当てられていた。

- `docs/adr/0002-github-write-review-runtime-fail-closed.md`
- `docs/adr/0002-pr-self-review-advisory-bootstrap.md`

このとき path 無しの `ADR-0002` は**どちらを指すのか決定できない**。決定記録が
同定できない状態は、記録が無いのとほぼ同じ危険度になる。しかも 3 件の参照は
どれも「番号だけ」で書かれているので、読み手が推測で解決するしかなかった。

採番を検査する lint は、ADR-0005 の `ssot_pointers` と同じ構図で
**この repository へ配布されていない**。宣言（`docs/adr/`）だけが移植されて
執行が届いていない。

## 決定

1. `docs/adr/` の file 名は `NNNN-slug.md`（`NNNN` は **ASCII 数字 4 桁**、拡張子は
   小文字 `.md`）とし、`NNNN` は**一意**とする。ADR は `docs/adr/` **直下**に置く。
2. 本文 1 行目の見出しが名乗る番号は file 名の番号と一致させる。
   rename して見出しを直し忘れる事故を機械で拾う。
3. `scripts/verify_adr_numbering.py` を追加し、`core-suite-ci.yml` で必須化する。
4. 既存の衝突は、`0002` を
   `docs/adr/0002-github-write-review-runtime-fail-closed.md` に残して解消する。
   上表の 3 件の参照はすべて **ruleset の話題**であり、そちらを指していたため。
   もう一方は `0006-pr-self-review-advisory-bootstrap.md` へ採番し直す。
   決定内容は変更しない。

## 代替案と却下理由

- **参照側に path を書き足して衝突を放置する**: 対症療法。次に ADR を足す人が
  同じ番号を選ぶのを止められない。番号で参照する運用自体は他の ADR でも
  使われており、そちらを壊さずに済む。
- **`0002-github-write-review-runtime-fail-closed.md` の方を動かす**:
  `0003:65` が path 付きでそれを `ADR-0002` として束縛している。動かすと
  その記述が嘘になる。参照が少ない側を動かすのが安全。
- **欠番も禁止する**: 過検知になる。ADR を取り下げた跡や、並行 PR で番号を
  予約した跡として欠番は正常に発生する。検査対象にしない。
- **`glob("*.md")` で拾えたものだけを見る**: 2026-08-29 のセルフレビューで、
  これが 3 通りに空振りすることを実測した。**いずれも `status: pass` を返す**
  （`docs/pr-self-review.md` R1「検査は未確定を合格にしない」違反）。
  - `docs/adr/` が空でも `pass`。ADR を別の場所へ移した瞬間、保証が空虚に満たされる
  - 下位ディレクトリ（`docs/adr/2026/`）の ADR は列挙されない。そこに衝突があっても `pass`
  - `0002-B.MD` は Linux の case-sensitive glob で列挙されない。**macOS では列挙される**
    ため、同じ tree で CI とローカルの判定が割れる
  よって `iterdir()` で全エントリを見て、形が違えば落とす。0 件も落とす。
- **YAML front matter などの形式を導入する**: 既存 6 件の書式を全部書き換える
  ことになり、この ADR が解こうとしている問題（同定不能）とは無関係。

## 保証と非保証

- 保証: `docs/adr/` 内で番号が重複しないこと。file 名と見出しの番号が
  一致すること。`docs/adr/` 直下の**すべての**エントリが `NNNN-slug.md` の形で
  あること（下位ディレクトリ・大文字拡張子・ADR 以外の file はエラー）。
  番号が ASCII 数字であること。`docs/adr/` が空でないこと。CI で必須。
- 非保証: 欠番が無いこと（検査しない）。ADR の内容・status・相互参照の
  正しさ。`docs/architecture.md` の索引が全 ADR を列挙していること
  （索引の網羅性を検査する仕組みは無い）。path 無し参照が**どの ADR を
  指すつもりだったか**の推定 ── 衝突を無くすことで推定が不要になる、
  という形で解いている。

## 検証

```bash
python scripts/verify_adr_numbering.py
```

修正前は `ADR-0002 is claimed by 2 files` で exit 1、修正後は exit 0。
回帰は `tests/unit/test_adr_numbering.py` が固定する（本番の `docs/adr/` を
検査する `test_this_repository_passes` を含む）。上記 3 つの空振り経路も、
**修正前のコードで新テストが落ちることを実測してから**塞いでいる。

同じ 0 件 fail-open が `scripts/verify_skill_manifests.py`（ADR-0005）にも
あったので、同時に塞いだ。片方だけ直すと同じ型が残る（R14「指摘は型で再発する」）。
