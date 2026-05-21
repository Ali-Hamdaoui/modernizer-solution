# Copilot Documentation Agent

The first GitHub Copilot integration proof in AI Migration Factory is advisory documentation.
Copilot consumes completed run outputs after sandbox validation and writes human-readable migration documents. The deterministic orchestrator remains in control of analysis, planning, approval, transformation, build validation, test validation, and final status.

## Boundary

The documentation agent is intentionally limited:

- no legacy source mutation
- no sandbox source mutation
- no approval decision mutation
- no approved plan lock mutation
- no migration plan mutation
- no gate, blocker, or status override
- no production promotion
- no pull request creation
- no deployment

If documentation generation cannot read a required artifact, the orchestration result records a warning and does not weaken or override the migration result.

## Inputs

The agent reads deterministic artifacts from the run directory:

- `analysis/analysis_report.json`
- `planning/migration_plan.yaml`
- `approval/approval_decision.json`
- `approval/approved_plan_lock.json`
- `transformation/transformation_execution_plan.yaml`
- `workspaces/sandbox/.migration/ledger.json`
- `test/post_transform/test_report.json`
- `orchestration/orchestration_summary.json`
- `final/migration_report.json`

## Outputs

After successful full sandbox validation, the agent writes:

- `final/copilot_docs/migration_overview.md`
- `final/copilot_docs/technical_changes.md`
- `final/copilot_docs/validation_evidence.md`
- `final/copilot_docs/risks_and_warnings.md`
- `final/copilot_docs/copilot_review.md`

Each generated document contains a `Source Artifacts` section with the exact artifact paths used for that section.
When the optional CLI adapter is attempted, the agent also writes:

- `final/copilot_docs/input_manifest.json`
- `final/copilot_docs/copilot_cli_status.json`

## Orchestrator Integration

The hook runs from `finalize_orchestration_state` after `final/migration_report.json` and `final/migration_summary.md` exist. This proves Copilot can be part of the factory without controlling deterministic gates:

1. The orchestrator validates sandbox transform, build, and tests.
2. The final report is generated from deterministic artifacts.
3. The Copilot documentation agent reads those artifacts.
4. The agent writes documentation only.
5. Final artifact validation treats the documentation package as optional generated evidence.

The AI Hub descriptor is `modernizer-solution-ai-hub/agents/copilot-doc-agent.yaml`.

## Optional Copilot CLI Integration

The implementation keeps `finalize_orchestration_state` as the integration point and adds a Copilot CLI-backed adapter inside `migration_factory/agents/copilot_doc_agent/`. The hook still runs only after `_is_successful_full_sandbox_migration` returns true and after `generate_final_migration_report` has produced `final/migration_report.json` and `final/migration_summary.md`.

The adapter order should be:

1. Resolve documentation configuration from the AI Hub descriptor, environment overrides, and conservative defaults.
2. If Copilot CLI usage is disabled, keep the current internal documentation generator.
3. If enabled, verify the configured CLI exists by running `copilot --version` or the configured absolute command path.
4. Invoke the CLI with an explicit prompt and an artifact manifest.
5. Accept only writes under `final/copilot_docs/`.
6. If the CLI is missing, times out, exits nonzero, or writes an invalid package, record a warning and fall back to the current internal generator unless fallback is disabled.

The current internal generator should remain as the deterministic fallback. Copilot CLI output is better suited as richer advisory prose, but the factory should not depend on a local interactive tool being installed or authenticated to complete an already-successful migration run.

## Configuration

Add these keys to `modernizer-solution-ai-hub/agents/copilot-doc-agent.yaml`:

```yaml
enabled: true
provider: github_copilot
mode: documentation_only
adapter: copilot_cli
fallback_adapter: local_documentation_agent
trigger_phase: post_final_report
cli:
  enabled: false
  command: copilot
  timeout_seconds: 180
  working_directory: run_dir
  output_directory: final/copilot_docs
```

Environment overrides should be narrow and explicit:

- `AI_MIGRATION_COPILOT_DOCS_ENABLED=true|false`
- `AI_MIGRATION_COPILOT_CLI_ENABLED=true|false`
- `AI_MIGRATION_COPILOT_CLI_PATH=C:\Users\abdelilah.mortaki\AppData\Roaming\npm\copilot.cmd`
- `AI_MIGRATION_COPILOT_DOCS_TIMEOUT_SECONDS=180`
- `AI_MIGRATION_COPILOT_DOCS_FALLBACK_ENABLED=true|false`

Default behavior should be disabled for live CLI use and enabled for local fallback documentation. This preserves current test behavior and avoids unexpectedly invoking a user-scoped external command during unattended runs.

## Command Shape

The implementation should pass Copilot a single bounded prompt through stdin and avoid shell interpolation. Use `subprocess.run([...], input=prompt, cwd=run_dir, timeout=timeout_seconds, capture_output=True, text=True)` with an argument list, not a composed shell command.

Recommended command:

```text
copilot --version
copilot
```

The prompt should instruct Copilot to read only the artifact paths listed in a generated manifest, write exactly the expected Markdown files under `final/copilot_docs/`, and not modify any other file. If the installed CLI later exposes a stable non-interactive subcommand, replace the second command with that explicit subcommand while keeping the same adapter boundary.

Generate a manifest such as `final/copilot_docs/input_manifest.json` before invocation:

```json
{
  "run_id": "shoppoc-full-orch-pc-java17-002",
  "output_dir": "final/copilot_docs",
  "required_outputs": [
    "migration_overview.md",
    "technical_changes.md",
    "validation_evidence.md",
    "risks_and_warnings.md",
    "copilot_review.md"
  ],
  "read_only_artifacts": {
    "analysis_report": "analysis/analysis_report.json",
    "migration_plan": "planning/migration_plan.yaml",
    "approval_decision": "approval/approval_decision.json",
    "approved_plan_lock": "approval/approved_plan_lock.json",
    "transformation_execution_plan": "transformation/transformation_execution_plan.yaml",
    "migration_ledger": "workspaces/sandbox/.migration/ledger.json",
    "post_transform_test_report": "test/post_transform/test_report.json",
    "orchestration_summary": "orchestration/orchestration_summary.json",
    "final_migration_report": "final/migration_report.json"
  }
}
```

## Failure Handling

Copilot documentation is optional evidence, so failures should not change `orchestration_status`, `final_status`, approval state, blockers, migration plan, or source files.

- Missing CLI: add warning `copilot documentation CLI unavailable; using local fallback`.
- Timeout: terminate the process, record stdout/stderr snippets in `final/copilot_docs/copilot_cli_status.json`, and use fallback.
- Nonzero exit: record exit code and bounded stdout/stderr, then use fallback by default.
- Invalid output package: delete only invalid files created under `final/copilot_docs/`, record a warning, and use fallback.
- Fallback disabled: record a warning and return no Copilot docs refs; do not fail the migration.

The status artifact includes provider, adapter, command path, version result, timeout, exit code, bounded stdout/stderr previews, fallback status, warnings, and generated artifact refs. It does not include secrets, full prompts containing source code, or unbounded CLI output.

## Security Boundaries

The Copilot CLI adapter must enforce the same documentation-only boundary as the current local generator:

- Read only from the required run artifacts and final report inputs.
- Write only under `run_dir/final/copilot_docs/`.
- Never write to the legacy app, sandbox workspace, approval directory, planning directory, transformation directory, migration ledger, or final migration report.
- Never mutate `approval_decision.json`, `approved_plan_lock.json`, `migration_plan.yaml`, `orchestration_summary.json`, `migration_report.json`, or `migration_summary.md`.
- Never create PRs, deployments, promotion records, commits, or approval decisions.
- Resolve paths with `Path.resolve()` and reject any output path outside `final/copilot_docs/`.
- Snapshot protected artifact bytes before CLI invocation and compare after invocation in tests.

## Test Coverage

The narrow tests around `tests/test_final_report.py` and the Copilot doc agent cover:

- CLI disabled uses the current internal generator and preserves existing artifact refs.
- CLI enabled with missing command records a warning and falls back to internal docs.
- CLI enabled with timeout records warning/status and falls back.
- CLI enabled with nonzero exit records warning/status and falls back.
- CLI success writes only expected files under `final/copilot_docs/` and records CLI artifact refs plus status.
- CLI attempt to write outside `final/copilot_docs/` is rejected and falls back.
- Protected artifacts and legacy/sandbox source bytes are unchanged after CLI execution.
- Copilot docs still run only after successful sandbox validation and final report generation.

No full orchestration test is needed for the first implementation. Mock the subprocess boundary and run the narrow final-report/doc-agent tests.
