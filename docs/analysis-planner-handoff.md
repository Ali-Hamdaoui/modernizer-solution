# Analysis Agent to Planner Handoff Contract

This document defines the artifact contract produced by Analysis Agent and consumed by Planner.

## Required artifacts

| File | Purpose | Producer | Consumer | Status values |
|---|---|---|---|---|
| `analysis_report.json` | Canonical machine-readable analysis result and scan metadata. | Analysis Agent | Planner, orchestrator, reporting tools | Overall/status fields are producer-defined; enrichment statuses must use `USED | SKIPPED | FAILED` where applicable. |
| `dependency_graph.json` | Structured dependency graph for migration planning and risk analysis. | Analysis Agent | Planner | Producer-defined graph status; failures represented in artifact payload. |
| `test_inventory.json` | Test inventory and summary used for migration confidence planning. | Analysis Agent | Planner | Producer-defined scan status. |
| `analysis_summary.md` | Human-readable summary for operators and planner context. | Analysis Agent | Planner, humans | N/A |

## Optional artifacts

| File | Purpose | Producer | Consumer | Status values |
|---|---|---|---|---|
| `config_inventory.json` | Configuration keys and migration-relevant config posture. | Analysis Agent | Planner | Producer-defined scan status. |
| `rewrite_preview.json` | OpenRewrite dry-run preview output and summary. | Analysis Agent | Planner (optional read), humans | `USED | SKIPPED | FAILED` |
| `rewrite_dry_run.patch` | OpenRewrite dry-run patch output generated from catalog profile. | Analysis Agent | Planner (optional read), humans | Implicit via rewrite status artifact fields. |
| `rewrite_plugin_plan.json` | Catalog-driven plugin/recipe invocation plan used for dry-run command construction. | Analysis Agent | Planner (optional read) | `USED | SKIPPED | FAILED` |
| `rewrite_impact_summary.json` | Normalized migration impact classification derived from rewrite dry-run output. | Analysis Agent | Planner (optional read) | Rewrite status: `USED | SKIPPED | FAILED`; impact: `LOW | MEDIUM | HIGH | BLOCKED | UNKNOWN` |
| `copilot_assist.json` | Optional AI-assist output; fail-open enrichment content only. | Analysis Agent | Planner (optional read), humans | `USED | SKIPPED | FAILED` |

## Compatibility statement

Planner's prior contract is satisfied by the current Analysis Agent output set consisting of:
1. Required artifacts listed above.
2. Legacy optional artifacts plus newly available optional rewrite planning/impact artifacts.

No previously required Planner input artifact has been removed.

## Planner branch follow-up

Planner branch should add optional reads for:
1. `rewrite_plugin_plan.json`
2. `rewrite_impact_summary.json`

Planner must treat both as optional and continue operating when either is absent or `SKIPPED`/`FAILED`.

## Safety and execution constraints

Analysis Agent guarantees:
1. It never writes to a real project `pom.xml`.
2. It never executes OpenRewrite apply goals (`rewrite:run`, `run`, `rewrite:runNoFork`, `runNoFork`).
3. OpenRewrite execution is limited to dry-run/discovery behavior and catalog-driven command inputs.

Catalog profile example: docs/examples/analysis-openrewrite-catalog.example.yaml
