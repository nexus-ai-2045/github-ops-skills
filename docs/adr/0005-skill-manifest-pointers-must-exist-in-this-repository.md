# ADR 0005: skill manifest の ssot_pointers はこの repository に実在すること

- status: accepted
- date: 2026-08-28

## 背景

`skills/*/manifest.yaml` は `ssot_pointers` でその skill の正本を宣言する。
しかし宣言を検証する lint（nexus-ai-skills の `shared/scripts/skills_lint.py`
の L3 `check_l3_pointers`）は**この repository へ配布されていない**。

結果として、移植時に manifest だけが来て実体が来ない状態が CI を通過していた。
実測（2026-08-28）で 6 件の違反が残っていた。

| manifest | 内容 |
|---|---|
| `skills/post-merge-closeout/manifest.yaml` | ヘッダが `shared/skills/...` を正本と宣言。`ssot_pointers` が `shared/scripts/post_merge_closeout_report.py`（不在） |
| `skills/pr-convergence-loop/manifest.yaml` | ヘッダ同上。`ssot_pointers` 3 件すべて不在 |

ヘッダは配布エンジン `shared/scripts/skills_distribute.py` と drift lint
`shared/scripts/skills_lint.py` も指しているが、どちらもこの repository に無い。
**移植元のヘッダを丸ごと持ち込んだ痕跡**であり、manifest が自分の所在について
嘘をついている状態だった。

同種の問題は他にもある。`skills/post-merge-closeout/SKILL.md` の手順は
`shared/scripts/post_merge_closeout_report.py` の実行を指示するが、この
repository を単体で clone した利用者はそれを実行できない。

## 決定

1. `ssot_pointers` は「**この repository 内**で、その skill の正本にあたる file」
   だけを指す。host workspace 側の script は正本ではなく**実行前提**なので、
   `ssot_pointers` ではなく SKILL.md の「前提条件」に書く。
2. manifest ヘッダで正本を名乗る時は `# SSOT in this repository: ...` の形にする。
   この形は `skills/github-cli-ops-guard/manifest.yaml` で既に使われている。
3. `scripts/verify_skill_manifests.py` を追加し、`core-suite-ci.yml` で必須化する。
   宣言先の実在、repository 外への脱出、外部正本を名乗るヘッダを検査する。
4. 対症療法として script を複製しない。複製すると同じ処理の実装が増え、
   どれが正本か分からなくなる。script が見つからない時は**止めて報告する**と
   SKILL.md に明記した。

## 代替案と却下理由

- **`skills_lint.py` をこの repository へ複製する**: 正本が 2 つになる。
  この ADR が塞ごうとしている問題そのものを再生産する。
- **host workspace の script をこの repository へ取り込む**: `post_merge_cleanup.py`
  は同名の別実装が複数あり（host workspace 版と fractal-decision-ecosystem 版で
  option が異なる）、取り込むと 3 つ目の実装になる。
- **何もせず manifest だけ直す**: 次の移植で同じ状態が再発する。宣言と執行が
  離れていることが原因であって、個々の値が原因ではない。

## 保証と非保証

- 保証: `ssot_pointers` に書かれた path がこの repository に実在すること。
  外部正本を名乗るヘッダが残っていないこと。CI で必須。
- 非保証: host workspace 側の script が実在すること（この repository からは
  検査できない）。SKILL.md 本文中のコマンド例に書かれた path の実在。
  `ssot_pointers` に書かれた file の**中身**が正しいこと。

## 検証

```bash
python scripts/verify_skill_manifests.py
```

修正前は 6 件の error で exit 1、修正後は exit 0。
回帰は `tests/unit/test_skill_manifest_pointers.py` が固定する。
