# V1 Full Implementation References

Web research was available and used. Official/primary sources only were preferred.

| source title | URL | why it matters | issues referenced |
|---|---|---|---|
| OpenAI Developers - Custom instructions with AGENTS.md | https://developers.openai.com/codex/guides/agents-md | Confirms AGENTS.md is the project guidance mechanism Codex should discover and apply. | V1-00A, V1-01, all implementation files |
| Microsoft Learn - Structured outputs for Azure OpenAI | https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs | Supports JSON Schema-bound planner/reviewer/repair outputs and fake-provider parity. | V1-09, V1-10, V1-12B, V1-13, V1-14C |
| OpenAI API - Structured model outputs | https://developers.openai.com/api/docs/guides/structured-outputs | Reinforces schema-adherent model outputs as a contract for proposal/audit flows. | V1-10, V1-12B, V1-14C, V1-16A, V1-16B |
| LangGraph - Persistence | https://docs.langchain.com/oss/python/langgraph/persistence | Persistence is relevant for resumable orchestration and approval recovery. | V1-07A, V1-07B, V1-08A |
| LangGraph - Interrupts | https://docs.langchain.com/oss/python/langgraph/interrupts | Explains human-in-the-loop interruption/resume concepts used by approval issues. | V1-07A, V1-07B, V1-12C, V1-13 |
| Apache Maven - Guide to Using Toolchains | https://maven.apache.org/guides/mini/guide-using-toolchains.html | Explains JDK selection independent of Maven runtime; informs JDK readiness and typed Maven operations. | V1-05, V1-06B1, V1-08B, V1-15D, V1-17D |
| Spring Blog - Spring Boot 2.7.18 available now | https://spring.io/blog/2023/11/23/spring-boot-2-7-18-available-now | Confirms the Stage 1 target release exists and is a maintenance release. | V1-02 |
| Spring Blog - Spring Boot 3.5.6 available now | https://spring.io/blog/2025/09/18/spring-boot-3-5-6-available-now | Confirms the V1 Stage 2/3 target release exists. | V1-02 |
| Spring Boot 3.5 Release Notes | https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.5-Release-Notes | Provides official upgrade context for the Boot 3.5 target family. | V1-02, V1-08A, V1-19A |
| FastAPI - Lifespan Events | https://fastapi.tiangolo.com/advanced/events/ | Relevant for FastAPI resource setup/teardown and app wiring tests. | V1-04, V1-09, V1-16B, V1-19C |
| sse-starlette - EventSourceResponse | https://github.com/sysid/sse-starlette | Primary package docs for Starlette SSE response behavior used by event/assistant streams. | V1-00C, V1-16B, V1-18F |
| Next.js - Server and Client Components | https://nextjs.org/docs/app/getting-started/server-and-client-components | Guides App Router split between server data loading and client interactivity. | V1-18A through V1-18G |
| Next.js - Fetching Data | https://nextjs.org/docs/app/getting-started/fetching-data | Guides App Router data fetching and streaming expectations for cockpit pages. | V1-18A through V1-18G |

Local canonical sources:

- `AGENTS.md`
- `docs/CODEXSUGGESTING.md`
- `docs/ai_migration_control_tower_v1_issues.md`
- Current source and tests under `migration_factory/control_tower/`, `migration_factory/orchestrator/`, `tests/control_tower/`, `web/control-tower/`, and `modernizer-solution-ai-hub/`.
- Local skills under `.agents/skills/`.
