---
name: public-repo-readiness
description: >
  公開 GitHub repo の lockdown 整備 (PUBLIC_READY.md / SECURITY.md / LICENSE / 出典表記) を行うスキル。
  「公開repoを整備して」「PUBLIC_READY を作って」「lockdown 監査を通して」「repo を公開準備して」
  「公開repoのライセンス整備」と言われたら使用する。audit-public-repo-lockdown.ps1 の FAIL 解消にも使う。
  Do NOT use for: private repo の整備、監査スクリプト自体の修正、repo の新規作成。
---

# public-repo-readiness — 公開 repo lockdown 整備フロー

> 起源: 2026-07-19 nanyo-prompt-orchestrator PR #1 整備セッション。
> Codex bot レビューで「宣言と実装の不一致」を 3 件指摘された教訓を含む。
> 監査元: `<USER_HOME>\Documents\Codex\2026-05-20\github\scripts\audit-public-repo-lockdown.ps1`
> (6h ごと。PUBLIC_READY.md 欠落 / secret scanning disabled で exit 1)

## 必須ファイル

| ファイル | 要点 |
|---|---|
| `PUBLIC_READY.md` | 公開判定メモ。ローカル確認済み項目 + GitHub 側未検証項目を分けて書く |
| `SECURITY.md` | データ境界 / sensitive data 方針 / 報告経路 |
| `LICENSE` | MIT (コード部分)。名義は **`Copyright (c) <year> nexus_ai`** — <PRIVATE_IDENTIFIER> は決して出さない |
| `README.md` | 「ライセンスと出典」セクション (下記) |

## フロー

1. **ライセンスの一次実測**: 外部データを含む場合、配布元の公式ページでライセンス表記を実測する
   (CiC / browser。公式が落ちていたら Wayback Machine のスナップショットで確認し、確認日と経路を記録)。
   ローカルメモの「CC BY 4.0」等は二次情報 — 必ず裏取り (盲点 8)。
2. **出典表記は URL 込み**: CC BY 系は「出典名 + 出典URL + ライセンス名 (ライセンスURL)」を
   標準表記として README と references に置く。CEO 方針: 出典は URL で明示する。
3. **ライセンス区分の明示**: コード (MIT) とミラーデータ (元ライセンス) が混在する repo は、
   README に「LICENSE (MIT) はコード部分のみ、data/ には適用されない」と scope を明記する。
4. **宣言と実装の突合** (Codex レビューで刺された点):
   - 「ネットワークアクセスは○○のみ」→ スクリプトから接続先を実 grep して全ホスト列挙する
     (`grep -rhoE 'https?://[a-zA-Z0-9.-]+' scripts/ | sort -u`)。
   - 「無改変 raw mirror」→ 正規化・整形・合成があるならその旨を正確に書く
     (raw フィールドと加工フィールドを区別)。CC BY の「変更の有無」表示に直結する。
5. **報告経路の実体化**: SECURITY.md に外部発見者向けの報告経路を書き、
   GitHub Private vulnerability reporting を有効化する:
   `gh api -X PUT repos/<owner>/<repo>/private-vulnerability-reporting` → GET で enabled=true を実測。
6. **identity 検査** (公開物は nexus 名義のみ):
   - clone 直後に `git config user.name nexus_ai` / `user.email 273569186+nexus-ai-2045@users.noreply.github.com`
   - push 前に内容 grep: `grep -riE 'say_yas|tamagoe|lm93|(^|[^a-z])<PRIVATE_IDENTIFIER>([^a-z]|$)' <対象ファイル>`
   - commit 後に `git log --format="%an <%ae>"` で author/committer 実測
7. **push_gate 登録** (未登録 repo は fail-closed deny):
   - `Documents/references/github-account-repo-map.md` の表 + machine-readable yaml に追記
   - `shared/scripts/push_gate.sh` の `PUBLIC_PUSH_ALLOWLIST` に追記 (CEO 承認必須 / Type1)
8. **push 経路**: sandbox cwd 固定のセッションでは push_gate が cwd で repo 判定するため
   gate を通せない。PowerShell script (BOM 付き UTF-8、identity check 内蔵) を作り、
   CEO 承認の上で実行する。main 直 push は禁止 — branch + PR。
9. **bot レビュー回収**: PR 作成後に `gh pr checks` と
   `gh api repos/<o>/<r>/pulls/<n>/comments` で bot 指摘を取得し、P2 以上は解消してから merge。

## 検証クローズ

- `gh pr view <n> --json state,files` と commits の author を実測してから完了報告 (盲点 2)。
- merge 後は監査タスクを手動起動して PASS 確認: `Start-ScheduledTask "GitHub Public Repo Lockdown"`
  → `logs/audit-public-repo-lockdown-*.log` に "All monitored public repositories passed." を確認。
