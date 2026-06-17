# F15 Assistant UX Copy and Examples

**Job:** F15-JOB-075
**Area:** Assistant UX
**Status:** Complete

## Overview

The F15 assistant (chatbot) is designed to be flexible in natural language
while never bypassing backend validation. This document provides examples
of user inputs, how they map to gate actions, and how the assistant should
respond.

## Design Principles

1. **Flexible language, strict backend.** The chatbot may understand many
   phrases and ask follow-up questions, but backend actions are typed,
   persisted, checksum-bound, idempotent, sandbox-only, and stage-ordered.

2. **Always clarify ambiguity.** When the user's intent is unclear, the
   assistant asks for clarification rather than guessing.

3. **No state change without explicit typed action.** The assistant drafts
   actions; the backend validates and executes them through
   V2GateActionService.

4. **Evidence is gate-bound.** All explanations come from gate-bound
   artifact refs/checksums, never stale previews.

---

## Continue to Next Phase

User wants to proceed to the next phase (e.g., analysis -> planning,
planning -> approval, repair -> next stage).

### Example Inputs

| User says | Classified Intent | Action |
|-----------|------------------|--------|
| "continue" | continue_from_gate | Continue to next phase |
| "looks good, continue" | continue_from_gate | Continue to next phase |
| "proceed to planning" | continue_from_gate | Continue to next phase |
| "ok go planning" | continue_from_gate | Continue to next phase |
| "let's move to the next stage" | continue_from_gate | Continue to next phase |
| "accept this analysis" | continue_from_gate | Continue to next phase |
| "go ahead" | continue_from_gate | Continue to next phase (high confidence) |
| "looks okay" | *ambiguous* | Ask: continue or reanalyze? |

### Assistant Responses

**High confidence (continue):**
> I understand you'd like to continue to the next phase. Here's a summary
> of what will happen:
> - Gate checksum: `abc123...`
> - The current analysis will be accepted
> - Stage 2 (planning) will be queued
>
> Shall I proceed with the continue action?

**Ambiguous ("looks okay"):**
> I see you're reviewing the analysis. Would you like to:
> - **Continue** to the next phase (planning)
> - **Reanalyze** with additional configuration
>
> Or would you like more details about the findings?

---

## Request Reanalysis

User wants to re-run analysis with additional input.

### Example Inputs

| User says | Classified Intent | Action |
|-----------|------------------|--------|
| "reanalyze" | request_reanalysis | Request reanalysis |
| "run analysis again" | request_reanalysis | Request reanalysis |
| "scan the XML configs too" | request_reanalysis | Request reanalysis with feedback |
| "need more analysis on database" | request_reanalysis | Request reanalysis with feedback |
| "check the pom.xml files" | request_reanalysis | Request reanalysis with feedback |

### Assistant Responses

> I understand you'd like to re-run the analysis with additional input.
> I'll draft a reanalysis request with your feedback:
>
> **Feedback:** Scan the XML configuration files in src/main/resources
>
> The current gate will be superseded and a new analysis run will be
> queued. Shall I proceed?

---

## Request Plan Revision

User wants to modify the migration plan.

### Example Inputs

| User says | Classified Intent | Action |
|-----------|------------------|--------|
| "revise the plan" | request_plan_revision | Request plan revision |
| "change the plan" | request_plan_revision | Request plan revision |
| "update the migration plan" | request_plan_revision | Request plan revision |
| "I think we need a different approach" | request_plan_revision | Request plan revision |
| "modify the unit order" | request_plan_revision | Request plan revision with instructions |

### Assistant Responses

> I understand you'd like to revise the migration plan. Please provide
> specific instructions for what should change, or I can help you draft
> revision instructions based on your feedback.

---

## Approve Transformation

User approves the transformation to proceed.

### Example Inputs

| User says | Classified Intent | Action |
|-----------|------------------|--------|
| "approve" | approve_from_gate | Approve transformation |
| "approved" | approve_from_gate | Approve transformation |
| "ready for transformation" | approve_from_gate | Approve transformation |
| "good to go, approve" | approve_from_gate | Approve transformation |
| "looks safe, proceed with transform" | approve_from_gate | Approve transformation |

### Assistant Responses

> I understand you'd like to approve the transformation. Before I proceed,
> please confirm:
>
> **Approval Summary:**
> - Gate phase: approval_review
> - Stage: 3
> - Accepted analysis checksum: `abc123...`
> - Accepted plan checksum: `def456...`
> - Gate checksum: `ghi789...`
>
> Approving will queue the transformation commands. Continue?

---

## Reject Current State

User rejects the current analysis, plan, or approval.

### Example Inputs

| User says | Classified Intent | Action |
|-----------|------------------|--------|
| "reject" | reject_from_gate | Reject with reason |
| "deny" | reject_from_gate | Reject with reason |
| "this is too risky" | reject_from_gate | Reject with reason |
| "I don't approve" | reject_from_gate | Reject with reason |
| "stop, this isn't right" | reject_from_gate | Reject with reason |

### Assistant Responses

> I understand you'd like to reject this gate. Please provide a reason
> for rejection so it can be recorded in the audit trail.
>
> **Warning:** Rejecting this gate will prevent proceeding to the next
> phase. You may need to restart the process from an earlier stage.

---

## Ask About Gate Evidence

User asks for details about the current gate's evidence.

### Example Inputs

| User says | Classified Intent | Action |
|-----------|------------------|--------|
| "what did the analysis find?" | explain_gate_evidence | Show evidence explanation |
| "show me the risks" | explain_gate_evidence | Show evidence explanation |
| "what are the available actions?" | show_gate_available_actions | Show available actions |
| "what can I do now?" | show_gate_available_actions | Show available actions |
| "explain this gate" | explain_gate_evidence | Show evidence explanation |

### Assistant Responses

> **Analysis Review — Gate a1b2c3d4**
>
> The analysis has completed for Stage 1. Here are the findings:
>
> - **3 high-risk dependencies** found in database layer
> - **5 medium-risk config changes** in application.properties
> - **12 source files** identified for transformation
> - **Test inventory:** 45 existing tests, 8 need updates
>
> **Available Actions:**
> - ✅ **Continue**: Proceed to planning phase
> - ✅ **Request Reanalysis**: Re-run with additional configs
>
> Would you like to proceed or need more details?

---

## Clarification Examples

When the user's intent is ambiguous, the assistant asks for clarification.

### Example: "looks okay"

> I see you're reviewing the analysis. Here's a quick summary:
>
> - 3 high risks found in database migration
> - 5 medium risks in config changes
>
> What would you like to do?
> - **Continue** to planning (accept these findings)
> - **Reanalyze** with additional configuration files

### Example: "fix it" (at repair gate)

> I understand something needs fixing. Could you clarify?
>
> - **Request repair**: Apply the suggested patch
> - **Reanalyze**: Re-run analysis to find additional issues
> - **Revise**: Update the repair approach

### Example: Short vague text

> I'm not sure what you'd like to do. Could you be more specific?
> Available actions: continue, reanalyze, revise, approve, reject.

---

## Blocked Examples

The following user requests are always rejected because the backend
enforces strict action types.

| User says | Why blocked |
|-----------|-------------|
| "execute command mvn compile" | Direct command execution is blocked |
| "write a patch file" | File writes are blocked |
| "approve without gate" | Approvals must go through a gate |
| "skip the review step" | Stage skipping is blocked |
| "override the checksum" | Checksum override is blocked |
| "modify the source code directly" | Legacy source mutation is blocked |

### Assistant Response to Blocked Actions

> I'm sorry, but I cannot execute commands directly, write files, or
> bypass gate reviews. All state-changing actions must go through the
> governed gate workflow. I can help you:
>
> - Explain the current gate evidence
> - Draft a gate action (continue, reanalyze, etc.)
> - Show available actions for the current gate
>
> What would you like to do?

---

## Error Understanding / Model Fallback

When the LLM is unavailable, the assistant falls back to a deterministic
gate status card.

### Fallback Response

> **Gate Status (Fallback Mode)**
>
> - **Gate**: a1b2c3d4
> - **Phase**: analysis_review
> - **Stage**: 1
> - **Status**: open
> - **Checksum**: `abc123...`
>
> **Available Actions:**
> - ✅ **Continue**: Accept and proceed to planning
> - ✅ **Request Reanalysis**: Re-run with additional configs
>
> *This is a fallback response because the AI assistant is temporarily
> unavailable. The gate information above is accurate and up-to-date.*

---

## Stage Context Examples

### Analyzing Stage 1 (current)

> **Stage 1 Analysis Review**
>
> The analysis has identified 3 high-risk dependencies in the database
> layer. The current gate is for Stage 1. Available actions apply to
> this stage only.

### Asking about Stage 2 while Stage 1 is open

> You're currently in Stage 1 (analysis review). Stage 2 information
> is not yet available because Stage 1 must be completed first.
> Would you like to proceed with Stage 1?

### Non-existent stage

> Stage 3 does not exist yet. The current migration only has 2 stages
> defined. Available actions apply to Stage 1 (analysis review).
