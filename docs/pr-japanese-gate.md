# PR日本語gateの運用

ユーザー向け文書とPRのtitle/bodyは日本語を既定にします。コミットメッセージは
repo固有規約を優先し、規約がなければ日本語または英語を選べます。
Conventional Commitsのtype/scope、コード識別子、API名は英語のままで構いません。

PR作成は次の順序を崩しません。

1. 日本語のtitleとbodyファイルを人間が確認する。
2. `scripts/check_pr_japanese.py`でローカルgateを実行する。
3. 現在の会話でcommit、push、PR作成をそれぞれ確認する。
4. local検証に対応するGitHub CIが不足していないか確認し、不足時は追加するか人間へ確認する。
5. account mapと固定したbase/head SHAを渡し、`scripts/create_pr_with_japanese_gate.py --confirm`を実行する。
6. ラッパーがidentity、PRIVATE、権限、clean、local/remote head、baseを再確認する。
7. ラッパーが検査済みbody snapshotをstdinから`gh pr create --body-file -`へ渡し、作成後のtitle/body/base/headを再取得して確認する。

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
