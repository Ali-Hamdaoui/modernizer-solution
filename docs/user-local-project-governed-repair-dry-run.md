# User Local Project Governed Repair Dry Run

This runbook prepares a safe dry run for a user-provided legacy project path:

```text
<USER_LEGACY_PROJECT_PATH>
```

It uses the existing governed repair flow, sandbox copy, reviewer gate, human approval, sandbox-only apply, and post-apply verification. It does **not** add new backend behavior.

## Safety guarantees

- The legacy project is treated as read-only.
- All mutation happens only in a temporary sandbox copy.
- No external LLM is called during apply or verification.
- No auto-apply is used.
- Human approval is still required before sandbox apply.
- The real validation runner is used only through the existing backend repair flow.
- No hardcoded user path is committed to code or tests.

## What already exists in this repo

- `migration_factory/repair_loop/validation_runner.py`
  - Real sandbox build/test/H2 validation entry.
- `migration_factory/repair_loop/patch_apply.py`
  - Sandbox-only patch apply and rollback helpers.
- `migration_factory/control_tower/application/v2_repair_flow.py`
  - Governed repair proposal, approval, apply, verification, and artifact projection.
- `tests/control_tower/test_v2_assistant_repair_api.py`
  - Proof that the governed repair workflow can run against a copied local Maven project fixture.

## Manual dry-run recipe

1. Set the user legacy path.

   ```powershell
   $legacy = "<USER_LEGACY_PROJECT_PATH>"
   ```

2. Check that the path exists and is a directory.

   ```powershell
   if (-not (Test-Path -LiteralPath $legacy)) { throw "Legacy path missing" }
   if (-not (Get-Item -LiteralPath $legacy).PSIsContainer) { throw "Legacy path is not a directory" }
   ```

3. Copy the legacy project into a temporary sandbox outside the legacy tree.

   ```powershell
   $sandboxRoot = Join-Path $env:TEMP ("modernizer-governed-dryrun-" + [Guid]::NewGuid().ToString("n"))
   New-Item -ItemType Directory -Force $sandboxRoot | Out-Null
   Copy-Item -LiteralPath $legacy -Destination (Join-Path $sandboxRoot "legacy-copy") -Recurse -Force
   ```

4. Record a legacy checksum snapshot before any repair work.

   ```powershell
   Get-ChildItem -LiteralPath $legacy -Recurse -File |
     Sort-Object FullName |
     ForEach-Object {
       [PSCustomObject]@{
         Path = $_.FullName
         Sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash
       }
     } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $sandboxRoot "legacy-checksum-before.json")
   ```

5. Run the existing governed repair flow against the sandbox copy.

   - Seed the usual failure evidence artifacts if the project already has them.
   - Ask the assistant: `solve this`
   - Review the governed proposal and reviewer critique.
   - Explicitly approve the proposal.
   - Apply only inside the sandbox.
   - Let the existing validation runner handle build/test/H2 verification.

6. Confirm the sandbox changed, but the legacy project did not.

   - Compare the legacy snapshot from step 4 with a fresh snapshot.
   - Verify the sandbox contains the expected patch/apply and verification artifacts.

7. Inspect the verification result.

   Expected backend-visible fields:

   - `verification_status`
   - `verification_build_status`
   - `verification_test_status`
   - `verification_h2_status`
   - `verification_artifact_refs`
   - `verification_failure_classification_ref`

## Real validation runner

The repo already has a real validation runner in `migration_factory/repair_loop/validation_runner.py`. It runs build/test/H2 work on the sandbox copy and records artifact refs for the repair flow.

Use the real runner when:

- the local project can be copied safely into a temp sandbox;
- the project has a valid Maven or equivalent validation setup already supported by the existing runner;
- you want to prove the sandbox can be built and tested after the approved patch.

Use the existing stubbed dry-run tests when:

- you only need to prove proposal/approval/apply/verification wiring;
- the local project is too heavy for a quick validation;
- the project setup is not yet compatible with the runner.

## Known limitations

- This repo does not add a new generic CLI for arbitrary user project paths in this ticket.
- The runbook assumes the operator or a later harness will pass the user path into the same governed flow that already handles sandbox paths internally.
- If the user project needs a new integration seam, add that seam in a later ticket instead of hardcoding paths now.

## Recommended proof points

- Legacy path remains unchanged.
- Sandbox path is outside the legacy tree.
- Proposal exists before approval.
- Apply only runs after explicit human approval.
- Verification artifacts are present after apply.
- Failure classification is exposed when verification fails.
