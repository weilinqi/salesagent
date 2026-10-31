# First Audio Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move cold knowledge initialization out of the first chat turn and expose end-to-first-audio latency against a 3000ms target.

**Architecture:** Add an offline-testable knowledge warmup helper and invoke it during FastAPI startup after embedding initialization. Track latency from the beginning of `stream_pipeline` through the first successful WebSocket audio send.

**Tech Stack:** Python 3, FastAPI lifespan, asyncio, unittest.

**Spec:** `docs/superpowers/specs/2026-10-25-first-audio-latency-design.md`

## Global Constraints

- Preserve `/api/v1` and WebSocket contracts.
- No live external services in tests.
- Keep knowledge retrieval query-dependent during normal turns.

## Review Focus

- Knowledge warmup exceptions must not block startup.
- A reply with no audio must report no first-audio measurement.
- The timer must include context assembly.
- The PASS boundary is strictly below 3000ms.
- Existing text and audio streaming ordering must remain unchanged.

---

### Task 1: Total first-audio measurement

**Files:**
- Modify: `backend/app/services/conversation/streaming.py`
- Test: `backend/tests/test_streaming_text_updates.py`

**Interfaces:**
- Produces: `stream_pipeline(..., latency_clock=...)` result field `first_audio_ms: Optional[int]` and `[LATENCY]` log output.

- [x] Write an offline test with a deterministic clock proving context time is included.
- [x] Run the targeted test and verify it fails before implementation.
- [x] Add request-level timing and the 3000ms PASS/MISS log.
- [x] Run the targeted test and verify it passes.

### Task 2: Startup knowledge prewarm

**Files:**
- Modify: `backend/app/services/conversation/streaming.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_streaming_text_updates.py`

**Interfaces:**
- Produces: `warmup_knowledge_retrieval(handler) -> bool`, called by application startup.

- [x] Write success and failure tests for the warmup helper.
- [x] Run the targeted tests and verify they fail before implementation.
- [x] Implement the helper and await it during startup with a bounded timeout.
- [x] Run backend syntax and full offline regression checks.
