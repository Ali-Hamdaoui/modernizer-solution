# Modernizer Solution

Migration Factory / Modernizer PoC.

This repository contains the first skeleton for a multi-agent modernization platform.

## Initial agents

- Analysis Agent
- Build Agent
- Planning Agent
- Transformation Agent

## Initial development strategy

Each team member works on one agent branch:

- agents/analysis-agent
- agents/build-agent
- agents/planning-agent
- agents/transformation-agent

Shared contracts will be defined after team alignment.

## Build Agent

The Build Agent runs a Maven or Gradle Java/Spring Boot application when called
by another agent. If project detection, compilation, startup, dependency
resolution, or command execution fails, it writes a JSON error contract under
`migration_factory/contracts/build`.

## Transformation Agent

The Transformation Agent applies a migration plan YAML one unit at a time against
the modernized target workspace. After each unit it updates
`.migration/ledger.json`, pauses, and waits for the Build Agent to validate the
current unit through the same ledger file.
