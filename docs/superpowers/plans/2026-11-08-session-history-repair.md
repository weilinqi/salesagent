# Session history repair

Root cause: history navigation supplies sessionId but chat ignores it; local page messages are never fetched, sessionStorage contains no role/settings snapshot; WebSocket reconnect starts a new persona/opening without restoring persisted context. The generated persona and opening message were never persisted.

Fix in place on main, preserving authenticated ownership checks and WebSocket message shapes:
- [x] Add offline API and reconnect regressions using temporary SQLite; add frontend history-loading/store/page tests.
- [x] Extend session detail with existing persisted settings, scenario, phase and saved persona; add an owned messages endpoint ordered by created_at/id.
- [x] Persist persona snapshot in the session's existing role_config JSON under a reserved server-only key (no schema migration); persist the opening message.
- [x] Rehydrate WebSocket context on cold reconnect and skip opening/persona regeneration for existing transcripts or in-memory context.
- [x] Load URL-selected history and settings before enabling WebSocket; cancel stale requests, show retryable errors, retain completed sessions as read-only.
- [x] Verify backend regression/compile and frontend tests/build/lint. Review the final diff.

No external history provider is required: existing SQL persistence remains the authority. Historical content never written to SQL cannot be reconstructed; new openings/personas will be saved by this repair. Audio recordings are not added to storage.

Verification: new tests reproduced missing settings, missing messages route, repeated opening and wrong-session socket before the repair. Final backend compile and 134 offline tests passed; frontend TypeScript/Vite/ESLint passed and 44 regressions passed. Used the installed VS Code Node runtime because standalone npm is unavailable. Independent review confirmed persona recovery after interrupted opening; no remaining findings. No live model calls, production database access or browser walkthrough performed.
