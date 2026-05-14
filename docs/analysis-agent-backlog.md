# Analysis Agent Backlog Traceability (#1-#36)

Source backlog references found in repo:
- `migration_factory/agents/analysis_agent/agents.md`
- Inline task tags in scanner/assembler code (`Task #12`, `#13`, `#16`, `#17`, `#22`, typo `#231`)

Status legend: `Done` / `Partial` / `Missing` / `Blocked`.

| Item | Checkpoint | Status | Trace (code/tests) |
|---|---|---|---|
| #1 | Analysis agent entrypoint exists | Done | `analysis_agent/main.py` |
| #2 | CLI accepts run and path inputs | Done | `analysis_agent/main.py` |
| #3 | Migration context created per run | Done | `analysis_agent/context_manager.py` |
| #4 | Output artifacts written under run analysis dir | Done | `context_manager.py`, `report_assembler.py` |
| #5 | Legacy/modernized source not directly overwritten | Partial | `context_manager.py`; missing explicit integration test |
| #6 | Read-path validation for external paths | Partial | `context_manager.py::validate_read_path` (not uniformly used by scanners) |
| #7 | Write allowlist/denylist enforced | Done | `context_manager.py`, `tests/test_context_manager.py` |
| #8 | Root POM parser reads source stack | Done | `maven_scanner.py`, `tests/test_maven_scanner.py` |
| #9 | Java import scanner inventory | Done | `import_scanner.py` |
| #10 | Test inventory scanner | Done | `test_scanner.py` |
| #11 | Surefire parser summary | Done | `surefire_parser.py` |
| #12 | Java/Spring versions extracted from Maven | Done | `maven_scanner.py` |
| #13 | Output keys aligned for report contract | Done | `maven_scanner.py`, `report_assembler.py` |
| #14 | Config inventory scan (datasource/security/actuator) | Done | `config_scanner.py`, `tests/test_config_scanner.py` (includes datasource/actuator/security/port/profiles) |
| #15 | Dependency tree command executed | Done | `dependency_adapter.py` |
| #16 | `analysis_report.json` artifact emitted | Done | `report_assembler.py` |
| #17 | Analysis artifact write in analysis directory | Done | `report_assembler.py`, `context_manager.py` |
| #18 | Human-readable summary artifact | Done | `summary_generator.py` |
| #19 | Copilot enrichment optional/fail-open | Partial | `copilot_enricher.py` |
| #20 | Copilot auth resolver | Partial | `copilot_enricher.py` (env token only) |
| #21 | Copilot model resolver with explicit configuration | Partial | `copilot_enricher.py` |
| #22 | Report schema includes deterministic metadata | Done | `report_assembler.py` |
| #23 | Copilot guardrails prevent deterministic tampering | Partial | `copilot_enricher.py`, `tests/test_copilot_enricher.py` |
| #24 | Copilot status artifact emitted | Partial | `copilot_enricher.py` (`SUCCESS` uses non-contract status) |
| #25 | OpenRewrite dry-run adapter executes | Done | `openrewrite_adapter.py` |
| #26 | OpenRewrite status artifact captured | Partial | `openrewrite_adapter.py` (`SUCCESS` non-normalized) |
| #27 | OpenRewrite failure non-blocking | Done | `openrewrite_adapter.py` |
| #28 | Structured dependency graph output | Done | `dependency_adapter.py`, `tests/test_dependency_adapter.py` |
| #29 | Raw dependency tree artifact preserved | Done | `dependency_adapter.py` |
| #30 | Deterministic scanner unit coverage | Done | `tests/test_import_scanner.py`, `tests/test_config_scanner.py`, `tests/test_test_scanner.py`, `tests/test_surefire_parser.py` |
| #31 | Path-safety tests for context manager | Done | `tests/test_context_manager.py` |
| #32 | Copilot disabled behavior tested | Done | `tests/test_copilot_enricher.py` |
| #33 | Copilot failed behavior tested | Done | `tests/test_copilot_enricher.py` |
| #34 | Orchestrator integration wiring | Blocked | No orchestrator module in this workspace path |
| #35 | End-to-end integration test for analysis flow | Missing | no integration test currently |
| #36 | Artifact contract normalization and traceability doc | Partial | this document + code, pending status normalization items |

## Notes
- Typo fixed in mapping context: `#231` in `report_assembler.py` appears to refer to backlog item `#23`.
- This document is authoritative repository-local traceability for backlog items `#1` to `#36` as currently implemented.

## Planner Handoff Contract

Analysis Agent to Planner artifact contract is documented in `docs/analysis-planner-handoff.md`.
