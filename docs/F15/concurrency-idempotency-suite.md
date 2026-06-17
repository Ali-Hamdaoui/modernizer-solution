# F15 Concurrency / Idempotency Suite

**Job:** F15-JOB-120
**Area:** Testing
**Status:** Design complete

## Purpose

Prove repeated user/chatbot actions are safe.

## Test cases

### 1. Double-click continue
- Submit two identical `continue` actions for the same gate.
- First returns `executed`, second returns `idempotent` (same decision_id).

### 2. Concurrent plan revision/accept
- Submit revise and approve concurrently on same gate.
- One succeeds, the other returns `gate_not_open` or `idempotent`.

### 3. Retry after timeout
- Submit action after network timeout, with same idempotency key.
- Returns `idempotent` with same result.

### 4. Stale action rejection
- Submit action using stale gate checksum.
- Returns `stale_checksum` error.

### 5. Idempotent repair revision
- Submit revision request twice with same idempotency key.
- Second returns `idempotent` with same result.

## Suggested test file

`test_v2_gate_concurrency.py` — focused concurrency/idempotency tests.
