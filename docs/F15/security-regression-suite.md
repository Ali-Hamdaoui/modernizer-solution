# F15 Security Regression Suite

**Job:** F15-JOB-119
**Area:** Testing
**Status:** Design complete

## Purpose

Prove F15 cannot accept dangerous inputs.

## Test cases

### 1. sandbox_path rejection
- Submit gate action request with `sandbox_path` field.
- Verify schema validation rejects the request.

### 2. argv/env rejection
- Submit gate action request with `argv` or `env` fields.
- Verify schema validation rejects the request.

### 3. Prompt injection via artifact
- Store artifact with "ignore previous instructions" content.
- Load evidence pack and verify sanitizer flags the injection.
- Verify assistant does not execute instructions from artifact content.

### 4. Direct command blocked
- Attempt to execute a repair via assistant (not through gate action service).
- Verify the assistant returns a warning, not a command execution.

### 5. Non-human approve/reject blocked
- Submit approve action with `actor_type: "assistant"`.
- Verify `actor_not_authoritative` error returned.

### 6. Stale checksum rejection
- Submit action with stale `expected_gate_checksum`.
- Verify `stale_checksum` error returned.

## Suggested test file

`test_v2_gate_security.py` — focused security regression tests.
