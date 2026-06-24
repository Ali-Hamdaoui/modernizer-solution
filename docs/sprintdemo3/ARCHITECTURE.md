# DEMO3 Architecture

## Normal Controlled Pipeline

```text
Create job
-> detect or confirm source_profile
-> select target_profile
-> backend validates source/target pair
-> Analysis Agent deterministic artifact
-> primary LLM reasoning
-> reviewer LLM validation
-> final Analysis Markdown artifact
-> stored checkpoint
-> user continue / request modification / stop
-> Planning Agent deterministic artifact
-> primary LLM reasoning
-> reviewer LLM validation
-> final Planning Markdown artifact
-> stored checkpoint
-> user continue / request modification / stop
-> required transformations only
-> Build Agent
-> Test Agent
-> stop at target profile
```

## Model Reviews Model Chain

```text
deterministic artifact
   |
   v
primary LLM reasoning
   |
   v
reviewer LLM validation
   |
   v
final Markdown artifact
   |
   v
stored checkpoint / next agent input
```

Reviewer LLM is mandatory for supported model-required outputs. Deterministic fallback can produce evidence but cannot satisfy a model-required reviewed artifact.

## Profile-Controlled Stage Progression

```text
detected source_profile
-> user confirm or override
-> backend validates source_profile + target_profile
-> stage plan includes only required stages
-> skipped stages are recorded and explained
-> pipeline stops when target_profile is reached
```

Example:

```text
source_profile = spring-boot-2
target_profile = spring-boot-3
-> migrate to Spring Boot 3
-> stop at Spring Boot 3
-> do not continue to Spring Boot 4
```

## Build/Test Repair Agent Loop

```text
Build Agent or Test Agent fails
-> capture build/test logs, compiler/test output, changed files, prior artifacts
-> deterministic failure artifact
-> Primary Repair LLM proposes root cause and diff
-> Reviewer LLM reviews reasoning and diff
-> final proposal artifact
-> user approves / rejects / requests another review
```

Approval:

```text
exact reviewed diff approved
-> backend validates checksum and policy
-> backend applies exact diff in sandbox
-> rerun Build Agent or Test Agent
-> proof or another Repair Agent cycle
```

Rejection:

```text
reject
-> status = STOPPED_BY_USER
-> no patch applied
-> rejection reason stored
-> artifacts downloadable
```

Another review:

```text
request another review with comments
-> original context + previous diff + previous reasoning + reviewer notes + user comments + current repo state
-> new Repair Agent proposal
-> new reviewer result
-> user decides again
```

## Authority Boundaries

| Actor | May do | Must not do |
|---|---|---|
| Chatbot | Explain, summarize, classify intent, draft typed actions, ask questions | Execute, approve, choose paths, supply argv/env, mutate source, apply patches, skip stages, override proof |
| Human | Continue, stop, accept, reject, approve, request modifications, request another review | Provide executable authority such as paths, raw commands, argv, env |
| Primary LLM | Reason and propose structured artifacts | Execute, approve, apply, choose sandbox, manufacture proof |
| Reviewer LLM | Review another model's output and exact proposed diff | Approve execution or bypass backend/human |
| Backend | Validate, persist, bind checksums, execute in sandbox, roll back, prove | Trust unreviewed model output or frontend execution details |

## Implementation Reuse Points

- FastAPI backend: `migration_factory/control_tower/adapters/fastapi/`
- Agents: `migration_factory/agents/`
- Stage progression and runner: `v2_stage_progression.py`, `v2_orchestrator_runner.py`
- Gates and artifacts: `v2_gate_action_service.py`, `v2_phase_gate_service.py`, `v2_gate_artifact_resolver.py`, artifact revision schema/repositories
- Reviewer: `v2_reviewer_service.py`
- Repair: `v2_repair_flow.py`, `v2_repair_gate_service.py`, `migration_factory/repair_loop/`
- Persistence: `migration_factory/control_tower/infrastructure/sqlite/`
