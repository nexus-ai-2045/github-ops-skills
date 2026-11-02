# Repo Goal

repo: github-ops-skills
owner: nexus-ai-2045
current_goal: 複数の GitHub アカウントと repository を扱うときに、対象・identity・権限・承認を混ぜず、GitHub への書き込み前に fail-closed で止める小さな Core Suite を Codex / Claude / Grok 共通の skills として提供する。

## 完了レイヤー

- local implementation:
- local verification:
- branch / commit:
- push / PR:
- merge / external state:
- cleanup:
- unrelated dirty state:

## 停止線

- publication: 現在会話での人間レビューと明示承認まで停止
- repository visibility: repo単位の明示承認まで変更しない
- external send / post / comment: 明示承認まで停止
- hook / automation: 配置のみ。install / enableは明示承認まで停止
- auth / secret / production: 明示承認まで変更しない

## Evidence

- git state:
- changed files:
- verification:
- external actions performed: false
- remaining risks:
