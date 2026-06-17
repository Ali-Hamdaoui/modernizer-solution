# F15 Repair Assistant Q&A

**Job:** F15-JOB-111
**Area:** Assistant
**Status:** Implemented (via existing `build_failure_explanation`)

## Purpose

Let the chatbot explain failures and repair proposals flexibly using gate-bound evidence.

## How it works

The `GateExplanationBuilder.build_failure_explanation()` method (in `v2_gate_assistant.py`) already implements repair assistant Q&A using `EvidencePackBuilder.build_failure_pack()`.

### Flow

1. User asks "What went wrong?" or "Why did the build fail?"
2. Assistant calls `build_failure_explanation(gate_id)`.
3. This loads the repair_review gate, resolves evidence artifacts, and builds a conversational answer.
4. Answer includes:
   - Failure summary from bound artifacts (not stale preview).
   - Root cause hypothesis from diagnosis.
   - Patch risk assessment.
   - Available actions (approve, reject, revise).

### What the assistant can do

- Explain build/test/transform failures using gate-bound evidence.
- Describe the proposed repair (patch summary, affected paths).
- Summarize reviewer critique (if available).
- Explain remaining attempt limits.
- Handle user repair change requests by routing to `request_repair_revision`.

### What the assistant cannot do

- Apply patches directly (must go through `approve_repair` → `V2RepairFlowService.apply_patch`).
- Approve or reject repairs (requires human actor).
- Write files or mutate legacy source.
- Accept `sandbox_path`, `argv`, or `env` from user input.

### Example conversation

```
User: Why did the build fail?
Assistant: The build failed in Stage 1 with a compilation error in Foo.java.
The root cause is a missing dependency declaration. A repair proposal
has been prepared that adds the missing dependency to pom.xml.
Available actions: Approve, Reject, or Request Revision.
What would you like to do?

User: That looks wrong, can you try a different approach?
Assistant: I'll create a revised repair proposal with your feedback.
[Routes to request_repair_revision with user feedback]
```
