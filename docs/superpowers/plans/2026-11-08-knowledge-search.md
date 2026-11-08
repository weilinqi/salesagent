# Knowledge search implementation plan

**Goal:** Preserve main's preparation and triple fallback features while improving Chinese knowledge retrieval and adding optional MiniMax web supplementation.

**Architecture:** Keep the existing authenticated /api/v1/knowledge/search contract and add optional fields. Combine semantic results with bounded Chroma keyword candidates, expand common sales synonyms, deduplicate and fuse ranks. Reuse the existing MiniMax web search adapter; never send internal document text to web search. Keep local and web evidence separate.

**Scope:** Three modes: local (API default, backwards compatible), auto (UI default; supplement insufficient local evidence), web (explicit public web search). No generated answers, OCR, automatic ingestion or changes to practice messages in this iteration.

**Global constraints:** No live external services in tests. No credentials or user audio in changes. Source/category filters apply before candidate limits. Search outages retain usable results and display a safe notice. Web URLs must be HTTP(S). Query length 1–500 after trimming.

## Tasks
- [x] Add offline tests for Chinese synonym retrieval, rank fusion/deduplication, mode routing, local/network outages, filters and request validation.
- [x] Implement bounded lexical retrieval and synonym expansion, preserving semantic-only callers.
- [x] Extend search schemas and route with optional web evidence/notices, reuse MiniMax search with a timeout.
- [x] Add UI mode selection, source links, notices, empty state and stale-request cancellation.
- [x] Run backend compile/regressions, frontend build/lint and inspect final diff.

## Review focus
- Both retrieval methods failing must remain a visible failure in local mode.
- Auto supplementation must assess relevance, rather than merely non-empty nearest neighbors.
- Local source filters must not silently cause an external request.
- Network snippets remain untrusted plain text, with safe validated links.
- No external call for invalid/empty input; old clients remain local by default.

## Integration ledger
- Local main fast-forwarded to 75cb78e (triple fallback). Remote fetch failed with GitHub connection timeout; remote freshness remains unverified.
- Python works outside the sandbox; run verification with approved escalation. No new dependency planned.
- User approved the preceding proposal and requested direct implementation in this checkout.
- Verification: backend compileall passed; 129 backend and 38 frontend regressions passed. TypeScript, Vite build and ESLint passed using the installed VS Code Node runtime (ELECTRON_RUN_AS_NODE=1), because standalone npm/node are absent from PATH.
- Review: fixed case-sensitive model token retrieval, legacy prefix/chapter deduplication and synonym-only false-positive web gating, with red/green regression tests. Independent reviewer rechecked these fixes without remaining significant findings.
- Residual limitation: routing threshold is heuristic; no live MiniMax request or browser walkthrough performed.
