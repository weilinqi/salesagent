# Original PDF and Detailed Materials Plan

**Goal:** Show the most relevant uploaded source PDF at the start of a practice session and show detailed knowledge excerpts for live and user-directed searches.

**Architecture:** Reuse the authenticated hybrid knowledge search for relevance. Add an authenticated, path-validated original-PDF response by document ID. The materials panel resolves the most relevant result to its source document and previews that original PDF; later searches retain full excerpts, source metadata, and web results.

**Files:**
- `backend/app/api/v1/knowledge.py`: add authenticated source-PDF streaming endpoint using stored document metadata and existing path containment checks.
- `frontend/src/api/knowledge.ts`: add source document/PDF API support.
- `frontend/src/stores/practiceStore.ts`: retain the preparation context in a newly created session.
- `frontend/src/components/business/practice/PracticeMaterialsPanel.tsx`: initial source lookup/PDF preview and detailed result/history display.

**Review focus:** no matching source; duplicate document names; missing or unsafe file path; session without preparation fields; no local match with web-only results. Preserve existing authentication and session history behavior.

**Verification:** source review and `git diff --check`; no tests or build run unless requested.
