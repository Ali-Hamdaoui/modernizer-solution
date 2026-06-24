# Feature 18 Tasks — E2E Fixtures

## Task F18-T01 — Prove Jackson Stage 4 recovery

### Goal

Validate the generic engine with the first deterministic Jackson/OpenRewrite scenario.

### Scope

- Seed accepted Stage 3 checkpoint and failing Stage 4 attempt.
- Assert evidence, `JACKSON_JSONNODE_UNRESOLVED`, retrieval policy, and OpenRewrite mode.
- Require fake Azure AI Foundry adapter responses for the proposer to recommend and explain the exact registered recipe ID, version, and parameters, and for the reviewer to critique that exact revision.
- Assert human approval, sandbox apply, compile plus focused-test proof, and checkpoint promotion through the same generic recovery engine used by the non-Jackson fixture.
- Assert safe cockpit projection.

### Likely future modified files

- `tests/control_tower/_helpers.py` — shared fixture helpers if appropriate; needs verification.
- `web/control-tower/tests/recoveryCockpit.test.tsx` — projection coverage.

### Likely future new files

- `tests/control_tower/test_demo3_e2e_jackson_fixture.py` — backend flow.
- `tests/fixtures/demo3/jackson-stage4/` — deterministic input/expected artifacts.

### Implementation notes

- Jackson validates the engine; no Jackson-only orchestration path.
- Use fake Azure AI Foundry adapter responses and fake retrieval.

### Acceptance criteria

- Failed attempt remains visible and validated repair creates accepted Stage 4 checkpoint.

### Focused tests

- Single fixture flow plus failure variants; no live calls.

### Out of scope

- Broad Jackson migration coverage.

### Dependencies

- Features 01–17.

## Task F18-T02 — Prove non-Jackson LLM-authored patch recovery

### Goal

Show that a reviewed generative fix works without backend fixture-specific repair logic.

### Scope

- Seed a non-Jackson, non-recipe failure such as a Hibernate/Jakarta import.
- Fake Azure AI Foundry proposer response authors exact bounded diff; fake reviewer response critiques exact revision.
- Assert policy, human approval, exact-byte sandbox apply, actual diff, validation, and promotion.

### Likely future modified files

- `tests/control_tower/_helpers.py` — reusable fake Azure AI Foundry adapter and retrieval helpers if appropriate; needs verification.
- `web/control-tower/tests/recoveryCockpit.test.tsx` — generative candidate rendering.

### Likely future new files

- `tests/control_tower/test_demo3_e2e_llm_authored_patch_fixture.py` — generative flow.
- `tests/fixtures/demo3/hibernate-jakarta/` — non-recipe fixture.

### Implementation notes

- Assert no deterministic backend rule encodes the exact fixture fix.
- Assert approved `repair_candidate.diff` checksum equals bytes passed to executor.
- No live model, retrieval service, web, direct OpenAI call, or Copilot runtime.

### Acceptance criteria

- Generic flow applies and validates the patch without a new core branch or fixed repair implementation.

### Focused tests

- Success, reviewer reject, stale checksum, forbidden path, validation rollback.

### Out of scope

- General autonomous code repair.

### Dependencies

- F18-T01 and Features 06–16.

## Task F18-T03 — Verify deterministic test isolation

### Goal

Keep DEMO3 acceptance reproducible and offline.

### Scope

- Centralize fake Azure AI Foundry adapter and retrieval behavior.
- Block accidental network/live provider usage.
- Keep fixture operations bounded to temporary sandboxes.

### Likely future modified files

- `tests/control_tower/conftest.py` — only if current test conventions support it; needs verification.
- `web/control-tower/vitest.config.ts` — only if network blocking needs configuration; needs verification.

### Likely future new files

- `tests/fixtures/demo3/fakes.py` — suggested fake Azure AI Foundry adapter and retrieval behavior; needs verification against test layout.
- `tests/control_tower/test_demo3_no_live_dependencies.py` — optional guard test.

### Implementation notes

- Prefer existing fake-model helpers behind the Azure AI Foundry adapter contract.
- Do not run the full suite for feature implementation.

### Acceptance criteria

- Both E2E fixtures pass without credentials, network, external model services, or GitHub Copilot.

### Focused tests

- Missing credentials, network stub assertion, temporary-path containment.

### Out of scope

- CI redesign.

### Dependencies

- F18-T01 and F18-T02.
