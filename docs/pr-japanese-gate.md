# PR日本語gateの運用

## 構文契約

- titleは平文日本語とし、Markdown linkを使用しない。
- bodyには日本語のATX見出しを最低1つ置く。
- 英語だけのATX／Setext見出しと、見出し内のMarkdown linkは使用しない。
- title/bodyはUTF-8ファイルでgateとwrapperへ渡す。
- 詳細な理由は[ADR-0001](adr/0001-pr-japanese-gate-boundary.md)を参照する。

ユーザー向け文書とPRのtitle/bodyは日本語を既定にします。コミットメッセージは
repo固有規約を優先し、規約がなければ日本語または英語を選べます。
Conventional Commitsのtype/scope、コード識別子、API名は英語のままで構いません。

PR作成は次の順序を崩しません。

1. 日本語のtitleとbodyファイルを人間が確認する。
2. `scripts/check_pr_japanese.py`でローカルgateを実行する。
3. 現在の会話でcommit、push、PR作成をそれぞれ確認する。
4. local検証に対応するGitHub CIが不足していないか確認し、不足時は追加するか人間へ確認する。
5. account map、期待visibility、固定したbase/head SHAを渡し、`scripts/create_pr_with_japanese_gate.py --confirm`を実行する。
6. ラッパーがidentity、期待visibility、権限、clean、local/remote head、live baseを再確認する。
   既定は`PRIVATE`であり、公開repositoryは人間承認後に`--expected-visibility PUBLIC`を明示する。ラッパーはvisibilityを変更しない。
7. ラッパーが送信直前の名義と既存identity patternを検査する。公開repositoryでは、明示されたrepo外のprivate policyも必須とする。
8. ラッパーが検査済みbody snapshotをstdinから`gh pr create --body-file -`へ渡し、作成後のtitle/body/base/headを再取得して確認する。

`BLOCKED`ではPRを作成しません。`UNKNOWN`はPR作成後の確認失敗を含むため、
重複作成や自動編集をせず、返されたURLを人間が確認します。
fork修飾headは照合対象外としてフェイルクローズで停止します。

## メタデータ限定CI案

ローカルgateだけではWeb UIや別自動化からのPR作成を強制できません。追加防御として、
`.github/workflows/pr-japanese-gate.yml`は`pull_request`のevent metadataだけを検査し、
checkout、secret、write権限を使いません。Web UIや別自動化から作られたPRも検出できます。
必須check化はrepository settingsの外部変更なので、このrepo差分とは分離し、
明示承認後に設定します。workflow追加だけでは必須gateになりません。

`.github/workflows/core-suite-ci.yml`は全test、Python構文、差分形式、Codex／Claude
adapterをGitHub上で再検証します。外部actionは40桁のcommit SHAへ固定し、write権限、
secret、`pull_request_target`を使いません。


## 公開PRの送信payload検査

`PUBLIC_IDENTITY_GUARD_SCRIPT` に信頼済みの外部Python helper、
`PUBLIC_IDENTITY_DENYLIST` に非空UTF-8 policyを、いずれもrepo外の絶対pathで明示します。
helperには `parse_denylist_text(text)` と `scan_private_text(text, patterns)` が必要です。
helperはoperatorが信頼して指定する実行コードであり、未信頼入力をsandbox化する機能ではありません。
未設定・欠落・空policy・不正UTF-8・API欠落・不正応答・検出は送信前に停止します。
private repositoryでも既存 `scan_text` のidentity/token構造検査は省略しません。

bodyはbytesを一度だけ読み、UTF-8の同一snapshotを検査とstdin送信に使用します。
title/body、名義、宛先、base/headを検査し、結果の `payload_check` に対象・実名義・
固定SHA・title/body/helper/policyのSHA-256を記録します。private policyの一致値は出力しません。
helper/policyも読取りsnapshotを検査・hashへ使い、検査後のファイル差替えを送信へ取り込みません。
名義確認と送信は同じprocessの認証選択を使いますが、別processによる認証fileの同時変更を
ロックするものではありません。

この保証は `github-ops-create-pr` の作成経路に限定されます。raw `gh pr create`、
`gh pr edit`、API直送、Web UI、comment、issue、releaseへの強制は別途検証が必要です。
この差分だけで全外部経路や既存履歴が検査済みとは扱いません。
