# 運用手順

通常確認は`python scripts/run_read_only_e2e.py`で行います。GitHubの設定変更、
投稿、pushは行いません。必要な環境変数が欠ける場合は`BLOCKED`で停止します。

private canaryはreview packetだけを生成します。現versionは`--execute`を指定しても
外部変更しません。実canaryは対象、visibility、送信内容を人間が確認した後の別工程です。
