# msa-utils Intelligence Audit

## Verdict

The `msa-utils` branch is useful as migration knowledge, but unsafe as a merge target.
It contains practical Spring Boot, Java, Jakarta, dependency, and test modernization intelligence.
It also removes or predates much of the governed Control Tower architecture now present on
`integration/fusion-chatbot-csv-msa`.

Use it as mined knowledge and memory seed data. Do not merge it directly.

## Branch Comparison

Current branch:

- `integration/fusion-chatbot-csv-msa`
- HEAD observed during audit: `4c037e2 Classify stage-aware migration failures`
- Contains governed Control Tower, R6 repair gates, R7B evidence packs, R7C classifier.

Migration intelligence branch:

- `origin/msa-utils`
- Commit observed: `b866df082fac5a90c157bbba081edfbe09c38e0e`
- Merge base: `1b9e9fe458fb48d47c398dfa7659eb74d4ec8267`
- Divergence: current has 438 unique commits; `msa-utils` has 28 unique commits.

High-level diff:

- 787 scoped files changed.
- Large Control Tower and F15 document deletions appear in the branch diff.
- New golden reference artifacts, remediation modules, review gates, and orchestration tests appear.

Conclusion: direct merge would risk replacing governed architecture. Selective extraction is the safe path.

## Key msa-utils Assets

Golden reference assets:

- `.migration/golden-references/msa-utils/golden_reference_summary.md`
- `.migration/golden-references/msa-utils/golden_reference_gap_report.json`
- `.migration/golden-references/rule-extraction-with-inventory/rule_extraction_summary.md`
- `.migration/golden-references/rule-extraction-with-inventory/rule_extraction_report.json`

Migration intelligence modules:

- `migration_factory/golden_reference/analyzer.py`
- `migration_factory/golden_reference/rule_extractor.py`
- `migration_factory/agents/build_agent/failure_classifier.py`
- `migration_factory/agents/transformation_agent/maven_pom_patcher.py`
- `migration_factory/agents/transformation_agent/review_gates.py`
- `migration_factory/remediation/behavioral_context.py`
- `migration_factory/remediation/legacy_equivalence.py`
- `migration_factory/remediation/legacy_guided_patch_proposal.py`
- `migration_factory/remediation/mockito_bean_placement.py`
- `migration_factory/remediation/test_context_repair.py`
- `migration_factory/remediation/strategy_router.py`
- `migration_factory/remediation/policy.py`
- `migration_factory/remediation/approved_patch_apply.py`
- `migration_factory/tools/reference_delta_analyzer.py`
- `migration_factory/tools/runtime_contract_analyzer.py`

Useful tests:

- `tests/orchestrator/test_strategy_router.py`
- `tests/orchestrator/test_mockito_bean_placement.py`
- `tests/orchestrator/test_test_context_repair.py`
- `tests/orchestrator/test_legacy_guided_patch_proposal.py`
- `tests/orchestrator/test_behavioral_context.py`
- `tests/orchestrator/test_legacy_equivalence.py`
- `tests/orchestrator/test_powermock_gate.py`
- `tests/test_golden_rule_extractor.py`

## Capability Inventory

| Capability | Source | Category | Stage relevance | Evidence | Governance fit | Action |
| --- | --- | --- | --- | --- | --- | --- |
| `JAVA_VERSION_ALIGNMENT` | golden summary, POM patcher | deterministic rule | Stages 2, 3, 4 | stage Java target, POM compiler config | backend proposal later | Map to compiler/toolchain classifier and proposal generator. |
| `SPRING_BOOT_VERSION_ALIGNMENT` | golden summary, POM patcher | deterministic rule | All stages | stage Boot target, parent/plugin/dependency refs | backend proposal later | Reuse as stage profile alignment rule. |
| `JJWT_VERSION_ALIGNMENT` | golden summary, POM patcher, review gate | dependency rule | Boot 3/4 mostly | POM, source usage | mixed deterministic plus review | Add classifier and human review gate before proposal. |
| `JAKARTA_DEPENDENCY_ADDITION` / `JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT` | golden summary, rule extractor, POM patcher | dependency rule | Boot 3/4 | POM, dependency graph, validation usage | deterministic candidate | Integrate with existing validation families. |
| `LOMBOK_VERSION_ALIGNMENT` | golden summary, POM patcher | dependency rule | Java 17/21 stages | POM/dependency graph | deterministic candidate | Add classifier/proposal after version policy exists. |
| `SLF4J_VERSION_ALIGNMENT` | golden summary, POM patcher | dependency rule | Boot 3/4 | POM/dependency graph | deterministic candidate | Add dependency alignment family later. |
| `IMPORT_JAVAX_VALIDATION_TO_JAKARTA` | golden analyzer | source transform | Boot 3/4 | source refs, compile error, stage target | deterministic candidate | Extend current R7C taxonomy. |
| `IMPORT_JAVAX_SERVLET_TO_JAKARTA` | golden analyzer | source transform | Boot 3/4 | source refs, compile error, dependency graph | already partial | Reconcile with controlled R6 inverse case and real Boot 3 case. |
| `SPRING_DATA_SORT_BY_MIGRATION` | golden analyzer | source transform | Boot 3/4 | source refs, compile/test error | deterministic candidate | Add only after exact pattern tests. |
| `MOCKBEAN_TO_MOCKITOBEAN` | golden analyzer, mockito placement | test modernization | Boot 3.4/4 primarily | test source, Spring test dependency, failed tests | deterministic only for narrow cases | Mine for RAG and later bounded proposal generator. |
| `INITMOCKS_TO_OPENMOCKS` | golden analyzer | test modernization | all Java/Spring stages if Mockito present | test source | deterministic candidate | Good later deterministic proposal. |
| `POWERMOCK_LEGACY_TEST_STRATEGY` | review gates, rule extractor | human review gate | Java 17/21 and Boot 3/4 risk | POM, test source markers | human review | Add gate, not auto-repair. |
| `SPRING_SECURITY_BEHAVIOR_REVIEW` | golden summary | human review gate | Boot 3/4 | POM, security config, test/runtime diffs | human review | Add as advisory gate. |
| `AZURE_SDK_API_MIGRATION` / playbook | review gates, rule extractor | human/LLM | Boot version independent | POM and source imports | human plus LLM candidate | Memory seed, not deterministic. |
| `PUBLIC_API_SIGNATURE_CHANGE` | golden analyzer | human review gate | all stages | public API diff, consumer contracts | human review | Map to consumer compatibility gate. |
| `UNMAPPED_SOURCE_TRANSFORMATION` | golden summary | LLM candidate | all stages | source/reference delta | proposer/reviewer later | RAG seed for R7E/R7F, no apply now. |
| behavioral failure classifier categories | build classifier | diagnosis | Boot 3/4 mainly but useful generally | surefire XML, source context | classifier only now | Import taxonomy into stage classifier, no repair enablement. |

## Current Failure Mapping

Observed current failure:

- `classification_status`: `unsupported_known_failure`
- `failure_type`: `unsupported_legacy_test_or_api_dependency`
- matched signal: `unsupported:legacy_dependency_or_test_framework`
- stage target: Spring Boot 2.1 / Java 11 to Spring Boot 2.7 / Java 11
- missing: build/test failure artifacts
- usable: dependency graph, runtime contract, reference delta, and related stage evidence

Current R7C classifier maps `springfox` or `powermock` signals to this unsupported type.
`msa-utils` gives sharper names:

- `POWERMOCK_LEGACY_TEST_STRATEGY`
- `LEGACY_TEST_FRAMEWORK_MIGRATION`
- `MOCKITO_FINAL_CLASS_MOCKING_LIMITATION`
- `SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT`
- `JAKARTA_VALIDATION_HANDLER_MISMATCH`
- `HTTP_STATUS_CONTRACT_DRIFT`
- `APPLICATION_BEHAVIOR_REGRESSION`
- `AZURE_SDK_API_MIGRATION`
- `PUBLIC_API_SIGNATURE_CHANGE`

For the current Stage 1 target, this should not become a supported repair family yet.
The safer behavior is:

- keep repair disabled;
- keep `unsupported_known_failure` when dependency/reference evidence proves a known legacy framework risk;
- use `blocked_pending_evidence` when the only blocker is missing build/test artifacts;
- refine into a human-review or LLM-candidate subtype after build/test artifacts exist.

`MOCKBEAN_TO_MOCKITOBEAN` is not a Stage 1 Boot 2.7 repair. It is mainly relevant to later Boot 3.4/4 test modernization and should be stage-filtered.

## Deterministic Rules To Import Later

High priority:

- `IMPORT_JAVAX_SERVLET_TO_JAKARTA`: Boot 3/4 source namespace migration; must use source checksums and dependency proof.
- `IMPORT_JAVAX_VALIDATION_TO_JAKARTA`: Boot 3/4 validation namespace migration; must use compile/test evidence.
- `JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT`: Boot 3/4 dependency alignment; POM/dependency graph required.
- `MAVEN_COMPILER_PLUGIN_SOURCE_TARGET_MISMATCH`: current branch already has classifier; import POM patch tactics.
- `JAVA_VERSION_ALIGNMENT`: use stage Java target and compiler config.

Medium priority:

- `JJWT_VERSION_ALIGNMENT`: needs source usage review and compatibility tests.
- `LOMBOK_VERSION_ALIGNMENT`: bounded POM proposal after version policy.
- `SLF4J_VERSION_ALIGNMENT`: bounded POM proposal after dependency policy.
- `INITMOCKS_TO_OPENMOCKS`: narrow test source rewrite.
- `SPRING_DATA_SORT_BY_MIGRATION`: narrow source rewrite after exact test corpus.

Low or gated:

- `MOCKBEAN_TO_MOCKITOBEAN`: deterministic only for narrow placement cases; otherwise human/LLM.
- `SPRING_DATA_SORT_BY_MIGRATION`: likely safe only after compile/test evidence and exact AST/text guard.

## Human Review Gates To Import Later

- `POWERMOCK_LEGACY_TEST_STRATEGY`: static/final/constructor mocking creates behavior risk.
- `JAKARTA_HYBRID_STRATEGY`: mixed javax/jakarta state often needs stage-specific intent.
- `AZURE_SDK_MIGRATION_PLAYBOOK`: old and new SDK coordinates/API surfaces need review.
- `API_CONTRACT_REVIEW_GATE`: public signature changes require consumer compatibility.
- `CONSUMER_COMPATIBILITY_VALIDATION`: public API and client impact proof.
- `SPRING_SECURITY_BEHAVIOR_REVIEW`: Boot 3 security behavior can drift without compile failure.
- `JUNEAU_VERSION_ALIGNMENT_OR_REVIEW`: dependency plus API behavior risk.

## LLM / RAG Candidates

Use LLM proposer only after deterministic evidence pack and classifier are present.

Good candidates:

- `UNMAPPED_SOURCE_TRANSFORMATION`
- repeated behavioral failure after deterministic patch
- ambiguous MockitoBean placement
- public API signature change explanation and proposal options
- Azure SDK API migration
- Spring MVC exception behavior drift
- application behavior regression where deterministic rule lacks confidence

Reviewer must receive:

- stage metadata;
- evidence pack checksum;
- retrieved memory case ids;
- proposed diff checksum;
- before/proposed file checksums;
- deterministic blockers and missing evidence;
- verification plan.

Fallback model should trigger on:

- low confidence;
- reviewer disagreement;
- apply failure;
- verification failure;
- repeated same blocker;
- stale or conflicting memory.

## Integration Plan

Near-term:

1. Add `msa-utils` rule inventory as read-only knowledge.
2. Refine R7C classifier labels with stage filters, still repair disabled.
3. Add memory seed schema and read-only retrieval.

Later:

1. Add evidence-bound proposer for one narrow family.
2. Add reviewer prompt memory snippets.
3. Promote repeated successful cases into deterministic rule registry.
4. Reconcile with 4-stage branch through shared stage metadata and evidence contracts.

## Do Not Import Directly

- `migration_factory/remediation/approved_patch_apply.py` as an apply path. Current backend-owned R6/R7 apply spine supersedes it.
- Direct remediation executor behavior.
- Any UI/client-supplied patch/path/command/model fields.
- Old Control Tower replacements or branch-level deletions.

## Files Inspected

- `origin/msa-utils:.migration/golden-references/msa-utils/golden_reference_summary.md`
- `origin/msa-utils:.migration/golden-references/rule-extraction-with-inventory/rule_extraction_summary.md`
- `origin/msa-utils:migration_factory/agents/build_agent/failure_classifier.py`
- `origin/msa-utils:migration_factory/agents/transformation_agent/maven_pom_patcher.py`
- `origin/msa-utils:migration_factory/agents/transformation_agent/review_gates.py`
- `origin/msa-utils:migration_factory/golden_reference/analyzer.py`
- `origin/msa-utils:migration_factory/golden_reference/rule_extractor.py`
- `origin/msa-utils:migration_factory/remediation/strategy_router.py`
- `origin/msa-utils:migration_factory/remediation/policy.py`
- `origin/msa-utils:migration_factory/remediation/approved_patch_apply.py`
- `origin/msa-utils:tests/orchestrator/test_strategy_router.py`
- `origin/msa-utils:tests/orchestrator/test_mockito_bean_placement.py`
- `origin/msa-utils:tests/orchestrator/test_test_context_repair.py`
- `origin/msa-utils:tests/orchestrator/test_legacy_guided_patch_proposal.py`
- `origin/msa-utils:tests/orchestrator/test_behavioral_context.py`
- `origin/msa-utils:tests/orchestrator/test_legacy_equivalence.py`
- `origin/msa-utils:tests/orchestrator/test_powermock_gate.py`
- `origin/msa-utils:tests/test_golden_rule_extractor.py`
- `migration_factory/control_tower/application/v2_stage_failure_classifier.py`
