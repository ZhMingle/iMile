# Project workflow

- After completing a user task, run the relevant verification, review the Git diff for generated files, credentials, and real operational data, then commit the intended changes and push the current branch to `origin`.
- Do not commit or push when the work is incomplete, verification fails, the repository has unresolved conflicts, sensitive data would be included, or the user explicitly asks not to push. Report the blocker instead.
- Preserve unrelated user changes. Never add ignored operational inputs, generated reports, attendance/sign-in records, local credentials, tokens, or message logs.
