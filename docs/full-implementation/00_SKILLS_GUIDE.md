# V1 Full Implementation Skills Guide

Use the skills as future implementation guidance only. This folder does not implement product code.

## Required exploration pattern

- Start each implementation issue with `git status --short` and `git branch --show-current`.
- Use `graphify` before broad scans when `graphify-out/graph.json` exists.
- Confirm Graphify hints against actual source and tests before editing.
- Use explicit path staging only; the current worktree may contain unrelated deleted historical docs.

## Skill mapping

- `graphify` - required for architecture/dependency exploration before implementation planning.
- `to-issues` - primary issue-shaping skill used to split large V1 issues into implementation-ready slices.
- `test-discipline` - primary skill for most implementation files because every issue needs focused tests, regression gates, and safe reporting.
- `requesting-code-review` - recommended for security-sensitive issues: worker launch, approvals, model audit, context redaction, privileged actions, patch policy/application, rollback, and final reports.
- `subagent-driven-development` - optional only for future large implementation work such as full assistant, patch application, and multi-panel UI. Do not use it to implement from this documentation generation task.
- `triage` - optional for readiness review, dependency order, risk, and scope boundaries before publishing implementation tickets.
- `setup-matt-pocock-skills` - use only if local issue-tracker or skill instructions are missing or unreadable.

## Recommended default per issue

- Backend schema/service/API issues: `test-discipline` plus `graphify`.
- Security, execution, approval, action, redaction, and patch issues: `test-discipline` plus `requesting-code-review`.
- UI panel issues: `test-discipline` plus `graphify`; add `requesting-code-review` for panels that approve or execute actions.
- Large cross-cutting future implementation: optionally use `subagent-driven-development` after reading its local skill instructions.

## Per-issue recommendation rule

Every issue file must list `test-discipline` as required. Add optional `graphify` for code navigation, optional `requesting-code-review` for execution/security/model/redaction/action/patch/proof work, optional `triage` for unclear dependency or risk boundaries, and optional `to-issues` only when a STOP split marker is present.
