REQUIRED_ANALYSIS_INPUT_ARTIFACTS: tuple[str, ...] = (
    "analysis_report.json",
    "dependency_graph.json",
    "test_inventory.json",
    "analysis_summary.md",
)

OPTIONAL_ANALYSIS_INPUT_ARTIFACTS: tuple[str, ...] = (
    "config_inventory.json",
    "rewrite_preview.json",
    "rewrite_plugin_plan.json",
    "rewrite_impact_summary.json",
    "rewrite_dry_run.patch",
    "copilot_assist.json",
)

PLANNING_OUTPUT_ARTIFACTS: tuple[str, ...] = (
    "migration_plan.yaml",
    "migration_units.yaml",
    "plan_summary.md",
    "approval_request.json",
    "plan_validation_report.json",
    "copilot_assist.json",
)
