# First Playback Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start browser MP3 playback earlier and expose its client-side startup delay.

**Architecture:** Extract the initial MP3 decode decision into a pure exported
helper tested with Node's built-in test runner. Use that helper in the existing
React audio hook, lower the first-play scheduling margin, and retain the current
retry-on-decode-failure behavior.

**Tech Stack:** React 18, TypeScript, Web Audio API, Node test runner.

**Spec:** `docs/superpowers/specs/2026-10-25-first-playback-latency-design.md`

## Global Constraints

- Preserve WebSocket message shapes and existing audio replay behavior.
- Add no package dependency.
- Do not commit user recordings, database journals, or secrets.

## Review Focus

- A sub-threshold first chunk must remain buffered.
- Exactly 4096 bytes must trigger a decode attempt.
- Decode failure must retain all accumulated bytes for the next retry.
- Later audio buffers must keep their existing queue behavior.
- Playback timing state must reset when playback is stopped.

---

### Task 1: Earlier first MP3 decode

**Files:**
- Modify: `frontend/src/hooks/useAudioStream.ts`
- Create: `frontend/tests/audioStartupPolicy.test.mjs`

**Interfaces:**
- Produces: `shouldAttemptMp3Decode(totalBytes, hasPendingBuffers): boolean`

- [x] Write a Node test for the 4095/4096-byte boundary and pending-buffer case.
- [x] Run the test and confirm it fails because the helper is absent.
- [x] Add the helper and use it in `playChunk`.
- [x] Add first-chunk-to-playback scheduling telemetry and a 20ms initial margin.
- [x] Run the Node test, frontend build, and frontend lint.

### Task 2: Verify and publish today's source changes

**Files:**
- Commit all current source, test, and documentation changes.
- Exclude: `backend/app/data/asr_debug/last_user_audio_processed.wav`
- Exclude: `backend/salesagent.db-journal`

- [ ] Run backend compile and offline regression suite.
- [ ] Review the complete source diff for correctness and secrets.
- [ ] Commit the selected files on the current branch.
- [ ] Push the current branch to `origin` (`weilinqi/salesagent`).
