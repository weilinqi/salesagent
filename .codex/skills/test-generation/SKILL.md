---
name: test-generation
description: Use when adding or improving SalesAgent tests for FastAPI APIs, Agent/WebSocket flows, or error paths.
---

# SalesAgent Test Generation

Extend the project’s existing test style before introducing a new framework. This repository defaults to `unittest`; use `unittest.TestCase`, standard assertions, and its current test discovery conventions.

## Framework and fixtures

Use `tempfile.TemporaryDirectory()` with `pathlib.Path` for temporary filesystem state. Use pytest fixtures only when pytest is already installed in the project or the user explicitly requests pytest.

## Coverage priorities

- Exercise observable API behavior: valid input, validation failures, authentication and authorization, ownership boundaries, persistence effects, and mapped errors.
- For Agent and WebSocket flows, cover handshake or authentication failures, event ordering, disconnects, cleanup, and error propagation.
- Add the narrowest regression test that fails before the intended production change and passes after it.
- Keep tests offline and deterministic: synthetic credentials, fixture data, temporary directories, and in-memory or test databases only. Do not call external AI services, use real audio, or access production systems.

## Test quality

Assert externally meaningful outcomes rather than implementation details. Isolate time, randomness, and background work when they affect determinism. Reuse existing helpers where they express the setup clearly; otherwise keep fixtures local to the test module. Run the relevant existing test command after adding or changing tests.

## Avoid

- Adding a test framework or dependency solely for one test without explicit approval.
- Mocking the behavior the test is meant to verify.
- Happy-path-only tests when a change adds an error or permission branch.
