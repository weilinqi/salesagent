# Practice Profile History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save and reuse practice customer profile entries locally per signed-in user.

**Architecture:** Keep the feature in the existing practice setup page. Store validated history records in localStorage under a user-specific key and pass selected records back into the existing customer preparation form.

**Tech Stack:** React, TypeScript, browser localStorage.

**Spec:** `docs/superpowers/specs/2026-11-16-practice-profile-history.md`

## Global Constraints

- Do not add a backend endpoint or dependency.
- History is isolated by user ID and capped at 20 records.
- Storage errors must not prevent starting a practice session.

## Review Focus

- Malformed or unavailable localStorage leaves setup usable.
- Switching accounts loads a separate history list.
- Selecting an entry restores all profile fields and the saved training mode.
- Failed session creation does not add a history record.
- The history list cannot exceed 20 entries.

---

### Task 1: Add local profile history to practice setup

**Files:**
- Modify: `frontend/src/pages/Practice/PracticePage.tsx`
- Modify: `frontend/src/components/business/practice/CustomerPreparation.tsx` only if a prop adjustment is needed.

**Interfaces:**
- History entry: `{ id: string; createdAt: string; trainingMode: 'full' | 'rejection'; profile: PreparationProfile }`.
- Storage key: `sales-agent-practice-profile-history:<user-id>`.

- [ ] Add safe load/save helpers, per-user state, and a 20-record limit.
- [ ] Add the blue history button next to the existing return button and render reusable entries.
- [ ] Restore the selected entry into the form and training mode.
- [ ] Persist only after a successful session setup; ignore storage failures.
