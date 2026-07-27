# Codex adapter

このadapterは、repository内の`skills/`が読み取れることだけを検証します。
home directoryへのcopy、symlink作成、設定変更は行いません。

```powershell
python adapters/codex/verify_adapter.py --repo . --json
```
