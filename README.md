# github-ops-skills

GitHubを複数account・複数repositoryで扱う際に、対象、identity、権限、承認を
混同しないための小さなCore Suiteです。Codex、Claude、Grokから同じ`skills/`を参照し、
GitHub書き込み前にfail-closedで停止できます。

## 安全境界

- 通常のprobeとE2Eはread-onlyです。
- globalな`gh` active accountを切り替えません。
- tokenをfile、引数、出力へ保存しません。
- adapterはhome directoryや設定を変更しません。
- push、PR、repository作成、visibility変更は現在会話の明示承認なしに実行しません。
- PR title/bodyは日本語gateを通し、作成後に承認済み入力との一致をread-backします。

## ローカル確認

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/gh_identity_probe.py --repo . --json
```

結果は`READY`、`BLOCKED`、`UNKNOWN`の3状態です。`UNKNOWN`を成功として扱いません。
account overlay例は`examples/account-repo-map.example.yaml`にあります。
PR作成手順は`docs/pr-japanese-gate.md`を参照してください。

並列作業中のsibling repositoryに未commit変更がある場合は、
`skills/cross-repo-wip-ownership/`と
`schemas/wip-ownership-registry.schema.json`で所有者、期限、依存関係、
secretリスクを`allow`／`warn`／`block`へ分類できます。

保証はL1（静的契約）、L2（ローカル実行）、L3（GitHub read-only実測）、
L4（private canary）を分離します。現在の実測は`PUBLIC_READY.md`を参照してください。
