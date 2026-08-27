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
> 監査元は各マシンの public-repo lockdown 監査 script。個人 home path は repository に書かない。

## 必須ファイル

| ファイル | 要点 |
|---|---|
| `PUBLIC_READY.md` | 公開判定メモ。ローカル確認済み項目 + GitHub 側未検証項目を分けて書く |
| `SECURITY.md` | データ境界 / sensitive data 方針 / 報告経路 |
| `LICENSE` | MIT (コード部分)。名義は **`Copyright (c) <year> nexus_ai`** — 個人名義は決して出さない |
| `README.md` | 「ライセンスと出典」セクション |

## フロー

1. **ライセンスの一次実測**: 外部データを含む場合、配布元の公式ページでライセンス表記を実測する。
   ローカルメモの二次情報だけで断定しない。
2. **出典表記は URL 込み**: CC BY 系は「出典名 + 出典URL + ライセンス名 (ライセンスURL)」を
   標準表記として README と references に置く。
3. **ライセンス区分の明示**: コード (MIT) とミラーデータ (元ライセンス) が混在する repo は、
   README に「LICENSE (MIT) はコード部分のみ、data/ には適用されない」と scope を明記する。
4. **宣言と実装の突合**:
   - 「ネットワークアクセスは○○のみ」→ スクリプトから接続先を実測して全ホスト列挙する。
   - 「無改変 raw mirror」→ 正規化・整形・合成があるならその旨を正確に書く。
5. **報告経路の実体化**: SECURITY.md に外部発見者向けの報告経路を書く。
   GitHub Private vulnerability reporting は **public repo 限定**。private 段階で叩くと
   PUT / GET とも 404 になるため、「public 化の直後に実施する項目」として扱う。
6. **identity 検査** (公開物は nexus 名義のみ):
   - clone 直後に `git config user.name nexus_ai` /
     `user.email 273569186+nexus-ai-2045@users.noreply.github.com`
   - push 前に個人識別子・個人 path を検査する (`scripts/public_identity_guard.py` 等)
   - commit 後に `git log --format="%an <%ae>"` で author/committer を実測する
7. **push / owner 導出**:
   - repo↔account 表 (人間向け inventory) を確認する
   - 廃止済み allowlist へ追記しない。現行 identity registry / owner 導出を一次確認する
   - 着手前に `git show origin/main:<対象ファイル>` で現物を見る
8. **push 経路**: main 直 push は禁止。branch + PR。
9. **bot レビュー回収**: PR 作成後に `gh pr checks` と review comments を取得し、
   P2 以上は解消してから merge 判断へ進む。

## public 化の直後にやること (順序固定)

1. secret scanning / push protection を明示的に有効化し、実測する。
2. Private vulnerability reporting を有効化する。
3. `PUBLIC_READY.md` を公開後の実態に書き直す。
4. 途中で落とした手順があれば理由を `PUBLIC_READY.md` に残す。

## 検証クローズ

- `gh pr view <n> --json state,files` と commits の author を実測してから完了報告する。
- merge 判定は `git branch --merged` を使わない。**squash merge だと元 commit が
  origin/main の祖先にならず偽陰性になる**。PR の `mergedAt` か内容照合で判定する。
- merge 後は public-repo lockdown 監査を実行し PASS を確認する。

## この Core Suite での補助

```powershell
python scripts/public_identity_guard.py --help
python scripts/gh_identity_probe.py --repo . --json
python scripts/check_visibility_claim.py --public-ready PUBLIC_READY.md --status-code <unauth-http-status> --json
```

公開oracleは未ログインHTTP 200/404。ownerログインの `gh repo view` では公開判定しない。

公開・visibility 変更・release は現在会話の明示承認なしに実行しない。
