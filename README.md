# github-ops-skills

GitHubを複数account・複数repositoryで扱う際に、対象、identity、権限、承認を
混同しないための小さなCore Suiteです。CodexとClaudeから同じ`skills/`を参照し、
GitHub書き込み前にfail-closedで停止できます。

加えて、一般概念のGitOps（Gitを望ましい状態の正本にし、実際の状態との差分を
継続的に検出する運用）をGitHub repository設定へ適用できます。設定変更は自動実行せず、
driftを人がレビューできる差分として返します。

## 安全境界

- 通常のprobeとE2Eはread-onlyです。
- globalな`gh` active accountを切り替えません。
- tokenをfile、引数、出力へ保存しません。
- adapterはhome directoryや設定を変更しません。
- push、PR、repository作成、visibility変更は現在会話の明示承認なしに実行しません。

## ローカル確認

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/gh_identity_probe.py --repo . --json
```

結果は`READY`、`BLOCKED`、`UNKNOWN`の3状態です。`UNKNOWN`を成功として扱いません。
account overlay例は`examples/account-repo-map.example.yaml`にあります。

## GitOpsによるrepository設定のdrift検出

`examples/github-repository-state.example.yaml`を元に、Gitで管理したい設定だけを宣言します。

```powershell
python scripts/github_gitops_reconcile.py `
  --repo . `
  --config examples/github-repository-state.example.yaml
```

- `READY`: 宣言した設定がGitHubの現在値と一致
- `BLOCKED`: driftまたはrepository不一致を検出。自動修復はしない
- `UNKNOWN`: API、identity、設定ファイルの検証を完了できない

これはGitHub設定の全項目を管理する仕組みではありません。visibility、既定branch、説明、
Issues、Wiki、Discussions、Projectsのうち、YAMLに書いた項目だけを照合します。
書き込みは既存のidentity・承認preflightを通す別工程です。

並列作業中のsibling repositoryに未commit変更がある場合は、
`skills/cross-repo-wip-ownership/`と
`schemas/wip-ownership-registry.schema.json`で所有者、期限、依存関係、
secretリスクを`allow`／`warn`／`block`へ分類できます。

保証はL1（静的契約）、L2（ローカル実行）、L3（GitHub read-only実測）、
L4（private canary）を分離します。現在の実測は`PUBLIC_READY.md`を参照してください。
