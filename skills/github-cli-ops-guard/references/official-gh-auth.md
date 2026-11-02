# Official GitHub CLI Auth Facts

Use these as source-backed facts when diagnosing `gh` identity drift.

- GitHub CLI manual: `gh auth status` displays active account and auth state for known hosts. Each host section indicates the active account that will be used for that host.
- GitHub CLI manual: `gh auth switch` switches the active account for a host. With more than two accounts, use `--user` to avoid interactive ambiguity.
- GitHub CLI manual: `gh auth login` stores a token in the system credential store when possible, with fallback storage if no credential store is available.
- GitHub CLI manual: `gh auth token` returns the token for a host/account; without `--user`, it uses the active account. Do not print token values in user-visible output.
- GitHub CLI manual: `gh auth refresh` may require switching to an inactive account first, refreshing, then switching back.
- GitHub changelog for CLI v2.40.0: multiple accounts can be logged in at once; one is marked active and `gh auth switch` changes which account `gh` uses.

Primary sources:

- https://cli.github.com/manual/gh_auth_status
- https://cli.github.com/manual/gh_auth_switch
- https://cli.github.com/manual/gh_auth_login
- https://cli.github.com/manual/gh_auth_token
- https://cli.github.com/manual/gh_auth_refresh
- https://github.blog/changelog/2023-12-17-log-in-to-multiple-github-accounts-with-the-cli/
