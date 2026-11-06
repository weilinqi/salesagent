# Guided customer preparation implementation plan

Goal: Deliver the user-approved prompt-first introduction, concise follow-up questions, editable fields after each round, and direct practice once product, target and goal are known.
Architecture: Extend authenticated practice routes with stateless collection and background lookup. Store confirmed preparation in existing customer_context and prefer it when constructing the WebSocket persona. Preserve existing session and WebSocket contracts.
Tech stack: React/TypeScript, FastAPI, existing MiniMax and search adapters.
Spec: Requirements confirmed in this chat on 2026-11-05.

- [x] Add offline tests for preserving edits, required values, failed AI calls and personal customers without invented companies.
- [x] Implement preparation service and authenticated collection/background routes.
- [x] Implement prompt-first UI, editable seven-field list, short questions, optional organization/preferences, cancellation and direct-start readiness.
- [x] Connect confirmed profile to session persistence and customer persona before random generation.
- [x] Run focused tests, backend suite, frontend build/lint and inspect final diff.

Review focus: Concurrent manual edits must survive AI responses; starting cancels collection; clearing required fields hides start; missing search sources must not invent facts; personal customers must not be converted to corporate buyers.
Ruling: Retain scenario selection; role style is optional. Unknown organization details remain unknown. Search returns source-linked snippets and explicitly reports unavailable data.

Validation: backend 133 tests passed; frontend 45 tests passed; production build and lint passed; backend compileall passed. Real model/browser interaction was not exercised. Background lookup requires the existing MINIMAX_MCP_URL search adapter; unavailable lookup is shown explicitly.
