# セキュリティ

secret、個人パス、誤account操作を見つけた場合は公開issueへ詳細を書かないでください。

この repository は public です。脆弱性や漏えいの疑いがある場合の第一経路は
GitHub の [Private vulnerability reporting](https://github.com/nexus-ai-2045/github-ops-skills/security/advisories/new)
です。ページが 404 なら未有効なので、公開 issue へ詳細を書かず owner `nexus-ai-2045` へ
GitHub 上で非公開連絡してください。メールアドレスはこの file に置きません。

このrepositoryはtokenを受け取る場合も対象processの環境変数だけを使い、ログへ
出さない設計です。漏えいの疑いがあるtokenは直ちに提供元で失効してください。
