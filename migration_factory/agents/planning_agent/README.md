# Planning Agent

Responsible for consuming the analysis output and producing the migration plan.

To be defined with the team:
- Inputs
- Outputs
- Migration unit format
- Dependencies on Analysis Agent
- Model/API usage
- Definition of Done

## Planning Assist Foundation

- Optional/fail-open only.
- No live Copilot SDK/MCP/network calls.
- Default config disables assist.

Manual validation:

1. `python -m compileall migration_factory`
2. `python -c "from migration_factory.agents.planning_agent.node import planning_node; print(planning_node({'run_id':'r1'}))"`
3. Confirm output includes `planning_assist_status='SKIPPED'` by default.
