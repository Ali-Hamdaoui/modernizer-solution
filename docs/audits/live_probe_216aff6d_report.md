# Live Probe Report - 216aff6d5bd24edb874a45db60a3f8ef

## Sandbox Path
- `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\workspaces\sandbox`

## Database Path
- Primary V2 Control Tower DB: `C:\Users\ilyas.abarbach\Documents\modernizer-solution\.control-tower-dev\control_tower.sqlite3`
- Job record table: `v2_migration_jobs`
- Related tables used here: `v2_job_events`, `v2_stage_commands`, `v2_repair_strategy_packets`, `v2_resume_commands`, `v2_phase_gates`

## Job Record
- `job_id`: `216aff6d5bd24edb874a45db60a3f8ef`
- `setup_id`: `919d593d8f084fccafbd584240cb501a`
- `pipeline_id`: `springboot-216-to-356-java21-three-stage`
- `status`: `created`
- `stage_chain_json`: Stage 1 queued, Stage 2 pending, Stage 3 pending

## Stage 1 Runtime Evidence
- Stage 1 command record is in `v2_stage_commands`
- `command_id`: `5048228ad83045f1a6ebb54b43db789a`
- `cwd`: `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\workspaces\sandbox`
- Stage 1 build result: `BUILD_FAILED_IN_SANDBOX`

## Artifact Paths
- `orchestration_summary`: `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\orchestration\orchestration_summary.json`
- `phase2_log`: `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\logs\phase2_transform.log`
- `migration_ledger`: `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\workspaces\sandbox\.migration\ledger.json`
- `assessment_report`: `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\assessment\assessment_report.json`
- `assessment_summary`: `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\assessment\assessment_summary.md`
- `analysis_report`: `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\analysis\analysis_report.json`
- `build_error_contract`: `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\build\build-error-20260704-012441-compilation_error.json`
- `runtime_contract`: `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\analysis\runtime_contract.json`

## Build Error Contract
- Present: yes
- Linked from `workspaces/sandbox/.migration/ledger.json` as `error_contract_path`
- Root cause in contract: Java compilation failure
- Concrete compile blockers:
  - `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\workspaces\sandbox\src\main\java\com\total\corp\common\service\base\SearchService.java:27`
  - `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\workspaces\sandbox\src\main\java\com\total\corp\common\dto\DTOHelpers.java:29`

## Test Report and Agent Log
- `test_report`: present in analysis read-only workspace, not in sandbox
  - `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\analysis\readonly-workspace\target\surefire-reports`
- `test_agent_log`: no standalone file found
- Likely explanation: test evidence is split, and the diagnosis packet did not link the existing test report into the failure summary

## Java Evidence for PowerMock / Constructor-Mocking Family
- Actual PowerMock source file found:
  - `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\analysis\readonly-workspace\src\test\java\com\total\corp\bus\AzureBusTopicTest.java`
- Relevant lines:
  - `33: @RunWith(PowerMockRunner.class)`
  - `34: @PrepareForTest(TopicClient.class)`
  - `44: final TopicClient topicClient = PowerMockito.mock(TopicClient.class);`
  - `63: final ServiceBusTopic busTopic = PowerMockito.spy(new ServiceBusTopic());`
  - `67: PowerMockito.when(busTopic.getTopicClient()).thenReturn(topicClient);`
- Literal `whenNew`:
  - Not found in the job artifacts I searched

## pom.xml Used By The Sandbox Build
- `C:\Users\ilyas.abarbach\Documents\modernized-app\.migration\runs\v2-216aff6d\workspaces\sandbox\pom.xml`
- Runtime contract also names `pom.xml` as the primary pom

## Diagnosis
- This looks like a real build failure plus an evidence-binding gap.
- Real blocker: sandbox compile failure in `SearchService.java` and `DTOHelpers.java`
- Evidence gap: the diagnosis packet says `build_error_contract`, `test_report`, `test_agent_log`, and `pom_xml` are missing, but the build error contract and pom.xml do exist, and the test report exists in the read-only workspace.
- The PowerMock constructor-mocking classification is not backed by a literal `whenNew` match in the runtime files I found.
- So the UI diagnosis is likely over-attributing the failure to the PowerMock family while missing the actual compile blockers and some linked artifact refs.

## Recommended Next Action
- Re-link the existing artifacts into the diagnosis view first:
  - build error contract
  - sandbox pom.xml
  - analysis readonly-workspace test report
- Then re-run diagnosis on the real compile errors in `SearchService.java:27` and `DTOHelpers.java:29`
- Treat the PowerMock family as advisory context only until a literal blocker trace is present
