# ADR-0002: GitHub write・review・runtime検査は実効状態をfail-closedで確認する

- 状態: 採用
- 日付: 2026-08-19

## 背景

GitHub操作の安全性は、表示上のremote、branch名、ファイル名だけでは保証できない。
Gitはfetch URLとpush URLを分けられ、PRはpagination中にもHEADが変化し得る。また、
runtime fileは欠落、symlink、Windows junctionなどにより独立copyに見えて実体が異なる
可能性がある。

これらを推測でcompliantへ倒すと、別repositoryへのpush、異なるHEADのreview evidence混在、
未配布runtimeの見逃しにつながる。

## 決定

- GitHub write前はoriginの実効push URLを全件取得し、1件だけであること、fetch先と同じ
  `owner/name`であること、実効credentialが期待loginであることを確認する。
- review threadを複数ページ取得する場合は、全ページで同じ`headRefOid`を要求する。
- pagination cursorの欠落・反復、上限超過、GraphQL error、壊れた`pageInfo`は成功扱いしない。
- runtime copy検査では、manifestに宣言されたsourceの欠落、symlink、junction／reparse point、
  root外参照、読取不能を成功扱いしない。
- 観測不能または応答不正は`UNKNOWN`または`BLOCKED`として停止し、disabled、clean、
  compliantへ推測変換しない。

## 許可範囲

- repository内のread-only probe、drift検査、review thread監査。
- tokenをログへ出さないcommand-local identity検証。
- sourceとruntimeのhash比較、および人間レビュー用evidence生成。

## 禁止範囲

- 本契約を根拠にした自動merge、GitHub Settings変更、visibility変更。
- runtime homeへの無承認上書き、一括同期、既存配布エンジンの迂回。
- API errorや欠落値を安全側の具体状態へ推測すること。

## 人間レビュー境界

- commit、push、PR作成・編集、mergeはそれぞれ既存の承認境界に従う。
- merge判断はPR番号、base SHA、head SHA、CI、未解決threadを同時にread-backする。
- runtime配布とProjects側pointer化はcanonical確定後の別差分とする。
- ruleset、required check、Actions制限などserver-side enforcementは別の設定変更承認を必要とする。

## 結果

- local gateは実効状態を検証するため、従来より停止条件が増える。
- 誤検知時も安全機能を迂回せず、原因を特定して入力または設定を修正する。
- runtime配布機能やmerge orchestratorをこのrepository内で重複実装せず、既存の配布・PR
  lifecycle資源へ検査結果を入力する。
- 新しい失敗モードは回帰testへ追加し、同じreview指摘を再発させない。

## 参照

- Git remote: https://git-scm.com/docs/git-remote
- GitHub GraphQL pagination: https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api
- GitHub rulesets: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
