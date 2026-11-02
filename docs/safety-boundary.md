# 安全境界

許可される既定動作はローカル読取とGitHub read-only APIだけです。system設定変更、
global account切替、process終了、push、PR作成、repository作成、visibility変更、
公開、共有は自動実行しません。`BLOCKED`と`UNKNOWN`は停止状態です。

GitOpsのdesired stateは変更承認ではありません。特にvisibilityを`PUBLIC`と宣言しても、
repository固有の人間確認なしに公開範囲を変更しません。drift検出結果から自動的に
`gh repo edit`を実行する経路は提供しません。

作業時の必須契約名は[`README.md`](../README.md)の「必須契約」に従います。
この文書は追加の実行手順を定義しません。
