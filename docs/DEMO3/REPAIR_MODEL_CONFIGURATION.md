# DEMO3 Reviewed Repair Model Configuration

The reviewed repair flow is backend-governed:

1. Build, test, or validation failure evidence is collected and redacted.
2. The Main Model role receives the repair context and creates an internal draft proposal.
3. The Reviewer Model role automatically reviews the Main Model output and exact diff checksums.
4. The backend stores `final_reviewed_repair.diff` and projects only the reviewed diff to the UI.
5. The user can approve sandbox apply or request a revision when the backend gate allows it.
6. Approval sends only identifiers and checksums. The backend resolves sandbox target context, applies the reviewed diff, rebuilds, reruns tests, and continues the route only after validation passes.

Users do not manually choose the Main or Reviewer model in the frontend. Model role routing is configured and invoked by backend code:

- `migration_factory/control_tower/application/v2_settings.py`
- `migration_factory/control_tower/application/v2_model_role_router.py`
- `migration_factory/control_tower/application/v2_assistant_model_client.py`
- `migration_factory/orchestrator/repair_review_chain.py`

Expected configuration concepts are environment variable names, not UI fields:

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_PROPOSER_DEPLOYMENT`
- `AZURE_OPENAI_REVIEWER_DEPLOYMENT`
- `AZURE_OPENAI_ASSISTANT_DEPLOYMENT`
- `AZURE_OPENAI_FALLBACK_DEPLOYMENT`

The frontend displays only safe model activity metadata from `GET /v1/v2/jobs/{job_id}/llm/activity`, including role label, responsibility, provider alias, optional safe model display name, deployment alias hash, checksums, status, token counts, latency, redacted summary, and redacted error.

No UI, API response, log snapshot, or documentation should expose actual endpoint values, API keys, raw deployment names, provider-internal deployment IDs, raw prompts, raw completions, local sandbox paths, raw commands, argv, env, or patch text as execution authority.

