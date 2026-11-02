# ADR 0006: PRセルフレビューのbase監査とbootstrap境界

> 2026-08-29 に ADR-0002 から採番し直した。0002 は
> `docs/adr/0002-github-write-review-runtime-fail-closed.md` が保持する。
> path 無しの `ADR-0002` 参照 (`PREFLIGHT.md:31`, `PUBLIC_READY.md`,
> `docs/adr/0003-pr-convergence-bounded-controller.md:65`) はすべて ruleset の
> 話題であり、そちらを指していたため。決定内容は変えていない。

- Status: accepted
- Date: 2026-08-23

## Context

`pull_request_target` はbase側のworkflow定義で実行できる一方、そこで作ったcheck runは
PR head SHAに結び付くrequired checkではない。`checks:write`で別のhead-bound statusを発行する
実装やrepository settingsのrequired化は、このrepositoryのread-only安全境界を越える。

また、セルフレビュー文書のdigest allowlistとtrusted検査器を同じPRで変更すると、候補自身が
自分の承認根拠を変更できる。

## Decision

1. `pr-self-review-trusted.yml` はbase側コードで候補treeを読むread-onlyの **advisory** 監査とする。
   `ADVISORY` はmerge許可、required check、head-bound証拠を意味しない。
2. trusted workflow、検査器、digest allowlistの変更はbase比較で停止する。bootstrapまたは更新は、
   人間レビューを伴う別のtrusted changeとして扱う。
3. artifactの候補は、base側allowlistに事前登録されたcanonical LF digestだけを受け入れる。
   allowlistにない更新は自動承認せず、人間bootstrap判断へ戻す。
4. PR作成前の一時indexは`INTENDED_PATHS`で明示したpathだけを取り込み、fail-fastでtreeを記録する。

## Consequences

- base SHA変更時はworkflow dispatchへPR番号を渡して再監査する。自動required化は行わない。
- exact head、CI、review thread、merge判断は別々に再確認する。
- settings変更なしで安全境界を守れるが、bootstrapとallowlist更新には人間の判断が残る。
