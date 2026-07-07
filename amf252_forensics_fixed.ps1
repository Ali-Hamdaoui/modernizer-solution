# =====================================================================
# AMF-252 Repair UI/Gate Forensics - FIXED VERSION
# =====================================================================

$ErrorActionPreference = "Stop"

$Job = "2223d92206df4bdd8498d417976d9af6"
$Port = "8000"

$RepoRoot = "C:\Users\abdelilah.mortaki\Desktop\modernizer-solution"
$OutRoot = Join-Path $RepoRoot ("_amf252_repair_ui_forensics_" + $Job)
New-Item -ItemType Directory -Force -Path $OutRoot | Out-Null

$Base = "http://127.0.0.1:$Port"

# ---------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------
$Report = [System.Collections.Generic.List[string]]::new()

function Add-ReportLine {
    param([object]$Text = "")
    $script:Report.Add([string]$Text) | Out-Null
}

function Save-JsonResponse {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url
    )

    $Path = Join-Path $OutRoot "$Name.json"

    try {
        Write-Host "GET $Url" -ForegroundColor Cyan
        $Data = Invoke-RestMethod $Url
        $Data | ConvertTo-Json -Depth 100 | Set-Content -Encoding UTF8 $Path
        return $Data
    }
    catch {
        $ErrorPath = Join-Path $OutRoot "$Name.ERROR.txt"
        $_ | Out-String | Set-Content -Encoding UTF8 $ErrorPath
        Write-Warning "Failed: $Url"
        return $null
    }
}

function Get-Prop {
    param(
        [Parameter(Mandatory = $false)]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }

    $Prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $Prop) {
        return $null
    }

    return $Prop.Value
}

function To-OneLine {
    param([Parameter(Mandatory = $false)]$Value)

    if ($null -eq $Value) {
        return ""
    }

    return (($Value | Out-String).Trim() -replace "`r", "" -replace "`n", " ")
}

function Has-Action {
    param(
        [Parameter(Mandatory = $false)]$Actions,
        [Parameter(Mandatory = $true)][string]$Action
    )

    if ($null -eq $Actions) {
        return $false
    }

    foreach ($A in $Actions) {
        if ([string]$A -eq $Action) {
            return $true
        }
    }

    return $false
}

# ---------------------------------------------------------------------
# 1. Capture backend endpoints
# ---------------------------------------------------------------------
$FailureSummary = Save-JsonResponse -Name "failure-summary" -Url "$Base/v1/v2/migration-jobs/$Job/failure-summary"
$CurrentProposal = Save-JsonResponse -Name "repair-proposals-current" -Url "$Base/v1/v2/jobs/$Job/repair/proposals/current"
$RepairAttempts = Save-JsonResponse -Name "repair-attempts" -Url "$Base/v1/v2/jobs/$Job/repair/attempts"
$LlmActivity = Save-JsonResponse -Name "llm-activity" -Url "$Base/v1/v2/jobs/$Job/llm/activity"
$Pipeline = Save-JsonResponse -Name "pipeline" -Url "$Base/v1/v2/migration-jobs/$Job/pipeline"
$Events = Save-JsonResponse -Name "events-snapshot" -Url "$Base/v1/v2/migration-jobs/$Job/events/snapshot?after=0"

# ---------------------------------------------------------------------
# 2. Capture code-search snippets
# ---------------------------------------------------------------------
$SearchOut = Join-Path $OutRoot "code-search.txt"
"" | Set-Content -Encoding UTF8 $SearchOut

if (Test-Path -LiteralPath $RepoRoot) {
    Push-Location $RepoRoot

    $Searches = @(
        @{
            Path = "web\control-tower\app\migrations\[jobId]\RepairProposalPanel.tsx"
            Pattern = "Reviewed Repair Materialization Failed|Reviewed Repair Diff Invalid|ValidationProgressPanel|materialization_failed|REVIEWER_REQUESTED_REVISION|allowed_actions|reviewed_diff|Not available|No repair proposal available|needs_revision"
        },
        @{
            Path = "web\control-tower\app\migrations\[jobId]\MigrationCockpit.tsx"
            Pattern = "Failure Evidence|Repair materialization blocker|original_stage_failure|repair_materialization_failure|repair_loop_active|repair_events"
        },
        @{
            Path = "web\control-tower\app\migrations\[jobId]\ValidationProgressPanel.tsx"
            Pattern = "attempts|return null|ValidationProgressPanel|repair_attempts"
        },
        @{
            Path = "web\control-tower\app\migrations\[jobId]\RepairActionsBar.tsx"
            Pattern = "allowedActions|allowed_actions|approve_sandbox_apply|view_diff|view_reviewer_opinion"
        },
        @{
            Path = "web\control-tower\lib\contracts.ts"
            Pattern = "RepairMaterializationUnavailable|reason_code|detail|scope|repair_materialization_failure|original_stage_failure|REVIEWER_REQUESTED_REVISION"
        },
        @{
            Path = "migration_factory\control_tower\adapters\fastapi\app.py"
            Pattern = "_v2_failure_summary|reviewed_repair_materialization_failed|reviewed_repair_unavailable|retry_required|_latest_repair_materialization_unavailable|_unavailable_allowed_actions|_v2_pipeline_projection|failure_repair|REVIEWER_REQUESTED_REVISION"
        },
        @{
            Path = "migration_factory\control_tower\application\v2_repair_projection.py"
            Pattern = "reviewed_diff|READ_ONLY_REPAIR_ACTIONS|record_to_attempt_summary|build_reviewed_diff_proposal"
        }
    )

    foreach ($S in $Searches) {
        $P = $S.Path
        $Pattern = $S.Pattern

        Add-Content -Encoding UTF8 $SearchOut ""
        Add-Content -Encoding UTF8 $SearchOut "============================================================"
        Add-Content -Encoding UTF8 $SearchOut "FILE: $P"
        Add-Content -Encoding UTF8 $SearchOut "PATTERN: $Pattern"
        Add-Content -Encoding UTF8 $SearchOut "============================================================"

        if (Test-Path -LiteralPath $P) {
            Select-String -LiteralPath $P -Pattern $Pattern -Context 8,20 |
                Out-String -Width 300 |
                Add-Content -Encoding UTF8 $SearchOut
        }
        else {
            Add-Content -Encoding UTF8 $SearchOut "MISSING FILE: $P"
        }
    }

    Pop-Location
}

# ---------------------------------------------------------------------
# 3. Extract state
# ---------------------------------------------------------------------
$Proposal = Get-Prop $CurrentProposal "proposal"
$Unavailable = Get-Prop $CurrentProposal "unavailable"
$Attempts = Get-Prop $RepairAttempts "attempts"

$UnavailableKind = Get-Prop $Unavailable "kind"
$UnavailableTitle = Get-Prop $Unavailable "title"
$ReasonCode = Get-Prop $Unavailable "reason_code"
$Detail = Get-Prop $Unavailable "detail"
$ReviewerDecision = Get-Prop $Unavailable "reviewer_decision"
$NextAction = Get-Prop $Unavailable "next_action"
$AllowedActions = Get-Prop $Unavailable "allowed_actions"
$FinalDiffExists = Get-Prop $Unavailable "final_diff_exists"
$ReviewedDiffChecksum = Get-Prop $Unavailable "reviewed_diff_checksum"
$ReviewerSelfRepairAttempted = Get-Prop $Unavailable "reviewer_self_repair_attempted"
$ReviewerSelfRepairSucceeded = Get-Prop $Unavailable "reviewer_self_repair_succeeded"
$BackendGeneratedDiff = Get-Prop $Unavailable "backend_generated_diff"

$AttemptsCount = 0
if ($null -ne $Attempts) {
    $AttemptsCount = @($Attempts).Count
}

$CanApprove = Has-Action $AllowedActions "approve_sandbox_apply"
$CanViewDiff = Has-Action $AllowedActions "view_diff"

# ---------------------------------------------------------------------
# 4. Write report
# ---------------------------------------------------------------------
Add-ReportLine "# AMF-252 Repair UI/Gate Forensics"
Add-ReportLine ""
Add-ReportLine "Job: $Job"
Add-ReportLine "Generated: $(Get-Date -Format o)"
Add-ReportLine ""

Add-ReportLine "## Executive Diagnosis"
Add-ReportLine ""

if ($null -eq $Proposal -and $UnavailableKind -eq "materialization_failed") {
    Add-ReportLine "- Current repair gate is unavailable/materialization_failed."
}
elseif ($null -ne $Proposal) {
    Add-ReportLine "- Current repair gate has a proposal."
}
else {
    Add-ReportLine "- Current repair gate has no proposal and no unavailable object. This may be loading or empty-state behavior."
}

if ($ReasonCode -eq "REVIEWER_REQUESTED_REVISION" -or $ReviewerDecision -eq "needs_revision") {
    Add-ReportLine "- Diff is likely not displayed because reviewer decision is needs_revision or reason code REVIEWER_REQUESTED_REVISION."
    Add-ReportLine "- This means the reviewer did not approve a final reviewed diff. UI should show reviewer requested revision, not a missing diff bug."
}
elseif ($ReasonCode -eq "MALFORMED_DIFF") {
    Add-ReportLine "- Diff failed after reviewer acceptance because backend structural validation rejected a malformed diff."
}
elseif ($null -ne $ReasonCode) {
    Add-ReportLine "- Repair gate reason code: $ReasonCode."
}

if ($AttemptsCount -eq 0) {
    Add-ReportLine "- Repair attempts are empty. Validation timeline should not render."
}
else {
    Add-ReportLine "- Repair attempts count: $AttemptsCount. Validation timeline may render from real attempts."
}

if ($CanApprove) {
    Add-ReportLine "- WARNING: allowed_actions includes approve_sandbox_apply."
}
else {
    Add-ReportLine "- No approve_sandbox_apply action is exposed."
}

Add-ReportLine ""

Add-ReportLine "## Current Reviewed Repair Gate"
Add-ReportLine ""
Add-ReportLine "| Field | Value |"
Add-ReportLine "|---|---|"
Add-ReportLine "| proposal exists | $($null -ne $Proposal) |"
Add-ReportLine "| unavailable.kind | $(To-OneLine $UnavailableKind) |"
Add-ReportLine "| unavailable.title | $(To-OneLine $UnavailableTitle) |"
Add-ReportLine "| reason_code | $(To-OneLine $ReasonCode) |"
Add-ReportLine "| reviewer_decision | $(To-OneLine $ReviewerDecision) |"
Add-ReportLine "| final_diff_exists | $(To-OneLine $FinalDiffExists) |"
Add-ReportLine "| reviewed_diff_checksum | $(To-OneLine $ReviewedDiffChecksum) |"
Add-ReportLine "| attempts_count | $AttemptsCount |"
Add-ReportLine "| can_view_diff | $CanViewDiff |"
Add-ReportLine "| can_approve | $CanApprove |"
Add-ReportLine "| reviewer_self_repair_attempted | $(To-OneLine $ReviewerSelfRepairAttempted) |"
Add-ReportLine "| reviewer_self_repair_succeeded | $(To-OneLine $ReviewerSelfRepairSucceeded) |"
Add-ReportLine "| backend_generated_diff | $(To-OneLine $BackendGeneratedDiff) |"
Add-ReportLine "| next_action | $(To-OneLine $NextAction) |"
Add-ReportLine "| detail | $(To-OneLine $Detail) |"
Add-ReportLine ""

Add-ReportLine "## Why Diff May Not Display"
Add-ReportLine ""

if ($ReasonCode -eq "REVIEWER_REQUESTED_REVISION" -or $ReviewerDecision -eq "needs_revision") {
    Add-ReportLine "Result: Expected no reviewed diff display."
    Add-ReportLine ""
    Add-ReportLine "The reviewer requested revision. A final reviewed diff should not be exposed as applyable. The UI should show:"
    Add-ReportLine "- reviewer requested revision"
    Add-ReportLine "- no backend validation or apply path"
    Add-ReportLine "- no repair proposal available"
    Add-ReportLine "- optional raw draft or reviewer output diagnostics only if a read-only artifact exists"
}
elseif ($FinalDiffExists -eq $true -and $CanViewDiff) {
    Add-ReportLine "Result: Backend says a final diff exists and view_diff is allowed."
    Add-ReportLine ""
    Add-ReportLine "If UI does not display it, likely frontend issue:"
    Add-ReportLine "- view_diff action exists but no button or component renders it"
    Add-ReportLine "- diff fetch endpoint is missing or failing"
    Add-ReportLine "- frontend hides diff for unavailable branch"
}
elseif ($FinalDiffExists -eq $true -and -not $CanViewDiff) {
    Add-ReportLine "Result: Backend says final_diff_exists=true but allowed_actions does not include view_diff."
    Add-ReportLine ""
    Add-ReportLine "Likely backend action-gating issue."
}
else {
    Add-ReportLine "Result: No final diff is available from the current gate payload."
    Add-ReportLine ""
    Add-ReportLine "If a draft diff exists in artifacts, the UI needs a separate read-only diagnostic path. It should not call it a reviewed diff."
}

Add-ReportLine ""

Add-ReportLine "## Failure Summary Scoping"
Add-ReportLine ""

$Failures = Get-Prop $FailureSummary "failures"
$RepairLoopActive = Get-Prop $FailureSummary "repair_loop_active"
$TopRepairEvents = Get-Prop $FailureSummary "repair_events"

Add-ReportLine "Top-level repair_loop_active: $RepairLoopActive"
Add-ReportLine "Top-level repair_events count: $(@($TopRepairEvents).Count)"
Add-ReportLine ""
Add-ReportLine "| type | scope | title | repair_loop_status | reason_code | next_operator_action |"
Add-ReportLine "|---|---|---|---|---|---|"

$BadScopes = [System.Collections.Generic.List[string]]::new()

foreach ($F in @($Failures)) {
    $T = Get-Prop $F "type"
    $Scope = Get-Prop $F "scope"
    $Title = Get-Prop $F "title"
    $Rls = Get-Prop $F "repair_loop_status"
    $Rc = Get-Prop $F "reason_code"
    $Noa = Get-Prop $F "next_operator_action"

    Add-ReportLine "| $(To-OneLine $T) | $(To-OneLine $Scope) | $(To-OneLine $Title) | $(To-OneLine $Rls) | $(To-OneLine $Rc) | $(To-OneLine $Noa) |"

    if (($T -eq "reviewed_repair_materialization_failed" -or $T -eq "reviewed_repair_unavailable" -or $T -eq "retry_required") -and $Scope -eq "original_stage_failure") {
        $BadScopes.Add("$T is incorrectly scoped as original_stage_failure") | Out-Null
    }
}

Add-ReportLine ""

if ($BadScopes.Count -gt 0) {
    Add-ReportLine "### Scope Problems Found"
    foreach ($B in $BadScopes) {
        Add-ReportLine "- $B"
    }
}
else {
    Add-ReportLine "### Scope Check"
    Add-ReportLine "No repair materialization blocker is incorrectly scoped as original_stage_failure."
}

Add-ReportLine ""

Add-ReportLine "## Pipeline Analysis"
Add-ReportLine ""

$Rows = Get-Prop $Pipeline "rows"
$FailureRepairRow = $null

foreach ($R in @($Rows)) {
    if ((Get-Prop $R "key") -eq "failure_repair") {
        $FailureRepairRow = $R
        break
    }
}

if ($null -eq $FailureRepairRow) {
    Add-ReportLine "No failure_repair row found."
}
else {
    $FrStatus = Get-Prop $FailureRepairRow "status"
    $FrMsg = Get-Prop $FailureRepairRow "latest_message"
    $FrUpdated = Get-Prop $FailureRepairRow "last_updated"

    Add-ReportLine "| Field | Value |"
    Add-ReportLine "|---|---|"
    Add-ReportLine "| status | $(To-OneLine $FrStatus) |"
    Add-ReportLine "| latest_message | $(To-OneLine $FrMsg) |"
    Add-ReportLine "| last_updated | $(To-OneLine $FrUpdated) |"
    Add-ReportLine ""

    if ($FrStatus -eq "running" -and $UnavailableKind -eq "materialization_failed") {
        Add-ReportLine "Problem: pipeline still shows failure_repair running while repair gate is materialization_failed."
    }
    elseif ($FrStatus -eq "blocked" -or $FrStatus -eq "retry_required") {
        Add-ReportLine "Pipeline status is consistent with blocked materialization state."
    }
    else {
        Add-ReportLine "Pipeline status needs manual review for this state."
    }
}

Add-ReportLine ""

Add-ReportLine "## Event Snapshot Signal"
Add-ReportLine ""

$EventItems = Get-Prop $Events "events"
$InterestingTypes = @(
    "repair_started",
    "repair_chain_started",
    "repair_llm_main_completed",
    "repair_llm_reviewer_completed",
    "reviewed_repair_materialization_failed",
    "reviewed_repair_unavailable",
    "retry_required",
    "stage_failed",
    "transform_failed",
    "build_failed"
)

Add-ReportLine "| sequence | type | status | message | reason_code | reviewer_decision |"
Add-ReportLine "|---|---|---|---|---|---|"

foreach ($E in @($EventItems)) {
    $Type = Get-Prop $E "type"
    if ($InterestingTypes -contains $Type) {
        $Payload = Get-Prop $E "payload"
        $Seq = Get-Prop $E "sequence"
        $Status = Get-Prop $E "status"
        $Msg = Get-Prop $E "message"
        $Rc = Get-Prop $Payload "reason_code"
        $Decision = Get-Prop $Payload "reviewer_decision"

        Add-ReportLine "| $(To-OneLine $Seq) | $(To-OneLine $Type) | $(To-OneLine $Status) | $(To-OneLine $Msg) | $(To-OneLine $Rc) | $(To-OneLine $Decision) |"
    }
}

Add-ReportLine ""

Add-ReportLine "## Recommended Fix Classification"
Add-ReportLine ""

if ($ReasonCode -eq "REVIEWER_REQUESTED_REVISION" -or $ReviewerDecision -eq "needs_revision") {
    Add-ReportLine "This is likely a new state-specific UI/copy issue, not the old Problem B leak."
    Add-ReportLine ""
    Add-ReportLine "Recommended fix:"
    Add-ReportLine "- Add a distinct frontend branch for REVIEWER_REQUESTED_REVISION or reviewer_decision = needs_revision."
    Add-ReportLine "- Title: Reviewer Requested Revision."
    Add-ReportLine "- Explain: Reviewer found the draft diff structurally invalid and requested a corrected repair proposal."
    Add-ReportLine "- Do not show approve/apply."
    Add-ReportLine "- Do not show validation timeline."
    Add-ReportLine "- Optionally expose raw draft/reviewer output as read-only diagnostics if backend has artifact refs."
}
elseif ($ReasonCode -eq "MALFORMED_DIFF") {
    Add-ReportLine "This is the known malformed diff materialization state."
    Add-ReportLine ""
    Add-ReportLine "Recommended fix:"
    Add-ReportLine "- If UI still hides available diff diagnostics, inspect diff action and fetch rendering."
    Add-ReportLine "- Actual automation fix belongs to Problem A soft materialization recovery."
}
else {
    Add-ReportLine "Unknown or unclassified state. Inspect current proposal and event snapshot in the captured JSON files."
}

# ---------------------------------------------------------------------
# 5. Write output
# ---------------------------------------------------------------------
$ReportPath = Join-Path $OutRoot "AMF252_REPAIR_UI_GATE_FORENSICS_REPORT.md"
$Report | Set-Content -Encoding UTF8 $ReportPath

Write-Host ""
Write-Host "Forensics complete." -ForegroundColor Green
Write-Host "Output directory: $OutRoot"
Write-Host "Report: $ReportPath"
Write-Host "Code search: $SearchOut"
Write-Host ""
Write-Host "Open report:"
Write-Host "notepad `"$ReportPath`""