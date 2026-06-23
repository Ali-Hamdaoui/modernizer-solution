# AI Migration Control Tower — Full Handoff

**Created:** 2026-06-23  
**Audience:** next ChatGPT/Codex session or senior engineer continuing the AI Migration Control Tower work.  
**Primary focus for next session:** use the successful Stage 4 runtime failure to improve the Spring Boot 4 migration system, especially Jackson 2 → Jackson 3 handling and repair diagnostics.

---

## 1. Executive Summary

The system is now on the merged `before` branch with the Stage 4 / Spring Boot 4 integration from PR #134. The four-stage pipeline works end-to-end at the Control Tower level:

```text
Stage 1: Spring Boot 2.1.6 → 2.7 / Java 11
Stage 2: Spring Boot 2.7 → 3.5 / Java 17
Stage 3: Spring Boot 3.5 / Java 17 → Java 21
Stage 4: Spring Boot 3.5 / Java 21 → Spring Boot 4 / Java 21
```

The previous bug where Stage 4 stayed pending was fixed locally on `before` by commit:

```text
1e06b32 fix(f15): persist stage output before stage 4 progression
```

A fresh runtime migration then proved that Stage 4 now starts automatically. It failed in Stage 4 because the migrated Java application did not compile after the Boot 4/Jackson migration. This is desirable for the next phase: the platform correctly reached Stage 4 and surfaced a real application-level modernization problem.

Current key state:

```text
branch: before
latest local fix HEAD: 1e06b32
pushed after 1e06b32: no, unless user later pushes outside this chat
real migration job that reached Stage 4: 3e60f3075b91480690a13873eabf3bf2
Stage 4 status: FAILED
Stage 4 profile: springboot-3.5-java21-to-4.0-java21
Stage 4 final_status: FALLBACK_REPAIR_PLAN
main compile failure: cannot find symbol: class JsonNode
failing Java type: com.total.corp.services.juneau.ProposalExternalFacade
```

The next session should not treat this as a Control Tower orchestration failure. Treat it as a successful governed Stage 4 execution that revealed a real Boot 4/Jackson compatibility blocker.

---

## 2. Important Artifacts, Branches, PRs, and Commits

### Repository

```text
C:\Users\abdelilah.mortaki\Desktop\modernizer-solution
```

### Main branch after merge

```text
before
```

### PR already merged

```text
PR #134
https://github.com/Ali-Hamdaoui/modernizer-solution/pull/134
```

PR #134 merged the `stable` branch into `before` and introduced:

- governed Stage 4 / Spring Boot 4 support;
- Boot 4 AI Hub profile and OpenRewrite catalog;
- migration `0046_v2_stage4_support.sql`;
- artifact-backed final report / PDF routes and cockpit controls;
- F15-safe tests and cockpit report UI.

### Merge commit after PR #134

```text
cfbf03c6ade654a47d4d391bb33c154c05ec4188
Merge pull request #134 from Ali-Hamdaoui/stable
```

### Stage 4 progression hotfix after PR #134

```text
1e06b32
fix(f15): persist stage output before stage 4 progression
```

Reported changed files in that hotfix:

```text
migration_factory/control_tower/adapters/fastapi/app.py
migration_factory/control_tower/application/v2_orchestrator_runner.py
migration_factory/control_tower/application/v2_stage_progression.py
migration_factory/control_tower/infrastructure/sqlite/v2_artifact_revision_repository.py
tests/control_tower/test_v2_stage_progression.py
tests/control_tower/test_v2_orchestrator_runner.py
```

### Key docs now in repo

```text
docs/STABLE_INTEGRATION_IMPLEMENTATION_PLAYBOOK.md
```

Audit reports were generated during the work but intentionally not committed unless the user later changes that decision:

```text
docs/STABLE_INTEGRATION_AUDIT_REPORT.md
docs/STABLE_INTEGRATION_RERUN_AUDIT_REPORT.md
```

---

## 3. How We Got Here

### 3.1 Original conflict problem

There were two divergent lines of work:

```text
before
```

contained the advanced F15 governed migration cockpit: phase gates, artifact revisions, accepted revision enforcement, repair governance, assistant safety, POM governance, backend-owned stage progression, and cockpit safety panels.

```text
V2IMPROVMENT
```

contained useful donor features: Stage 4 / Spring Boot 4, final report generation, PDF download, and report cockpit controls, but it was behind the advanced governance branch and could not be merged directly without deleting/regressing many F15 systems.

The integration strategy was:

```text
stable = before + manually reconstructed safe donor features - donor regressions
```

No wholesale merge or cherry-pick of `V2IMPROVMENT`.

### 3.2 Stable implementation and audit cycle

Codex implemented the stable integration from `before@fad82fdf...`, then audits found P0 blockers:

- Stage 4 was not bound to accepted Stage 3 revision/checksum.
- Terminal completion bypassed final governance.
- Report artifacts were not persisted.
- Download reconstructed unsafe filesystem paths.
- Backend focused tests failed.

Codex fixed those blockers, then reran focused verification. Final stable readiness before PR:

```text
backend focused: 243 passed
frontend focused: 82 passed
typecheck: pass
build: pass
diff checks: pass
```

PR #134 was pushed and merged.

### 3.3 Local before updated and DB cleaned

After PR #134 merge, local `before` was updated successfully:

```powershell
git fetch --all --prune
git switch before
git pull --ff-only origin before
```

`before` became:

```text
cfbf03c6ade654a47d4d391bb33c154c05ec4188
```

Local runtime DB and stale generated files were cleaned carefully, not using broad `git clean -fdX`:

```text
.control-tower-dev
web/control-tower/.control-tower-dev
.tmp-tests
.pytest_cache
web/control-tower/.next
web/control-tower/tsconfig.tsbuildinfo
_db-backup-before-fad82-20260619-102048
_runtime-backup-before-clean-20260619-103443
```

Backend focused tests were rerun with `py` because `python` resolves to the Microsoft Store alias on this machine:

```powershell
py -m pytest --cache-clear -q `
  tests/control_tower/test_sqlite_migrations.py `
  tests/control_tower/test_v2_phase_gate_migration.py `
  tests/control_tower/test_v2_artifact_revision_migration.py `
  tests/control_tower/test_v2_job_service.py `
  tests/control_tower/test_v2_setup_service.py `
  tests/control_tower/test_v2_stage_progression.py `
  tests/control_tower/test_v2_stage_progression_policy.py `
  tests/control_tower/test_v2_orchestrator_runner.py `
  tests/control_tower/test_v2_worker_stage.py `
  tests/control_tower/test_v2_cockpit_events.py `
  tests/control_tower/test_v2_final_report_service.py `
  tests/control_tower/test_v2_e2e.py `
  tests/agents/planning_agent/test_boot4_stage_profile.py `
  tests/reporting/test_pdf_writer.py `
  tests/test_final_report.py
```

Result:

```text
243 passed, 5 warnings
```

---

## 4. Stage 4 Pending Bug and Fix

### 4.1 Runtime symptom

A migration job reached Stage 3, but Stage 4 remained pending.

Job:

```text
475a6d05857044a99c91c21e9d5071a6
```

The cockpit showed:

```text
Stage 1 completed
Stage 2 completed
Stage 3 completed
Stage 4 pending
```

Events showed Stage 3 completed and wrote sandbox artifacts, but DB inspection showed:

```text
v2_stage_commands:
stage 1 status = manifest_ready, result_json = null
stage 2 status = manifest_ready, result_json = null
stage 3 status = manifest_ready, result_json = null

v2_artifact_revisions rows = 0
artifacts rows = 0
```

### 4.2 Manual safe progress route

The safe route was:

```text
POST /v1/v2/jobs/{job_id}/stages/progress
```

OpenAPI showed request schema:

```json
{
  "setup_id": "...",
  "current_stage": 3
}
```

No `idempotency_key` allowed; schema had `additionalProperties=false`.

Mutation guards required:

```text
Origin: http://127.0.0.1:3000
Referer: http://127.0.0.1:3000/
X-Control-Tower-Client: control-tower-frontend
Content-Type: application/json
```

The exact frontend client value was found in:

```text
web/control-tower/app/migrations/new/NewMigrationForm.tsx
web/control-tower/lib/controlTowerApi.ts
```

### 4.3 Root cause traceback

The safe progress POST reached backend logic but crashed:

```text
AttributeError: 'V2StageCommandRecord' object has no attribute 'output_root_dir'
```

Traceback pointed to:

```text
migration_factory/control_tower/adapters/fastapi/app.py:2916
resolved_sandbox_path = latest.output_root_dir or latest.sandbox_root_dir
```

That route still expected old command-record fields. The actual command record only has fields such as:

```text
command_id
job_id
stage_index
manifest_checksum
argv_json
env_json
status
created_at
updated_at
result_json
gate_id
decision_id
```

### 4.4 Hotfix implemented by Codex

Codex fixed two independent bugs:

1. Removed broken `output_root_dir` / `sandbox_root_dir` resolution from `app.py`. The route now delegates to governed progression and returns controlled errors instead of 500.
2. Added accepted `stage_output` artifact revision persistence before queueing next stage. `_save_stage_output_revision()` is called in `_auto_queue_next_stage()` before `service.queue_next_stage()`.

Reported tests after hotfix:

```text
tests/control_tower/test_v2_stage_progression.py ............. (13)
tests/control_tower/test_v2_stage_progression_policy.py .. (2)
tests/control_tower/test_v2_orchestrator_runner.py ................................ (40)
tests/control_tower/test_v2_e2e.py ..... (5)
tests/control_tower/test_v2_cockpit_events.py ................... (19)
tests/control_tower/test_v2_final_report_service.py ........... (12)

91 passed
Second batch: 161 passed
Frontend: typecheck + build OK
```

This hotfix was committed locally as:

```text
1e06b32
```

Do not assume it is pushed. Verify with:

```powershell
git status --short
git log --oneline -n 5
git branch --show-current
git remote -v
git status -sb
```

If not pushed, next session must decide whether to push directly to `before` or open a hotfix PR branch.

---

## 5. Runtime Verification After Hotfix

A fresh migration was run after the Stage 4 progression hotfix.

New runtime job:

```text
3e60f3075b91480690a13873eabf3bf2
```

Cockpit showed:

```text
Stage 1 completed
Stage 2 completed
Stage 3 completed
Stage 4 failed
```

This confirms Stage 4 auto-progress works now.

Stage 4 event excerpt from DB:

```text
sequence 500: artifact_written — Artifact written: sandbox
sequence 507: artifact_written — Stage sandbox output registered
sequence 508: sandbox_transform_failed — Sandbox transform failed: BUILD_FAILED_IN_SANDBOX
sequence 509: build_failed — Sandbox build failed: BUILD_FAILED_IN_SANDBOX
sequence 513: build_failed — Build result: BUILD_FAILED_IN_SANDBOX
sequence 515: transform_failed — Transform/build failed: FALLBACK_REPAIR_PLAN
sequence 517: stage_failed — Stage 4 real orchestrator completed with terminal failure: FALLBACK_REPAIR_PLAN
```

Important observation from one DB script:

```text
v2_stage_commands still showed status=manifest_ready and result_json=false for all stages.
```

This may mean stage command rows are not being updated even though events and artifact revisions now drive progression. Since Stage 4 did auto-start, the new accepted revision persistence path works at least enough for progression. However, the next session should verify `v2_artifact_revisions` for job `3e60...` because the pasted script did not print artifact revisions after the final successful auto-progress run.

Suggested DB check:

```powershell
$env:JOB = "3e60f3075b91480690a13873eabf3bf2"

@'
import sqlite3, os
DB = r".control-tower-dev\control_tower.sqlite3"
JOB = os.environ["JOB"]
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

print("artifact revisions:")
for r in con.execute(
    "select stage_index, revision_kind, revision_status, accepted_at_gate_id, superseded_by_revision_id, created_at from v2_artifact_revisions where job_id=? order by stage_index, revision_order",
    (JOB,),
):
    print(dict(r))

print("artifacts:")
for r in con.execute(
    "select artifact_id, job_id, stage, kind, checksum_sha256, relative_path, created_at from artifacts where job_id=? order by created_at",
    (JOB,),
):
    print(dict(r))
'@ | py -
```

---

## 6. Stage 4 Failure — Java / Jackson Problem

### 6.1 What failed

Stage 4 ran the Boot 4 profile:

```text
springboot-3.5-java21-to-4.0-java21
```

and failed in sandbox build:

```text
Build result kind: compilation_error
Build message: Java application failed to compile
Build status: BUILD_FAILED_IN_SANDBOX
final_status: FALLBACK_REPAIR_PLAN
repair_loop_status: FALLBACK_REPAIR_PLAN
copilot_invocation_status: INVALID_RESPONSE
```

The repeated Java compiler error:

```text
cannot find symbol
symbol: class JsonNode
location: interface com.total.corp.services.juneau.ProposalExternalFacade
```

This is a real app-level modernization failure, not a Control Tower orchestration failure.

### 6.2 Most likely root cause

This is almost certainly related to Jackson migration under Spring Boot 4.

Official references:

- Spring Boot 4 migration guide says Boot 4 now uses Jackson 3 as preferred JSON library, and Jackson 3 changes group IDs/packages from `com.fasterxml.jackson` to `tools.jackson`, except annotations.
  - https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide
- Spring blog says Boot 4 applications are encouraged to migrate to Jackson 3, while temporary Jackson 2 support can be used if needed.
  - https://spring.io/blog/2025/10/07/introducing-jackson-3-support-in-spring
- OpenRewrite has `org.openrewrite.java.jackson.UpgradeJackson_2_3`, which handles package changes, dependency updates, class/method renames.
  - https://docs.openrewrite.org/recipes/java/jackson/upgradejackson_2_3

Most likely causes:

```text
A. ProposalExternalFacade uses JsonNode without an import after transformation.
B. It still imports com.fasterxml.jackson.databind.JsonNode, but Stage 4 dependencies expect tools.jackson.databind.JsonNode.
C. The POM lost jackson-databind / Spring Boot Jackson dependency after dependency cleanup.
D. The Stage 4 OpenRewrite catalog does not include the Jackson 2→3 migration recipes.
```

### 6.3 Next debugging commands

The next session should inspect the Stage 4 sandbox and POM.

Because `v2_stage_commands.result_json` was not useful, extract artifact payloads/events to locate the Stage 4 run folder:

```powershell
cd C:\Users\abdelilah.mortaki\Desktop\modernizer-solution
$env:JOB = "3e60f3075b91480690a13873eabf3bf2"

@'
import sqlite3, json, os
DB = r".control-tower-dev\control_tower.sqlite3"
JOB = os.environ["JOB"]

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

print("Stage 4 artifact events with payloads:")
for r in con.execute(
    '''
    select sequence, type, status, message, payload_json
    from v2_job_events
    where job_id=? and stage=4 and type='artifact_written'
    order by sequence
    ''',
    (JOB,),
):
    d = dict(r)
    print("\nSEQ", d["sequence"], d["message"])
    payload = d.get("payload_json")
    if payload:
        try:
            print(json.dumps(json.loads(payload), indent=2))
        except Exception:
            print(payload)
'@ | py -
```

Then locate the run folder:

```powershell
Get-ChildItem -Recurse -Directory -Path . -Filter "v2-3e60f307-s4" |
  Select-Object FullName
```

If that does not find it, search under the known modernized output root:

```powershell
Get-ChildItem C:\Users\abdelilah.mortaki\Desktop\modernized-v2-runs -Recurse -Directory -Filter "v2-3e60f307-s4" |
  Select-Object FullName
```

Once `$runDir` is found, locate sandbox:

```powershell
Get-ChildItem $runDir -Recurse -Directory |
  Where-Object { $_.Name -match "sandbox|modernized|candidate|workspaces" } |
  Select-Object FullName
```

Then inspect Java/POM:

```powershell
$sandboxPath = "<PASTE_STAGE4_SANDBOX_PATH_HERE>"

Get-ChildItem $sandboxPath -Recurse -File -Filter "ProposalExternalFacade.java" |
  Select-Object FullName

$facade = Get-ChildItem $sandboxPath -Recurse -File -Filter "ProposalExternalFacade.java" | Select-Object -First 1
Get-Content $facade.FullName -TotalCount 120

Get-ChildItem $sandboxPath -Recurse -File -Include *.java,*.xml |
  Select-String -Pattern "JsonNode|com.fasterxml.jackson.databind|tools.jackson.databind|jackson-databind|spring-boot-starter-json|spring-boot-jackson" |
  Select-Object Path, LineNumber, Line

$pom = Get-ChildItem $sandboxPath -Recurse -File -Filter "pom.xml" | Select-Object -First 1
Select-String -Path $pom.FullName `
  -Pattern "spring-boot-starter-json|spring-boot-starter-web|spring-boot-jackson|jackson-databind|tools.jackson|com.fasterxml.jackson" `
  -Context 2,2
```

### 6.4 Sandbox-only compile experiment

Do not change platform code first. Prove the likely Java fix in the sandbox.

If the failing file imports Jackson 2:

```powershell
$facade = Get-ChildItem $sandboxPath -Recurse -File -Filter "ProposalExternalFacade.java" | Select-Object -First 1
Copy-Item $facade.FullName "$($facade.FullName).bak"

(Get-Content $facade.FullName) `
  -replace "com\.fasterxml\.jackson\.databind\.JsonNode", "tools.jackson.databind.JsonNode" |
  Set-Content $facade.FullName

mvn -f $pom.FullName -DskipTests compile
```

If it uses `JsonNode` without import:

```powershell
$facade = Get-ChildItem $sandboxPath -Recurse -File -Filter "ProposalExternalFacade.java" | Select-Object -First 1
Copy-Item $facade.FullName "$($facade.FullName).bak"

$content = Get-Content $facade.FullName
$packageLineIndex = ($content | Select-String -Pattern "^package ").LineNumber

$newContent = @()
for ($i = 0; $i -lt $content.Count; $i++) {
  $newContent += $content[$i]
  if ($i -eq ($packageLineIndex - 1)) {
    $newContent += ""
    $newContent += "import tools.jackson.databind.JsonNode;"
  }
}

$newContent | Set-Content $facade.FullName
mvn -f $pom.FullName -DskipTests compile
```

If this compiles, the platform fix is likely to enhance the Stage 4 OpenRewrite catalog/profile with Jackson 2→3 recipes.

---

## 7. Next Product / Platform Work

The next work is not to “make Stage 4 pass” by hiding failures. The failure is valuable. The goal is to improve the system so it handles or explains this class of failure better.

### Recommended next Codex mission

1. Inspect Stage 4 sandbox.
2. Confirm whether `ProposalExternalFacade` is missing import, using old `com.fasterxml.jackson.databind.JsonNode`, or missing dependency.
3. If a manual sandbox edit proves Jackson 3 import/dependency fix, update:

```text
modernizer-solution-ai-hub/catalogs/openrewrite/springboot-3.5-java21-to-4.0-java21.yaml
modernizer-solution-ai-hub/profiles/springboot-3.5-java21-to-4.0-java21.yaml
tests/agents/planning_agent/test_boot4_stage_profile.py
tests/control_tower/test_v2_e2e.py
```

4. Add/verify OpenRewrite Jackson 2→3 recipes such as:

```text
org.openrewrite.java.jackson.UpgradeJackson_2_3
```

or subrecipes:

```text
UpgradeJackson_2_3_PackageChanges
UpgradeJackson_2_3_TypeChanges
UpgradeJackson_2_3_Dependencies
```

Use exact recipe names supported by the repo’s OpenRewrite version/catalog.

5. Improve failure diagnosis:
   - classify “cannot find symbol JsonNode” as `jackson3_migration_missing_type_or_dependency`;
   - surface a repair proposal: migrate imports to `tools.jackson.databind.JsonNode` or add temporary Jackson 2 support depending on chosen policy;
   - ensure Copilot invalid response still results in deterministic repair instructions.

6. Consider adding a deterministic fallback repair artifact for Boot 4 Jackson migration compile failures:
   - affected files,
   - missing symbol,
   - suggested imports/dependencies,
   - links to Jackson 3 migration docs,
   - whether compatibility mode is acceptable.

---

## 8. Current Risks / Things to Verify

1. **Hotfix 1e06b32 may not be pushed.**
   - Verify and push/open PR as required.
   - Do not assume remote `before` includes it.

2. **`web/control-tower/next-env.d.ts` was reported as modified after frontend build.**
   - Restore before committing:
     ```powershell
     git restore -- web\control-tower\next-env.d.ts
     git status --short
     ```

3. **Stage command rows may still show `manifest_ready` and `result_json=null`.**
   - Stage 4 auto-start proves progression now works, but verify whether the command state should also be updated.
   - If this is intentional/event-sourced, document it. If not, add a follow-up issue.

4. **`v2_artifact_revisions` after the successful auto-progress run was not pasted.**
   - Verify accepted Stage 3 `stage_output` and Stage 4 failure artifacts are present.

5. **Boot 4 failure is expected but now should drive platform improvement.**
   - Do not treat it as a failed Control Tower deliverable.
   - Treat it as evidence that Stage 4 is working and needs better recipe/repair capabilities.

6. **P2 pre-existing issue remains:**
   - `MAVEN_OPTS` / `MAVEN_USER_HOME` ambient propagation in setup preflight only.

---

## 9. Commands to Reconfirm Local State

```powershell
cd C:\Users\abdelilah.mortaki\Desktop\modernizer-solution

git branch --show-current
git status --short
git log --oneline -n 10
git status -sb
```

Expected if local hotfix is committed and clean:

```text
before
HEAD includes 1e06b32
status clean
```

If `next-env.d.ts` appears:

```powershell
git restore -- web\control-tower\next-env.d.ts
git status --short
```

Focused tests to rerun after any next change:

```powershell
py -m pytest -q `
  tests/control_tower/test_v2_stage_progression.py `
  tests/control_tower/test_v2_stage_progression_policy.py `
  tests/control_tower/test_v2_orchestrator_runner.py `
  tests/control_tower/test_v2_e2e.py `
  tests/control_tower/test_v2_cockpit_events.py `
  tests/control_tower/test_v2_final_report_service.py

py -m pytest -q `
  tests/control_tower/test_sqlite_migrations.py `
  tests/control_tower/test_v2_phase_gate_migration.py `
  tests/control_tower/test_v2_artifact_revision_migration.py `
  tests/control_tower/test_v2_job_service.py `
  tests/control_tower/test_v2_setup_service.py `
  tests/control_tower/test_v2_worker_stage.py `
  tests/agents/planning_agent/test_boot4_stage_profile.py `
  tests/reporting/test_pdf_writer.py `
  tests/test_final_report.py

npm --prefix web/control-tower test -- `
  tests/controlTowerApi.test.ts `
  tests/migrationCockpit.test.tsx `
  tests/newMigrationForm.test.tsx

npm --prefix web/control-tower run typecheck
npm --prefix web/control-tower run build

git diff --check
git status --short
```

---

## 10. Suggested Skills / Tools for Next Session

The uploaded handoff instruction requires a suggested-skills section. Suggested skills/tools:

1. **GitHub / Codex repo inspection**
   - Inspect diffs and commit status for `1e06b32`.
   - Push hotfix or open PR if not pushed.

2. **Backend code audit**
   - Inspect:
     ```text
     migration_factory/control_tower/adapters/fastapi/app.py
     migration_factory/control_tower/application/v2_orchestrator_runner.py
     migration_factory/control_tower/application/v2_stage_progression.py
     migration_factory/control_tower/infrastructure/sqlite/v2_artifact_revision_repository.py
     ```

3. **SQLite runtime inspection**
   - Use Python `sqlite3` to inspect:
     ```text
     .control-tower-dev/control_tower.sqlite3
     v2_stage_commands
     v2_job_events
     v2_artifact_revisions
     artifacts
     ```

4. **Java/Spring Boot migration analysis**
   - Inspect the Stage 4 sandbox Java source and POM.
   - Focus on Jackson 2 → 3 package/dependency migration.

5. **OpenRewrite catalog update**
   - Inspect:
     ```text
     modernizer-solution-ai-hub/catalogs/openrewrite/springboot-3.5-java21-to-4.0-java21.yaml
     modernizer-solution-ai-hub/profiles/springboot-3.5-java21-to-4.0-java21.yaml
     ```
   - Add supported Jackson recipes if missing.

6. **Repair/failure-classification enhancement**
   - Improve deterministic repair handling for Boot 4/Jackson compile failures.
   - Avoid relying only on Copilot; Copilot returned `INVALID_RESPONSE` in the runtime failure.

7. **Frontend cockpit validation**
   - Ensure Stage 4 failure surfaces useful failure summary and repair artifacts without exposing paths.

---

## 11. Redaction / Security Notes

- No API keys, secrets, or credentials are included here.
- User-specific absolute Windows paths were avoided where possible and should be treated as local-only.
- Runtime job IDs are included because they are necessary for local DB/event inspection.
- Do not expose `sandbox_path`, `run_dir`, raw filesystem paths, argv, env, or absolute report paths in public API responses.
- Keep frontend/chatbot as decision surface only; backend remains execution authority.

---

## 12. One-Line Next Session Goal

Continue from the proven Stage 4 runtime failure: inspect the Stage 4 sandbox compile error around `JsonNode`, prove the minimal Jackson 3 or dependency fix in the sandbox, then update the Boot 4 OpenRewrite catalog/repair diagnostics so the system handles this class of Spring Boot 4/Jackson migration failure better.
