---
name: debugging
description: Use when a SalesAgent error, failed test, stack trace, API failure, or Agent/WebSocket regression needs investigation before code changes.
---

# SalesAgent Debugging

Establish evidence before proposing a change. Do not make a guess-driven fix.

## Investigation order

1. Capture the exact symptom: command or request, observed result, expected result, stack trace, and affected route, service, or socket event.
2. Reproduce with the smallest safe case and determine whether the failure is deterministic.
3. Trace inputs, state, logs, and the relevant call path to identify a root cause supported by evidence.
4. Propose the smallest change that removes that cause; distinguish it from mitigations or unrelated cleanup.
5. After a change, run verification commands matched to the changed scope, then report the command and outcome.

## Safety boundaries

Use synthetic credentials, fixtures, local temporary files, and in-memory or test databases. Do not validate with a real MiniMax key, real user audio, a production database, or external network calls.

## SalesAgent checks

For APIs, inspect request validation, authentication, authorization, database state, and response/error mapping. For Agent and WebSocket failures, inspect connection lifecycle, event ordering, background tasks, cancellation, and cleanup. Treat a failing test as evidence to explain, not merely a condition to silence.

## Stop conditions

If reproduction is unavailable, report the missing evidence and the least invasive next observation. Do not claim a root cause or a fix without evidence.
