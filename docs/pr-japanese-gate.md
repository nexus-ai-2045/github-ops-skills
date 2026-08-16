# PR日本語gateの運用

ユーザー向け文書とPRのtitle/bodyは日本語を既定にします。コミットメッセージは
repo固有規約を優先し、規約がなければ日本語または英語を選べます。
Conventional Commitsのtype/scope、コード識別子、API名は英語のままで構いません。

PR作成は次の順序を崩しません。

1. 日本語のtitleとbodyファイルを人間が確認する。
2. `scripts/check_pr_japanese.py`でローカルgateを実行する。
3. 現在の会話でcommit、push、PR作成をそれぞれ確認する。
4. `scripts/create_pr_with_japanese_gate.py --confirm`を実行する。
5. wrapperが`gh pr create --body-file`を実行し、作成後のtitle/body/base/headをread-backする。

`BLOCKED`ではPRを作成しません。`UNKNOWN`はPR作成後の確認失敗を含むため、
重複作成や自動編集をせず、返されたURLを人間が確認します。

## metadata-only CI案

ローカルgateだけではWeb UIや別自動化からのPR作成を強制できません。追加防御として、
`.github/workflows/pr-japanese-gate.yml`は`pull_request`のevent metadataだけを検査し、
checkout、secret、write権限を使いません。Web UIや別自動化から作られたPRも検出できます。
required check化はrepository settingsの外部変更なので、このrepo差分とは分離し、
明示承認後に設定します。workflow追加だけではrequired gateになりません。
