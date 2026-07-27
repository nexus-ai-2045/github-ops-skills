# GitHub Operations Skills 設計

## 記録情報

- schema_version: `fact-provenance/v1`
- recorded_at: `2026-07-28T02:02:42+09:00`
- recorded_by: `codex`
- status: `expected_login分離の修正差分レビュー待ち`
- visibility_intent: `private`

## 目的

複数のローカルGitリポジトリで再利用できるGitHub操作スキル群を、独立した単一の正本（SSOT）として管理する。

主な目的は、複数GitHubアカウントを使う環境で、誤ったアカウント・owner・repositoryに対する操作を防ぎながら、commit、push、PR確認、レビュー、公開準備、merge後確認を一貫した安全境界で扱うことである。

本リポジトリはGitHub操作の共通部品を提供する。個別プロジェクトのrelease判断、repository公開、merge、外部共有を自動承認するものではない。

## 採用した構成

```text
github-ops-skills/
├─ skills/
│  ├─ github-cli-ops-guard/
│  ├─ commit-push-pr/
│  ├─ pr-status/
│  ├─ review-pr/
│  ├─ public-repo-readiness/
│  ├─ post-merge-closeout/
│  └─ pr-convergence-loop/
├─ scripts/
│  ├─ gh_identity_probe.py
│  ├─ github_pr_readiness_preflight.py
│  ├─ github_account_context.py
│  ├─ check_pr_japanese.py
│  └─ public_identity_guard.py
├─ schemas/
│  └─ account-repo-map.schema.yaml
├─ examples/
│  └─ account-repo-map.example.yaml
├─ adapters/
│  ├─ codex/
│  └─ claude/
├─ tests/
│  ├─ unit/
│  └─ e2e/
└─ docs/
   ├─ architecture.md
   ├─ safety-boundary.md
   └─ migration.md
```

## データ境界

製品リポジトリへ保存してよいものは、schema、匿名化したexample、汎用スクリプト、テストfixture、運用文書に限定する。

次の情報はリポジトリへ保存しない。

- token、cookie、credential
- 個人用account map
- private repository一覧
- 個人の絶対パス
- 実在する非公開owner/repositoryを含むfixture

実データはリポジトリ外のローカルoverlayへ置く。adapterはoverlayの場所を設定として受け取り、存在しない場合やschema検証に失敗した場合は処理を停止する。

## 操作フロー

```text
GitHub操作要求
  → 対象repository、期待owner、期待loginを解決
  → ローカルoverlayを検証
  → identity probe
  → 操作別preflight
  → 必要な人間承認を確認
  → 対象を限定して操作
  → read-onlyで結果を再確認
  → global active accountが不変か確認
```

## identityモデル

次のidentityを別々に観測し、同一のものとして推測しない。

- `expected_owner`
- `expected_login`
- 現在の`gh` active account
- 対象processへ渡されたtokenのlogin
- Git remoteのowner
- credential helperが返すusername
- Git author
- Git committer

### validated-token mode

global accountを切り替えずに対象アカウントを使う場合は、次を満たす。

1. token値を画面・ログへ表示せず取得する。
2. そのtokenを使った`gh api user`でloginを確認する。
3. loginがoverlayの`expected_login`と一致する場合だけ続行する。organization所有repositoryでは`expected_owner`と`expected_login`が異なることを正常系として扱う。
4. tokenは対象commandまたは子processだけへ渡す。
5. command終了後に環境から除去する。
6. 操作前後でglobal active accountが変化していないことを確認する。

tokenが存在するだけでは安全証明としない。loginを一次確認できなければ`BLOCKED`とする。

globalな`gh auth switch`は既定経路では使わない。明示的な復旧操作としてユーザーが承認した場合だけ候補にできる。

## 結果とエラー契約

すべてのpreflightと操作結果は次のいずれかとする。

- `READY`: 必須証拠が揃い、指定操作へ進める。
- `BLOCKED`: 安全条件を満たさず、停止理由と復旧手順が確定している。
- `UNKNOWN`: 一次確認できず、現在状態を断定できない。

暗黙のaccount切替、対象repositoryの推測、失敗後の別credentialへの自動fallbackは行わない。

人間向け出力には次を含める。

- 原因
- 影響
- 安全な次の確認または復旧手順

機械向けには同内容をJSONで返す。secret値は標準出力、標準エラー、例外、fixture、snapshotへ含めない。

## fail-closed条件

少なくとも次の場合は書き込みを行わない。

- ownerまたはrepositoryを一意に解決できない
- token loginと期待loginが不一致
- remote ownerが期待値と不一致
- 必須overlayがない、またはschema不適合
- 対象外のdirty worktreeを含む
- stage対象を明示できない
- 必要な現在会話の承認がない
- repository visibilityを確認できない
- public化、merge、release、外部共有に個別承認がない
- GitHub API結果が404、権限不足、または相互に矛盾する

## GitHub書き込み契約

書き込み成功の判定には、次のすべてを必要とする。

1. 対象repository、branch、操作が明示されている。
2. identityと権限のpreflightが`READY`である。
3. worktreeとstage対象が意図した範囲である。
4. 操作に必要な現在会話の承認がある。
5. 書き込みcommandが成功する。
6. APIまたはremote参照によるread-only再確認が成功する。
7. global active accountが操作前後で不変である。

commandのexit codeが0であるだけでは運用成功とみなさない。

## E2E保証レベル

| レベル | 内容 | 保証範囲 |
|---|---|---|
| L1 | unit test | account判定、owner照合、状態分類、secret redaction |
| L2 | local E2E | Git設定、remote、worktree、adapter、CLI統合 |
| L3 | GitHub read-only E2E | 認証user、repo、権限、visibility、PR読取 |
| L4 | private mutation canary | branch、push、draft PR、read-back、後片付け |
| L5 | public operation | visibility変更、公開、release |

L4まで成功した場合に限り、隔離fixtureに対するGitHub書き込み経路を「運用確認済み」と表現できる。これは任意のrepositoryに対する権限、branch protection、CI、組織policyまで保証するものではない。対象repositoryごとのpreflightは常に必要である。

L5は自動テスト対象にしない。repositoryごとの公開前レビューと現在会話での明示承認を必須とする。

## private mutation canary

L4は、専用のprivate fixture repositoryに限定し、既定で無効とする。実行前に次を人間へ提示する。

- fixtureの`owner/name`
- 使用account
- 作成するbranch
- 作成するdraft PR
- 実行する正確なcommand
- 外部から見える範囲
- 後片付けの対象と方法
- secret scan結果
- global active accountの事前値

canaryの実行、後片付け、repository削除は別々の外部変更として扱う。推測で削除しない。

## 移行方式

既存スキルを直ちに移動・削除せず、次の段階で移行する。

1. 新リポジトリへ対象ファイルを検証済みコピーとして配置する。
2. コピー元とhash、依存関係、挙動を比較する。
3. 新リポジトリでL1からL3を通す。
4. Codex・Claude adapterを追加する。
5. 既存配置から新SSOTを参照する切替案を作る。
6. 人間レビュー後に参照先を切り替える。
7. 安定期間後、重複コピーの廃止を別途判断する。

移行中はコピー元を変更・削除しない。既存リポジトリの未commit作業や他sessionの変更を巻き込まない。

## 文書と配布物

ユーザー向け、運用向け、レビュー向け文書は日本語を既定とする。

実装時に次を用意する。

- `README.md`
- `LICENSE`
- `SECURITY.md`
- `PUBLIC_READY.md`
- architecture、安全境界、移行、運用runbook
- 人間レビュー用decision document
- testとscanの再現command

## 実装完了条件

次がすべて確認された場合に「ローカル実装完了」とする。

- unit test成功
- local E2E成功
- live read-only E2E成功
- secret scan成功
- personal path scan成功
- Windows terminal flash guardのsmoke成功
- Codex・Claude adapterが同じSSOTを参照
- 既存スキルとの差分と互換性を記録
- READMEの手順を再現
- worktree内の残務を分類

L4未実施の場合は、GitHub書き込み運用を未保証と明記する。

## 人間レビューゲート

ローカル実装、ローカル検証、read-only検証までは安全に進められる。

次の操作はそれぞれ現在会話の承認を必要とする。

- GitHub上でprivate repositoryを作成
- push
- draft PR作成
- private mutation canary
- merge
- repository visibility変更
- release、公開、告知、外部共有

GitHub repository作成前のreview packetには次を含める。

- 作成予定repository: `nexus-ai-2045/github-ops-skills`
- visibility: `private`
- 送信予定file一覧とcommit history
- test、E2E、scan結果
- 既知の制約と未保証範囲
- mutation canaryの正確な操作
- public化時に外部から見える内容
- 推奨判断と理由

## 残務ゼロの定義

残務は次の4区分で個別に判定する。

1. ローカル実装
2. private GitHub運用
3. 人間レビュー
4. 公開運用

一部区分が完了していても、他区分を推測で「残務ゼロ」としない。現在値は、取得時刻と対象範囲を伴う一次証拠がある場合だけ断定する。

## 現時点の事実・未確定事項

### fact

- actor: `user`
- event_time: `2026-07-27`
- observed_at: `2026-07-27T20:35:00+09:00`
- scope: `本設計の会話上の承認`
- source: `現在会話`
- claim: 独立SSOTとローカルoverlay、安全・エラー契約、段階的E2E、非破壊移行、成果物とレビューゲートが採用された。

### non_fact

- actor: `codex`
- event_time: `2026-07-27T20:35:00+09:00`
- scope: `実装方針`
- kind: `proposal`
- basis: `採用済み設計`
- claim: この設計に基づく実装計画を、設計書の人間レビュー後に作成する。

### unknown

- actor: `GitHub`
- event_time: `unknown`
- scope: `nexus-ai-2045/github-ops-skills`
- reason: `GitHub repositoryはまだ作成していない`
- verification_next: `repository作成前review packetの承認後にGitHub APIで確認する`
- claim: GitHub上のrepository状態、権限、visibility、書き込み運用結果。
