# Stable Branch Azure AI Foundry / Copilot Audit

## 1. Executive Verdict
- Verdict: **Not aligned. Demo 3 implementation should not continue as an Azure AI Foundry-only product until the provider boundary, public DTOs, Copilot reachability, and product documentation are corrected.**
- Branch: `stable`
- Commit: `ff84d69`
- Worktree: Clean isolated `stable` worktree before this report; the original dirty `chatbot-optimization` worktree was left untouched.
- Docs aligned: **No.** The requested Demo 3 PRD and sprint documentation do not exist on `stable`. Existing stable documentation describes Copilot as a supported optional runtime/reporting capability and Azure OpenAI as a live model provider.
- Code aligned: **No.** Backend model access directly reads `AZURE_OPENAI_*`, emits `azure_openai`, supports model fallback, and exposes provider/env metadata. Copilot is enabled and routed by default in the legacy orchestrator.
- Main blockers: No backend-owned Foundry adapter contract; direct Azure OpenAI configuration and HTTP path; public provider/env/fallback leakage; executable/default Copilot paths; missing Demo 3 source-of-truth docs; UUID-derived rather than content-derived context-pack checksums.

## 2. Documentation Alignment
| File | Finding | Category | Why it matters | Required fix |
|---|---|---:|---|---|
| `docs/DEMO3/PRD.md` | File does not exist on `stable`. | A | There is no stable-branch product contract stating Foundry-only runtime and terminology. | Add or merge the Demo 3 PRD after resolving code-policy contradictions. |
| `docs/sprintdemo3/` | Directory and required `INDEX.md`, `TASKS.md`, `ROADMAP.md`, `ARCHITECTURE.md`, and `RISKS.md` do not exist on `stable`. | A | Sprint implementation has no stable source of truth for the new provider boundary. | Add the reviewed sprint documentation and make it authoritative for Demo 3. |
| `README.md:13,37-38,68,96,220-225,274` | Documents optional Copilot advisory statements, Copilot documentation agent, Copilot environment configuration, and Copilot artifacts as current product behavior. | A | Client/developer-facing product language contradicts “No Copilot runtime path” and “No Copilot client-facing terminology.” | Rewrite current scope, architecture, runbook, artifacts, and safety language around Azure AI Foundry or provider-neutral AI; quarantine legacy names in a compatibility note. |
| `docs/system/00-overview.md:5,23,35,45-46,66,76,100-103,122` | Describes Copilot as advisory/reporting functionality and records Copilot runtime status. | A/C | This is explicit product/runtime capability documentation, not prohibition language. | Replace current architecture narrative; move historical behavior to a clearly marked legacy compatibility appendix. |
| `docs/system/01-architecture.md:19-23,61,69,96,109,161-162` | Architecture includes Copilot nodes, state fields, artifacts, AI Hub configuration, and tests. | A/C | The documented architecture promises a reachable Copilot subsystem. | Redraw architecture around one backend-owned Foundry adapter and remove Copilot from current product flows. |
| `docs/system/05-copilot-integration.md:1-280` | Full live Copilot configuration/runbook, including CLI availability, default provider, environment variables, provider flow, and extension instructions. | A/C | Directly contradicts the new goal and can guide implementation toward the prohibited runtime. | Retire from current docs or relabel as non-runtime legacy quarantine documentation. |
| `docs/system/09-how-to-run.md:23-42,136-172` | Tells operators how to enable Copilot and use `copilot_cli`. | A/C | Makes the prohibited runtime operationally reachable. | Remove from active runbook; retain only migration/history notes if needed. |
| `docs/governed-llm-migration-supervisor/index.md:26,32,35,189-190` | Describes Azure-backed assistant fallback, Copilot repair primitives, Copilot final report, and Azure OpenAI behavior. | A/C | Current governing docs encode the old architecture. | Update the supervisor index to require the Foundry adapter, fail-closed behavior, and compatibility boundaries. |
| `docs/governed-llm-migration-supervisor/14-stage3-pom-dependency-editor.md:89` | Calls the stable LLM client “Azure OpenAI with deterministic fallback.” | A/C | Explicitly contradicts Foundry-only and fail-closed model semantics. | Replace with the intended Foundry adapter contract and explicit unavailable/error states. |
| `docs/audits/V2_LIVE_COCKPIT_AI_BUILD_AUDIT.md:164-226,516-520,557,608-619` | Accurately records Azure OpenAI HTTP/config and fallback behavior. | B | Useful evidence of current reality, but not an acceptable target architecture. | Preserve as a historical audit with a superseded banner and link to this report. |
| `docs/F15/job071-to-implement-add-model-fallback-behavior.md` and fallback prohibition references | Fallback is discussed as a bounded deterministic behavior. | D/B | Some references are safety requirements, but successful-looking fallback output remains risky. | Clarify that deterministic assistance is explicitly labeled non-model output and cannot satisfy a required model-backed operation. |

## 3. Client-Facing Blockers
| File:line | Term/API field/UI text | Category | Finding | Proposed fix |
|---|---|---:|---|---|
| `migration_factory/control_tower/application/v2_settings.py:117-124,198-215` | `provider`, `env_ref`, role `env_ref`, `fallback` | A | `/v1/settings/ai` serializes provider identity, Azure OpenAI environment variable names, role mapping, and fallback configuration. Values are redacted, but provider/config internals still leak. | Project only product-level readiness, profile label, role readiness, and safe status codes. |
| `migration_factory/control_tower/adapters/fastapi/app.py:1001-1010` | `/v1/settings/ai` | A | Public settings endpoint returns the leaking projection. | Replace response DTO with a provider-neutral/Foundry-branded readiness projection. |
| `migration_factory/control_tower/adapters/fastapi/app.py:2203-2211,2279-2304` | `provider`, `source`, `failure_reason` | A | Assistant events and responses expose `azure_openai`, model source, provider, fallback state, and internal failure reason. | Return stable product statuses such as `ready`, `unavailable`, or `degraded`; keep provider details in protected backend telemetry. |
| `migration_factory/control_tower/adapters/fastapi/app.py:3099-3177` | `provider_kind`, `model_env_ref`, `endpoint_env_ref`, `deployment_env_ref`, accepted `azure_openai` | A/C | Public model-profile CRUD accepts and returns provider and environment-reference internals. | Remove these fields from public APIs; make adapter/config selection backend-owned. |
| `migration_factory/control_tower/adapters/fastapi/app.py:10022-10055` | “Azure OpenAI”, `Source: azure_openai` | A | Assistant-generated status text exposes prohibited product terminology. | Use “Azure AI Foundry” or provider-neutral model readiness language. |
| `migration_factory/control_tower/adapters/fastapi/app.py:10329-10369` | `azure_openai`, `copilot_status` | A | Model prompts include provider source and failure summaries include Copilot status. | Remove provider/Copilot details from model context unless needed as internal compatibility data and normalized before invocation. |
| `migration_factory/control_tower/adapters/fastapi/app.py:10875-10886` | `copilot_status`, `repair_fallback` | A | Public failure summary exposes legacy runtime state. | Map to provider-neutral `ai_repair_status` and explicit deterministic/error semantics. |
| `web/control-tower/lib/contracts.ts:496-506` | assistant `source`, `provider`, `failure_reason` | A | Frontend contract requires provider internals. | Replace with a product-level readiness/result status contract. |
| `web/control-tower/lib/contracts.ts:562-573` | settings `provider`, endpoint/role `env_ref` | A | Frontend contract explicitly models backend provider configuration. | Remove provider/env refs from the client contract. |
| `web/control-tower/lib/contracts.ts:627-638` | `copilot_status` | A | Public frontend failure DTO retains Copilot terminology. | Rename through a compatibility projection and stop returning the legacy field publicly. |
| `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx:69,199-201` | `Source`, failure reason, “Live Azure OpenAI” | A | Cockpit directly displays provider/source internals and prohibited terminology. | Display “Azure AI Foundry ready/unavailable” or neutral “AI service” state. |
| `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx:769` | `Copilot:` | A | User-visible Copilot status remains in the Demo surface. | Replace with provider-neutral repair status after backend compatibility mapping. |
| `web/control-tower/app/migrations/new/NewMigrationForm.tsx:65-70,495-513` | “Azure Settings”, provider value | A | Setup UI displays raw provider identity and models env-ref configuration. | Use “Azure AI Foundry readiness”; do not display provider/config internals. |
| `migration_factory/assessment/writer.py:172-174,418` | `copilot` and “Copilot advisory” | A/B | Generated assessment JSON/Markdown can be client-visible artifacts containing Copilot terminology. | Normalize public reports while preserving legacy artifact readability internally. |
| `migration_factory/tui/app.py` and `migration_factory/tui/copilot_status.py` | Copilot labels, artifacts, connectivity, provider | A/C | TUI is a client-facing surface and can probe Copilot CLI. | Remove current product labels and runtime probes; quarantine legacy artifact rendering behind compatibility-only views. |

## 4. Runtime Provider Blockers
| File:line | Code path/config | Category | Finding | Proposed fix |
|---|---|---:|---|---|
| `migration_factory/control_tower/application/v2_settings.py:63-74` | “Foundry” settings default to `azure_openai` and `AZURE_OPENAI_*` | C | Foundry naming is currently a wrapper over Azure OpenAI-specific configuration. | Introduce a real backend-owned Foundry settings object and adapter boundary. |
| `migration_factory/control_tower/application/v2_assistant_model_client.py:48-58,235-328,911-918` | Direct environment reads and Azure OpenAI HTTP client | C | Live calls require `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, deployments, and API-version behavior. | Move all model access behind the Foundry adapter; application services must not read provider env vars. |
| `migration_factory/control_tower/application/v2_assistant_model_client.py:892-903` | Deterministic fallback appended as assistant content | C/A | Model failure returns answer content plus provider/failure diagnostics, which can be consumed as an assistant response. | Fail closed for model-required operations; expose deterministic guidance as a distinct non-model result. |
| `migration_factory/control_tower/application/v2_model_role_router.py:67-147,164-229` | Azure OpenAI deployment refs, fallback model, deterministic fallback | C | Router owns provider-specific deployment selection and may try a configured fallback deployment. | Route roles through Foundry adapter capabilities; remove Azure OpenAI fallback path. |
| `migration_factory/control_tower/adapters/fastapi/app.py:10401-10407` | Readiness checks `AZURE_OPENAI_*` directly | C | API layer bypasses any backend adapter/config abstraction. | Ask the Foundry adapter for readiness without exposing its configuration. |
| `migration_factory/orchestrator/state.py:16-23,203-210,248-282` | Copilot defaults: mode `failures`, report enabled, provider `copilot_cli` | C | Copilot is enabled and selected by default. | Default all Copilot runtime paths off and make them unreachable from Demo 3. |
| `migration_factory/orchestrator/graph.py:75-86,89-125,229-237,270-273` | Copilot assist and final-report graph nodes | C | The orchestrator has executable routes to Copilot assist and final reporting. | Remove these nodes from Demo 3 graph wiring or guard them behind an internal legacy-only runner that Demo 3 cannot select. |
| `migration_factory/orchestrator/preflight.py:68-84` | Copilot availability probe | C | Preflight probes Copilot and can fail if Copilot is required. | Remove from Demo 3 preflight; Foundry readiness belongs to the backend adapter. |
| `migration_factory/orchestrator/summary.py:172-259` | Copilot report and documentation generation | C | Summary/finalization can invoke Copilot CLI report generation and always attempts Copilot docs generation. | Disable for Demo 3 and replace client-facing output with provider-neutral/Foundry-governed reporting. |
| `migration_factory/final_report/copilot.py:17-41` and provider execution paths | Copilot CLI resolver and provider configuration | C | A live Copilot CLI adapter remains implemented. | Keep module only as quarantined legacy code; remove all current runner/import reachability. |
| `migration_factory/transform_v1_after_approval.py:647-668` | Dependency Copilot advisory invocation | C | Transform flow can invoke Copilot advisory behavior when policy requires it. | Disable/unwire from Demo 3; route future model proposals through the Foundry adapter and human/backend gates. |
| `migration_factory/agents/analysis_agent/analysis_agent/copilot_enricher.py:127-144,259-297` | Copilot SDK boundary/import | C | Analysis path contains a Copilot SDK execution boundary. | Ensure Demo 3 cannot instantiate or route to it; retain only quarantined legacy compatibility if needed. |
| `migration_factory/control_tower/application/v2_model_schemas.py:448-492` | Context pack checksum `cp-{random UUID prefix}` | C | Checksum is not content-derived and no policy version is bound to the model invocation. | Compute SHA-256 over canonical redacted pack content and include policy version. |

## 5. Copilot Runtime Reachability
- Default state: **Enabled.** `DEFAULT_COPILOT_ASSIST_MODE = "failures"`, `DEFAULT_COPILOT_REPORT_ENABLED = True`, and `DEFAULT_COPILOT_PROVIDER = "copilot_cli"`.
- Orchestrator path: `migration_factory/orchestrator/graph.py` registers `copilot_phase_assist` and `copilot_final_report`; failures route to assist by default and final reports route to Copilot when the default report flag is true.
- Preflight path: `migration_factory/orchestrator/preflight.py` calls `probe_copilot_availability()` and can make Copilot availability mandatory.
- Summary/final report path: `migration_factory/orchestrator/summary.py` can detect/invoke Copilot CLI report generation and invokes the Copilot documentation package.
- Agent paths: Analysis contains a Copilot SDK wrapper; planning resolves Copilot auth/model/config; transform can invoke a dependency Copilot advisory.
- TUI paths: The TUI displays Copilot statuses/artifacts and calls `detect_copilot_cli_status()`.
- Verdict: **Copilot runtime is reachable and partly enabled by default. It is not merely dead compatibility code.**

## 6. Azure AI Foundry-Only Gap
Foundry-only requires one backend-owned adapter/configuration object that owns authentication, endpoint resolution, deployment/model role mapping, invocation, readiness, redaction, and provider telemetry. Application services should depend on that interface and must not read `AZURE_OPENAI_*`, construct Azure OpenAI URLs, or select provider/fallback deployments.

Frontend and public APIs must receive only product-level readiness and outcome states. They must not receive provider names, environment references, deployment references, credential names, or fallback-provider details. Copilot nodes, CLI/SDK probes, and report/repair invocations must be unreachable from Demo 3 flows. Historical Copilot schemas and artifacts may remain readable through internal compatibility adapters.

There must be no Azure OpenAI provider fallback. If a required Foundry call fails, the operation must fail closed or return an explicit AI-unavailable result. Deterministic guidance may still exist, but it must be represented as non-model output and must not masquerade as a successful model answer or satisfy a model-required proposal/review.

Context packs are partly bounded and redacted today (`v2_evidence_pack_builder.py`), but the model `ContextPack` checksum is UUID-derived, not content-derived, and carries no policy version. Foundry invocation must bind to a canonical SHA-256 of the exact redacted context supplied to the model and treat retrieved/source text as untrusted data.

## 7. Legacy Items That Can Be Deferred
| Item | Why it can remain temporarily | Required boundary |
|---|---|---|
| `migration_factory/contracts/schemas/copilot_*.schema.json` | Historical artifacts and persisted runs may require them. | Internal read compatibility only; never project names/fields into current public APIs or UI. |
| `migration_factory/contracts/copilot_artifacts.py` and legacy artifact readers | Needed to read old run directories. | No execution, provider selection, or new artifact production in Demo 3. |
| Existing DB values such as `azure_openai`, `copilot_cli`, and `copilot_*` fields | Database migration may need phased compatibility. | Translate at repository/projection boundaries; new public contracts use current terminology. |
| Legacy tests and fixtures containing provider/Copilot strings | They document compatibility and security behavior. | Mark as compatibility/security tests and add separate tests proving absence from public/runtime surfaces. |
| Historical audit documents | They accurately record prior behavior. | Add “historical/superseded” banners and exclude them from current architecture/runbooks. |
| Quarantined Copilot modules | Deletion is not required for this migration. | No imports or routes from Demo 3 entry points; explicit reachability tests must prove quarantine. |

## 8. Required Fix Features

### Feature FND-01 — Foundry Adapter Contract
Purpose: Replace Azure OpenAI-specific model access with one backend-owned Azure AI Foundry adapter/config contract.

Likely modified files:
- `migration_factory/control_tower/application/v2_assistant_model_client.py`
- `migration_factory/control_tower/application/v2_settings.py`
- `migration_factory/control_tower/application/v2_model_role_router.py`
- `migration_factory/control_tower/application/v2_azure_health_service.py`

Likely new files:
- `migration_factory/control_tower/application/azure_ai_foundry_adapter.py`
- `migration_factory/control_tower/application/v2_foundry_settings.py`
- `tests/control_tower/test_v2_foundry_adapter.py`
- `tests/control_tower/test_v2_foundry_settings.py`

Acceptance:
- No application service or API layer directly reads `AZURE_OPENAI_*` or `OPENAI_API_KEY`.
- Live model calls and readiness checks use the Foundry adapter.
- Public API does not expose provider/env internals.
- Foundry failures fail closed for model-required operations.
- No Azure OpenAI fallback deployment is selected.

Tests:
- Adapter success/error/redaction tests.
- Settings validation without public env-ref projection.
- Search-based test forbidding direct provider env reads outside the adapter.
- Failure tests proving no successful-looking fallback output.

### Feature FND-02 — Remove Provider/Public DTO Leakage
Purpose: Replace provider/config-shaped public contracts with product-level AI readiness and result statuses.

Likely modified files:
- `migration_factory/control_tower/adapters/fastapi/app.py`
- `web/control-tower/lib/contracts.ts`
- `web/control-tower/lib/controlTowerApi.ts`
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
- `web/control-tower/app/migrations/new/NewMigrationForm.tsx`

Likely new files:
- Focused backend contract tests and frontend component/API tests.

Acceptance:
- Public JSON contains no `copilot`, `azure_openai`, `AZURE_OPENAI`, provider env refs, provider credentials, deployment refs, or fallback-provider details.
- Events keep provider details only in protected backend telemetry.
- UI uses “Azure AI Foundry” or provider-neutral readiness language.

Tests:
- Snapshot/recursive-key scans over settings, assistant, failure, event, and model-profile endpoints.
- TypeScript contract compilation and focused component rendering tests.

### Feature FND-03 — Disable Copilot Runtime Paths
Purpose: Make Copilot CLI/SDK/report/repair behavior unreachable from Demo 3 while retaining legacy files.

Likely modified files:
- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
- `migration_factory/orchestrator/state.py`
- `migration_factory/orchestrator/graph.py`
- `migration_factory/orchestrator/preflight.py`
- `migration_factory/orchestrator/summary.py`
- `migration_factory/final_report/copilot.py`
- `migration_factory/agents/planning_agent/copilot_assist_client.py`
- `migration_factory/agents/analysis_agent/analysis_agent/copilot_enricher.py`
- `migration_factory/transform_v1_after_approval.py`

Likely new files:
- Reachability/quarantine tests for Demo 3 entry points.

Acceptance:
- No Control Tower or Demo 3 flow invokes Copilot CLI/SDK.
- Copilot defaults are disabled.
- Preflight and finalization do not probe or invoke Copilot.
- Legacy modules remain only behind a non-Demo compatibility boundary.

Tests:
- Graph routing tests proving no Copilot nodes are selected.
- Mock/subprocess tests proving no Copilot executable lookup or process launch.
- Environment matrix tests proving legacy flags cannot activate Demo 3 paths.

### Feature FND-04 — UI Language Cleanup
Purpose: Remove Copilot and Azure OpenAI terminology from current client-facing UI, reports, runbooks, and artifacts.

Likely modified files:
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
- `web/control-tower/app/migrations/new/NewMigrationForm.tsx`
- `web/control-tower/lib/contracts.ts`
- `migration_factory/assessment/writer.py`
- `README.md`
- `migration_factory/tui/app.py`
- `migration_factory/tui/copilot_status.py`
- `migration_factory/tui/history.py`
- `docs/system/`
- `docs/governed-llm-migration-supervisor/`

Likely new files:
- `docs/DEMO3/PRD.md`
- `docs/sprintdemo3/INDEX.md`
- `docs/sprintdemo3/TASKS.md`
- `docs/sprintdemo3/ROADMAP.md`
- `docs/sprintdemo3/ARCHITECTURE.md`
- `docs/sprintdemo3/RISKS.md`

Acceptance:
- User-visible current product language contains no Copilot.
- User-visible current product language contains no Azure OpenAI except in clearly marked historical/legacy quarantine material.
- Demo surfaces show Azure AI Foundry or provider-neutral AI status.
- Documentation and code describe the same runtime boundary.

Tests:
- Focused UI text tests.
- Documentation lint/search allowlist separating current docs from historical compatibility docs.

### Feature FND-05 — Context Pack Enforcement
Purpose: Complete the existing bounded/redacted evidence work with deterministic content binding and prompt-injection boundaries.

Likely modified files:
- `migration_factory/control_tower/application/v2_evidence_pack_builder.py`
- `migration_factory/control_tower/application/v2_failure_diagnosis.py`
- `migration_factory/control_tower/application/v2_repair_flow.py`
- `migration_factory/control_tower/application/v2_model_schemas.py`

Likely new files:
- `migration_factory/control_tower/application/v2_context_pack_policy.py`
- `tests/control_tower/test_v2_context_pack_policy.py`

Acceptance:
- Context packs are bounded and redacted.
- Checksums are content-derived SHA-256 over canonical redacted model input.
- Context packs include policy version.
- Every model invocation binds to the exact context-pack checksum.
- Retrieved/source text is framed as untrusted data, never instructions.
- Artifact checksum mismatch fails closed.

Tests:
- Determinism and mutation-sensitive checksum tests.
- Redaction and budget boundary tests.
- Injection-content framing tests.
- Invocation/audit binding tests.

### Feature FND-06 — Compatibility Mapping and Legacy Quarantine
Purpose: Keep old persisted names readable without retaining old behavior or exposing old terminology.

Likely modified areas:
- `migration_factory/contracts/schemas/copilot_*.schema.json`
- `migration_factory/contracts/copilot_artifacts.py`
- Repository/public projection adapters.
- Existing DB values and legacy test fixtures.

Likely new files:
- Explicit compatibility mapper/projection module.
- Tests separating historical readability from current API/runtime behavior.

Acceptance:
- Historical artifacts remain readable.
- Public projections rename or hide legacy fields.
- Runtime does not invoke old Copilot behavior.
- New writes use current internal vocabulary where schema migration permits.
- Tests distinguish category B/D references from category A/C leaks.

Tests:
- Historical artifact load tests.
- Public projection absence tests.
- Runtime reachability tests.

## 9. Suggested Implementation Order
1. Approve and merge the Demo 3 PRD, architecture, risks, and terminology contract onto `stable`.
2. Implement FND-03 defaults/quarantine first so prohibited Copilot runtime cannot execute during subsequent work.
3. Implement FND-01 as the only model-access boundary.
4. Implement FND-02 and migrate public backend/frontend contracts.
5. Implement FND-04 across UI, reports, README, and current architecture/runbooks.
6. Implement FND-05 content-derived context binding and injection policy.
7. Implement FND-06 compatibility mapping and add allowlist-based regression tests.
8. Re-run this audit and only then continue Demo 3 feature slices.

## 10. Suggested Focused Tests
Backend:
- `tests/control_tower/test_v2_foundry_adapter.py`
- `tests/control_tower/test_v2_foundry_settings.py`
- Focused assistant/settings/model-profile/failure DTO tests.
- Orchestrator routing tests proving no Copilot nodes from Demo 3.

Frontend:
- Settings form renders Foundry/provider-neutral readiness without provider/env details.
- Cockpit assistant and failure panels contain no Copilot/Azure OpenAI text.
- Type contracts contain no public `provider`, `env_ref`, or `copilot_status` fields for these surfaces.

Security:
- Recursive response scans for `copilot`, `azure_openai`, `AZURE_OPENAI`, `OPENAI_API_KEY`, `provider_kind`, and `env_ref`.
- Context-pack redaction, canonical SHA-256, policy-version, and injection framing tests.
- No executable lookup/subprocess call for Copilot from Demo 3.

No-live-provider tests:
- Missing/unavailable Foundry returns an explicit unavailable/error result.
- Deterministic guidance is labeled non-model and cannot satisfy proposal/reviewer/repair model requirements.
- No Azure OpenAI or Copilot fallback is attempted.

## 11. Final Recommendation
- Can Demo 3 implementation proceed now? **No, not under the Azure AI Foundry-only claim.** Documentation planning may proceed, but runtime/UI feature implementation should wait for the provider and reachability blockers.
- What must be fixed first? Land the stable Demo 3 source-of-truth docs, disable/quarantine Copilot runtime routes, establish the Foundry adapter contract, and remove provider/config fields from public DTOs.
- Which docs need update? `README.md`, active `docs/system/`, active `docs/governed-llm-migration-supervisor/`, and the missing `docs/DEMO3/PRD.md` plus `docs/sprintdemo3/` set.
- Which code paths are highest risk? `v2_assistant_model_client.py`, `v2_settings.py`, `app.py` public settings/assistant/model-profile/failure endpoints, orchestrator defaults/graph/preflight/summary, and frontend cockpit/settings surfaces.
