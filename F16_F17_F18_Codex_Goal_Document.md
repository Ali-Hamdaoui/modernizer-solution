# AI Migration Control Tower — F16/F17/F18 Goal Document

**Branch:** `chatbot-optimization`  
**Audience:** Codex/subagents working on the real codebase.  
**Important:** This file is the goal document. The source of truth is the real codebase, not `/docs`.

---

## 0. Hard Rules

1. Do **not** push.
2. Do **not** discard dirty files.
3. Do **not** read, run, or change anything under `/docs` unless explicitly asked.
4. Work from the real codebase only.
5. Confirm the branch is `chatbot-optimization`.
6. Confirm these commits exist before coding:
   - `c5bd4c0 feat(f15): default ui v2 jobs to auto_on_green`
   - `61b6781 fix(f15): repair assistant ask imports`
7. Keep the current demo behavior working:
   - UI-created jobs default to `auto_on_green`.
   - Stage 1 → Stage 2 → Stage 3 auto progression works.
   - Stage 3 POM/dependency review works.
   - `/assistant/ask` does not crash on normal messages.
   - Direct valid POM changes apply in the Stage 3 sandbox with validation and rollback.
   - Unsafe non-direct targets, for example Tomcat when not directly present, remain blocked.

---

## 1. Non-Negotiable Architecture Invariant

```text
LLM explains/proposes.
Reviewer critiques.
Human approves.
Backend validates and executes.
Artifacts prove.
```

Do **not** violate this model.

Forbidden:
- No frontend/chatbot-supplied `sandbox_path`.
- No frontend/chatbot-supplied raw command.
- No frontend/chatbot-supplied env.
- No direct LLM write authority.
- No mutation outside governed sandbox.
- No approval without exact checksum where approval is required.
- No duplicate orchestrator, stage progression, gate, reviewer, repair, artifact, validation, rollback, repository, or unit-of-work systems.

---

## 2. Current Baseline

Known working demo behavior:
- Full 3-stage migration completed.
- Final status reached `TRANSFORM_APPLIED_IN_SANDBOX`.
- Assistant can answer status questions.
- Assistant can summarize the current POM.
- Direct POM property changes work:
  - `Update org.modelmapper.version to 3.2.0`
  - `Update io.jsonwebtoken.version to 0.12.6`
- Direct POM dependency update works:
  - `Update com.google.code.gson:gson to 2.11.0`
- Safe block works:
  - `Change Tomcat to 10.1.20` is blocked when Tomcat is not a direct target.

Do not regress any of the above.

---

## 3. Parallel Subagent Plan

Subagent A can implement F16 now.  
Subagent B can implement F17 now.  
Subagent C should first analyze F18 and implement **Slice 1 only** until F17 contracts stabilize.

Recommended merge order:

```text
F16
→ F17 slices 1–3
→ F18 slice 1
→ F17 proposer integration if needed
→ F18 full repair proposal/patch loop
```

Expected conflict points:
- F16 and F17 may both touch `app.py` and `MigrationCockpit.tsx`.
- F17 and F18 may both touch model invocation, reviewer, and repair flow.
- Keep commits small and feature-scoped.
- Use stable-fragment tests, not exact full response snapshots.

---

# F16 — Professional Chatbot Response Composer

## Goal

Create centralized assistant answer formatting that makes chatbot replies clearer, more professional, and easier to demo.

This is formatting only. Do **not** change:
- intent classification semantics
- POM apply logic
- POM validation logic
- rollback logic
- stage progression
- gates
- model routing
- repair flow

## Problem

Assistant answer text is spread through `migration_factory/control_tower/adapters/fastapi/app.py`, especially functions like:

- `_classify_v2_assistant_intent`
- `_build_v2_assistant_answer`
- `_build_status_answer`
- `_build_pom_explanation_answer`
- `_build_apply_dependency_change_answer`
- `_build_stage3_dependency_review_answer`
- `_build_pom_change_proposal_answer`
- `_build_model_status_answer`

Current issues:
- Some answers are too long.
- Some answers mix evidence, status, and next step in one wall of text.
- Applied POM answers are close but not standardized.
- Blocked-change answers need clearer safety framing.
- Status answers should start with current state, not artifact inventory.

## Required Implementation

Add:

```text
migration_factory/control_tower/application/v2_assistant_response_composer.py
```

Suggested shape:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class AssistantResponseSection:
    title: str
    lines: tuple[str, ...] = ()

@dataclass(frozen=True)
class AssistantResponseCard:
    headline: str
    status: str  # done, blocked, warning, info, failed, pending
    summary: str
    sections: tuple[AssistantResponseSection, ...] = ()
    next_step: str = ""
    evidence_refs: tuple[str, ...] = ()
    safety_note: str = ""

class V2AssistantResponseComposer:
    def render(self, card: AssistantResponseCard) -> str:
        ...
```

Renderer rules:
- Return a plain markdown string.
- Keep the existing API contract.
- Avoid raw absolute file paths.
- Avoid secrets/env values.
- Keep answers concise.
- Prefer stable headings:
  - `Change`
  - `Validation`
  - `Reason`
  - `Safe next step`
  - `Status`
  - `Artifacts`
  - `Next`

## Required Formats

Applied POM change:

```text
✅ POM change applied

The change was written to the Stage 3 sandbox.

Change
- Operation: update_property_version
- Target: org.modelmapper.version
- Before: 2.3.2
- After: 3.2.0

Validation
- Status: running
- Validation ID: <id>
- Rollback: available

Next
Open Stage 3 Dependency Review to inspect validation results.
```

Blocked POM change:

```text
🛡️ Change blocked safely

The backend refused to apply this change.

Reason
- Tomcat is not directly declared in the current POM.
- It is likely managed through Spring Boot starter web.

Safe next step
Ask for a proposal instead of a direct apply:
"Explain how Tomcat is managed and propose whether a Tomcat override is needed."
```

Migration status:

```text
Migration completed

Status
- Stage 1: completed
- Stage 2: completed
- Stage 3: completed
- Build/tests: PASS_WITH_WARNINGS
- Failures: none

Artifacts
- final_report
- post_transform_test_report
- sandbox

Next
Review the final proof report and warning details before signoff.
```

## Integration Scope

Start with:
- `_build_apply_dependency_change_answer`
- blocked POM target answer path
- `_build_status_answer`
- rollback/validation result answer if easy

Do not rewrite all assistant builders in one pass.

## Tests

Add:
- `tests/control_tower/test_v2_assistant_response_composer.py`

Update if needed:
- `tests/control_tower/test_v2_gate_assistant_ask.py`
- `web/control-tower/tests/migrationCockpit.test.tsx`

Test cases:
- Composer renders applied change with target/before/after/validation/rollback.
- Composer renders blocked change with reason and safe next step.
- Status answer starts with migration status and stage state.
- Composer redacts obvious absolute paths and secrets.
- Output remains a string.
- Existing assistant ask tests pass.
- Frontend renders multiline assistant responses.
- Assistant-only errors stay assistant-only.

Focused tests:

```powershell
py -3 -m pytest tests/control_tower/test_v2_assistant_response_composer.py -q -rs --tb=short
py -3 -m pytest tests/control_tower/test_v2_gate_assistant_ask.py -q -rs --tb=short -k "pom or status or blocked or apply or assistant"
cd web/control-tower
npm test -- MigrationCockpit
npm run typecheck
```

## Acceptance

- Same API contract.
- Clearer answer text only.
- No behavior change.
- Existing demo still works.
- `git diff --check` clean.

Commit:

```text
feat(f16): standardize assistant response formatting
```

---

# F17 — Model Role Routing With Safe Fallback

## Goal

Implement explicit model role routing:

- assistant model answers user-facing questions
- proposer model drafts proposals
- reviewer model critiques proposals
- fallback model is reserve-only if primary role is unavailable
- deterministic fallback remains final safe reserve

No model approves or executes.

## Files to Inspect

Code only. Do not inspect `/docs`.

Backend:
- `migration_factory/control_tower/application/v2_settings.py`
- `migration_factory/control_tower/application/v2_assistant_model_client.py`
- `migration_factory/control_tower/application/v2_reviewer_service.py`
- `migration_factory/control_tower/adapters/fastapi/app.py`
- existing model/reviewer/assistant tests

Frontend if needed:
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
- `web/control-tower/lib/contracts.ts`
- `web/control-tower/tests/migrationCockpit.test.tsx`

Existing env refs:
- `AZURE_OPENAI_ASSISTANT_DEPLOYMENT`
- `AZURE_OPENAI_PROPOSER_DEPLOYMENT`
- `AZURE_OPENAI_REVIEWER_DEPLOYMENT`
- `AZURE_OPENAI_FALLBACK_DEPLOYMENT`

## Required Implementation

Add:

```text
migration_factory/control_tower/application/v2_model_role_router.py
```

Suggested shape:

```python
from dataclasses import dataclass
from enum import Enum

class V2ModelRole(str, Enum):
    ASSISTANT = "assistant"
    PROPOSER = "proposer"
    REVIEWER = "reviewer"
    FALLBACK = "fallback"

@dataclass(frozen=True)
class V2RoleModelRequest:
    role: V2ModelRole
    prompt: str
    fallback: str
    output_schema_name: str | None = None
    require_schema: bool = False
    conversation_history: tuple[dict[str, str], ...] = ()

@dataclass(frozen=True)
class V2RoleModelResult:
    content: str
    role: str
    provider: str
    source: str
    model_status: str
    success: bool
    failure_reason: str
    primary_failure_reason: str = ""
    fallback_used: bool = False
    schema_validated: bool = False
```

Router behavior:
1. Resolve deployment env by role.
2. Try primary role model.
3. If primary fails and fallback enabled, try fallback deployment.
4. If fallback fails, return deterministic fallback.
5. If `require_schema=True` and schema validation fails, fail closed.
6. Reviewer fallback/deterministic path returns `decision=revise`, never `accept`.

## Required Model Client Change

Add `answer_with_role(...)` to `v2_assistant_model_client.py`.

Keep existing `answer()` backward-compatible and implemented through assistant role.

## Safe Fallback Rules

Assistant:
- fallback may answer with metadata.

Proposer:
- fallback may draft only if enabled.
- still needs schema validation, reviewer critique, and human approval later.

Reviewer:
- fallback/deterministic must never auto-accept.
- safe fallback decision is `revise`.

Safe reviewer fallback:

```json
{
  "decision": "revise",
  "reasoning": "Reviewer model unavailable; fail-closed review requires revision or manual evidence review.",
  "missing_evidence": ["Reviewer model output unavailable"],
  "unsafe_assumptions": ["No independent model critique was completed"]
}
```

## Slices

1. Add role router and tests only.
2. Make `/assistant/ask` use role `assistant`.
3. Make reviewer critique path use role `reviewer`.
4. Proposer integration only if existing path is ready.
5. Expose optional model metadata.

Optional API metadata only:
- `fallback_used`
- `primary_failure_reason`
- `reviewer_decision`

## Tests

Add:
- `tests/control_tower/test_v2_model_role_router.py`

Update:
- `tests/control_tower/test_v2_gate_assistant_ask.py`
- `tests/control_tower/test_v2_reviewer_service.py`
- frontend tests only if touched

Focused tests:

```powershell
py -3 -m pytest tests/control_tower/test_v2_model_role_router.py -q -rs --tb=short
py -3 -m pytest tests/control_tower/test_v2_gate_assistant_ask.py -q -rs --tb=short -k "model or fallback or assistant"
py -3 -m pytest tests/control_tower/test_v2_reviewer_service.py -q -rs --tb=short
cd web/control-tower
npm test -- MigrationCockpit
npm run typecheck
```

## Acceptance

- Role router tested.
- Existing assistant ask still returns 200.
- Reviewer fallback cannot accept.
- No model execution authority.
- No API-breaking response change.
- `git diff --check` clean.

Commit:

```text
feat(f17): route assistant models by role with safe fallback
```

---

# F18 — Governed Build-Failure Repair Loop

## Goal

Build/test/transform failure should trigger:

```text
diagnosis → proposer repair → reviewer critique → human checksum approval → backend sandbox patch → validation → rollback
```

Do not create a new repair engine.

Reuse:
- `v2_failure_diagnosis.py`
- `v2_repair_gate_service.py`
- `v2_repair_flow.py`
- `v2_reviewer_service.py`
- runner
- repositories

## V1 Scope

Allowed:
- Maven compile failures
- test compile failures
- javax → jakarta import issues
- missing dependency after migration
- plugin/dependency version conflict
- POM repair in sandbox

Out of scope:
- business logic fixes
- runtime behavior fixes
- security redesign
- large refactors
- multi-module redesign
- direct production/source mutation

## Slice 1 — Repair Policy And Gate Trigger

Implement this slice first if F18 runs in parallel.

Problem:
Repair gate should not depend on `stage_continuation_policy`.

Expected:
- `auto_on_green` still progresses on success.
- build/test/transform failure opens `repair_review` when repair is enabled.
- repair disabled means no repair gate.
- duplicate failure creates one gate only.

Add policy/default fields if appropriate:
- `enable_build_repair: true`
- `enable_llm_repair_proposal: true`
- `max_repair_attempts: 3`
- `repair_scope: build_only`

Do not implement full patch apply in Slice 1.

## Later Slices

2. Repair proposal generator.
3. Patch draft artifact/checksum.
4. Reviewer critique required.
5. Human approval applies sandbox patch and validation reruns.

## Tests

```powershell
py -3 -m pytest tests/control_tower/test_v2_failure_diagnosis.py -q -rs --tb=short
py -3 -m pytest tests/control_tower/test_v2_repair_flow.py -q -rs --tb=short
py -3 -m pytest tests/control_tower/test_v2_repair_gate_service.py -q -rs --tb=short
py -3 -m pytest tests/control_tower/test_v2_fastapi_repair_gate_runtime_wiring.py -q -rs --tb=short
```

## Acceptance

- Governed repair path works under `auto_on_green`.
- No source mutation.
- No raw command/path from frontend/chatbot.
- No duplicate repair engine.
- `git diff --check` clean.

Commit Slice 1:

```text
feat(f18): enable repair review independently from stage continuation
```

---

## Final Instructions For All Subagents

Before coding:
1. `git branch --show-current`
2. `git log --oneline -n 10`
3. `git status --short`
4. Confirm no `/docs` work.
5. Inspect existing code/tests first.

Before reporting:
1. Run focused tests only.
2. Run frontend tests only if frontend touched.
3. Run `git diff --check`.
4. Report changed files, tests, unrelated dirty files, commit hash.
