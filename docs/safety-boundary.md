# 安全境界

許可される既定動作はローカル読取とGitHub read-only APIだけです。system設定変更、
global account切替、process終了、push、PR作成、repository作成、visibility変更、
公開、共有は自動実行しません。`BLOCKED`と`UNKNOWN`は停止状態です。
