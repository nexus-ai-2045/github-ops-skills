# 移植記録

legacy Core Suiteは原本を変更せず`skills/`へcopyしました。移植元と移植先のhashは
`migration/source-manifest.json`へ別々に保存しています。個人home pathを含む原本は
移植時にplaceholderへ正規化し、検証時に両hashを確認します。
