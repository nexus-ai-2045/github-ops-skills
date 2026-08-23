# Review findingの横断フィードバックループ

個別reviewコメントをそのまま別repositoryへコピーせず、再現できた根本原因だけを
`policy/invariants.json`の不変条件へ昇格する。不変条件には安定ID、説明、強制方法、
回帰testを束縛する。CIはregistryとtest path、source manifestのtarget digestを検証する。

```text
review finding -> 独立再現 -> invariant ID -> 回帰test -> canonical SHA
               -> consumer thin caller -> CI receipt -> 再発測定
```

consumerへの配布は既存の`nexus-ai-skills` distribute系が所有する。このrepositoryでは
配布エンジンを再実装せず、canonical SHA/digestと検証契約を提供する。organization
rulesetのEvaluate/Active切替、required workflow、runtime上書きは別の人間承認境界とする。

同型findingが再発した場合は新IDを増やさず、既存IDのtest coverageまたはenforcementを
強化する。コメント本文、token、credential、個人pathはregistryやreceiptへ保存しない。
