# Final Report AI Trace

## Goal

Add an AI trace section to the final report after diagnosis/proposal/review/approval/validation records exist.

Do not start here; this depends on features 1-8.

## Current State in Repo

Exact files/classes/functions found:

- `migration_factory/final_report/context_builder.py`
  - `build_report_context()` loads deterministic artifacts and builds provenance.
  - Redacts secrets and relativizes paths.
- `migration_factory/final_report/writer.py`
  - `generate_final_migration_report()` writes JSON and Markdown final reports.
  - `_repair_loop_context()` already includes repair-loop status, ledger ref, attempts, validation after repair.
  - `_build_markdown_summary()` renders repair-loop and dependency-policy sections.
- `migration_factory/final_report/copilot.py`
  - Generates governed Copilot final report material with guardrails.
- `migration_factory/repair_loop/ledger.py`
  - `repair_ledger.json` stores attempt status and repair artifacts.
- `migration_factory/control_tower/application/v2_assistant_service.py`
  - Assistant messages and draft actions.
- `migration_factory/control_tower/application/v2_approval_mapping.py`
  - Approval cards and resume commands.

What already exists:

- Final report JSON/Markdown generation.
- Report context/provenance.
- Repair-loop context.
- Guardrailed Copilot report material.
- Approval and assistant records.

What must not be duplicated:

- Final report writer.
- Report context builder.
- Repair ledger.
- Approval records.
- Assistant messages.

## Proposed Implementation

After features 1-8, extend final report context and writer with an AI trace section:

```text
- event
- agent
- evidence refs
- diagnosis
- proposal
- reviewer verdict
- human decision
- validation result
```

Steps:

1. Extend `build_report_context()` to load AI diagnosis/proposal/reviewer/approval/repair ledger refs.
2. Redact and relativize all refs using existing final-report redaction helpers.
3. Add `ai_trace` to final report JSON payload.
4. Add `## AI Trace` to Markdown only when records exist.
5. Include guardrail statement:
   - LLM proposed/reviewed only.
   - Human approved.
   - Backend applied in sandbox.
   - Maven/tests/proof are source of truth.

## Data / Schema Changes

Add final report JSON field:

```json
{
  "ai_trace": [
    {
      "event": "",
      "agent": "",
      "evidence_refs": [],
      "context_pack_checksum": "",
      "diagnosis": "",
      "proposal_ref": "",
      "proposal_checksum": "",
      "reviewer_verdict": "",
      "human_decision": "",
      "validation_result": "",
      "ledger_ref": ""
    }
  ]
}
```

Technical basis: final AI trace should distinguish structured model outputs from tool execution; OpenAI tool/function calling describes tool arguments as model output for application handling, and Azure JSON mode caveats reinforce that schema-bound outputs are preferable for durable report facts: [OpenAI Function Calling](https://developers.openai.com/api/docs/guides/function-calling), [Azure OpenAI JSON mode](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/json-mode).

## Backend Flow

```text
final report requested
-> build_report_context()
-> load AI trace records and repair ledger
-> redact/relativize
-> writer adds JSON + Markdown section
```

## UI / Cockpit Impact

Proof & Report panel can link to final report AI trace after report generation. It should not show the trace before backend report exists.

## Human Supervision Point

The final report documents the human decision and proof chain. It does not create a new approval point.

## Safety / Governance

- Sandbox only: report states sandbox binding and validation refs.
- No legacy mutation: report should state legacy source unchanged when proof exists.
- Human approval boundary: report separates reviewer critique from human decision.
- Backend-owned action gate: trace identifies which LLM migration intents entered resolver, approval, bridge, apply, validation, rollback, and ledger gates.
- Checksum/proof gates: trace cites proposal/review/approval/ledger/proof checksums.

## Tests

Targeted tests:

- Extend `tests/test_final_report.py`.
- Extend `tests/reporting/test_report_context.py`.
- Extend `tests/reporting/test_copilot_final_report.py` only if Copilot report uses the new trace.
- Add `test_final_report_ai_trace_uses_existing_records`.
- Add `test_final_report_ai_trace_redacts_paths_and_secrets`.
- Add `test_final_report_ai_trace_distinguishes_llm_review_from_human_approval`.

## Risks

- Adding trace claims before real records exist.
- Letting advisory text imply LLM applied or approved.
- Leaking raw model prompts or secret-bearing evidence.

## Open Questions

- Should AI trace be included in every final report or only when AI diagnosis records exist?
- Should assistant chat messages be summarized or cited by message id only?
- Which record is the canonical validation result: repair-loop ledger, V2 event, or proof report?
