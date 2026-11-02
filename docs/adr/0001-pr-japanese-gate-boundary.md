# ADR-0001: PR日本語gateは限定的な構文契約とする

- 状態: 採用
- 日付: 2026-08-16

## 背景

PR title/bodyの日本語既定を自動検査する過程で、正規表現によるMarkdown除去が、fence、HTML comment、link destinationなどの完全なMarkdown解析へ拡大した。metadata-only workflowはcheckoutや外部依存を使わないため、完全なMarkdown rendererを再実装すると保守不能な境界になる。

## 決定

- PR titleは平文日本語とし、Markdown link構文を許可しない。
- PR bodyには日本語を含むATX見出しを最低1つ必須とする。
- ATX／Setext見出しが英語だけの場合は停止する。
- 見出し内のMarkdown link構文を許可しない。
- fenced blockは0〜3スペースindentと3文字以上のbacktick／tildeだけを認識する。
- title/bodyはUTF-8ファイルでCLIへ渡し、shell展開を避ける。
- body全体を完全なMarkdownとして解析・renderする責務は持たない。

## 理由

ユーザー向け見出しを日本語にする目的を直接検査しつつ、独自Markdown parser化を防ぐ。metadata-only、read-only、secret不使用というworkflow境界も維持できる。

## 結果

- 複雑なMarkdownをtitleや見出しに使うPRは、平文へ直して再検査する。
- body本文すべての言語品質は人間レビューで確認する。
- 完全なrender結果の検査が必要になった場合は、parser依存、supply-chain、workflow権限を別ADRで再評価する。
