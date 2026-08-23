# ADR-0004: Review findingは不変条件へ昇格する

- 状態: 採用
- 日付: 2026-08-20

## 背景

PRごとのreviewコメントだけでは、同型不具合を別機能や別repositoryで再発させ得る。一方、
コメント全文の集約や新しい配布基盤は、未信頼入力・秘密情報・責務重複を増やす。

## 決定

- findingは独立再現できた根本原因だけを、安定ID付きのrepo-local不変条件へ昇格する。
- 各不変条件を回帰testへ束縛し、registryとtest pathをCIで自己検証する。
- 配布対象はcanonical commit SHAとmanifest digestへ束縛する。
- runtime／他repositoryへの配布は既存`nexus-ai-skills`が所有し、本repositoryでは再実装しない。
- コメント本文、token、credential、個人pathはregistryやreceiptへ保存しない。
- required check、ruleset、runtime上書きはコード変更と分離した人間承認境界とする。

## 結果

同型findingは新しいコメント知識ではなく、既存IDのtestまたはenforcement強化として扱える。
CIは再発を機械的に止めるが、GitHub Settings変更やconsumer配布を暗黙には実行しない。
