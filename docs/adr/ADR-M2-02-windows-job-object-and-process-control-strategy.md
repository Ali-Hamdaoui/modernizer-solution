# ADR-M2-02 Windows Job Object and process-control strategy

Status: Proposed for review

Date: 2026-06-10

## Context

The M2 plan requires Windows Job Object process control. Repository inspection did not find a reusable M0 Windows Job Object implementation or tests.

Found evidence:

- PRD and M2 plan text describe Windows Job Object requirements.
- Existing code uses `subprocess` in legacy agent, Copilot, repair, and TUI boundaries.

Not found:

- `CreateJobObject`.
- `AssignProcessToJobObject`.
- `TerminateJobObject`.
- Suspended process creation helper.
- Job Object test suite.
- Reusable M0 process-control package.

## Decision

M2-00 records process-control evidence as missing.

M2-06 and M2-08 must not assume an approved reusable M0 implementation exists unless reviewers provide it before coding.

The preferred M2 runtime strategy remains a Windows Job Object owned by the controller/API process.

## Required M2 behavior

- Create worker suspended.
- Assign worker to Job Object before resume.
- Apply `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
- Disallow breakaway.
- Make Job Object handle non-inheritable.
- Keep the Job Object handle owned by the controller.
- Do not persist raw Windows handles.
- Persist only process identity and launch evidence such as `process_control_id`, `worker_pid`, worker process creation time or nonce, launch attempt, and diagnostic metadata.

## Blocked or unverified

- No M0 implementation evidence is present in this repository.
- No Windows Job Object tests are present.
- Reviewer must decide whether M2 creates new process-control code or imports an external/previously approved M0 artifact.

## Consequences

M2-06 and M2-08 need explicit reviewer approval before process-control implementation begins.

M2-13 acceptance must include Windows process-tree tests proving assignment-before-resume, non-inherited handle behavior, process-tree termination, timeout, and cancellation.
