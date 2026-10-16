---
name: code-review
description: Use when reviewing a SalesAgent Python pull request, diff, or proposed backend change.
---

# SalesAgent Code Review

Review the proposed change and report actionable findings only. Do not edit code, tests, configuration, or dependencies unless the user separately asks.

## Focus

- Trace changed FastAPI routes through validation, authentication, authorization, response handling, and error paths.
- Check SQLAlchemy queries, session lifetime, transaction boundaries, ownership checks, and data exposure.
- Check Agent and WebSocket changes for connection lifecycle, authentication, message ordering, cancellation, cleanup, and accidental external-service calls.
- Compare changed behavior with nearby tests. Call out missing regression, permission, error-path, and WebSocket coverage.

## Finding format

Report each issue as: **severity — file:line — evidence — impact**. Explain the condition that makes it fail and the smallest safe direction for a fix. Separate confirmed defects from residual test gaps. If no actionable defect is found, say so and identify any remaining unverified risk.

## Avoid

- Style-only comments without a concrete correctness, security, reliability, or maintainability impact.
- Speculative findings without evidence in the diff or its reachable code.
- Assuming tests pass because a happy path exists.
