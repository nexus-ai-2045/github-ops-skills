# 移植記録

legacy Core Suiteは原本を変更せず`skills/`へcopyしました。移植元と移植先のhashは
`migration/source-manifest.json`へ別々に保存しています。個人home pathを含む原本は
移植時にplaceholderへ正規化し、検証時に両hashを確認します。

## 継続吸収

1. runtime / workspace の差分は `scripts/skill_drift_check.py` で検出する。
2. portable な学習だけを `skills/` と `src/github_ops/` へ吸収する。
3. 個人 path・token・private inventory は正規化または repository 外 overlay に残す。
4. 原本削除や runtime 一括切替は別 PR / 人間判断とする。
