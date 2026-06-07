[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$LegacyApp,

    [Parameter(Mandatory = $true)]
    [string]$ModernizedApp,

    [string]$RunId,

    [string]$Profile = "springboot-2.7-to-3.5-java17",

    [string]$AiHub = "modernizer-solution-ai-hub",

    [string]$ApprovedBy,

    [switch]$ApproveAndResume
)

$ErrorActionPreference = "Stop"

function Resolve-RepoPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathValue,
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return (Resolve-Path -LiteralPath $PathValue).Path
    }

    return (Resolve-Path -LiteralPath (Join-Path $RepoRoot $PathValue)).Path
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot

try {
    if (-not $RunId) {
        $RunId = "smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss")
    }

    if (-not $ApprovedBy) {
        $ApprovedBy = if ($env:USERNAME) { $env:USERNAME } else { "local-reviewer" }
    }

    $resolvedLegacy = Resolve-RepoPath -PathValue $LegacyApp -RepoRoot $repoRoot
    $resolvedModernized = Resolve-RepoPath -PathValue $ModernizedApp -RepoRoot $repoRoot
    $resolvedAiHub = Resolve-RepoPath -PathValue $AiHub -RepoRoot $repoRoot
    $runDir = Join-Path $resolvedModernized ".migration\runs\$RunId"

    $env:PYTHONPATH = "."

    Write-Host "Repo root: $repoRoot"
    Write-Host "Legacy app: $resolvedLegacy"
    Write-Host "Modernized app: $resolvedModernized"
    Write-Host "AI Hub: $resolvedAiHub"
    Write-Host "Profile: $Profile"
    Write-Host "Run id: $RunId"
    Write-Host "Resolved run directory: $runDir"
    Write-Host ""
    Write-Host "Phase 1: starting full sandbox migration orchestration..."

    & python -m migration_factory.orchestrator.runner `
        --run-id $RunId `
        --legacy $resolvedLegacy `
        --modernized $resolvedModernized `
        --ai-hub $resolvedAiHub `
        --profile $Profile `
        --mode full_sandbox_migration

    if ($LASTEXITCODE -ne 0) {
        throw "Initial orchestration failed with exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Phase 1 complete. Review artifacts before approval."
    Write-Host "Run directory: $runDir"
    Write-Host "Recommended review targets:"
    Write-Host "  - $runDir\analysis\analysis_report.json"
    Write-Host "  - $runDir\planning\migration_plan.yaml"
    Write-Host "  - $runDir\planning\migration_units.yaml"
    Write-Host "  - $runDir\planning\approval_request.json"
    Write-Host "  - $runDir\assessment\assessment_report.json"

    if (-not $ApproveAndResume) {
        Write-Host ""
        Write-Host "No auto-approval done."
        Write-Host "When ready, resume manually with:"
        Write-Host "python -m migration_factory.orchestrator.resume --run-id $RunId --run-dir `"$runDir`" --decision approved --approved-by `"$ApprovedBy`""
        exit 0
    }

    Write-Host ""
    Write-Host "ApproveAndResume set. Resuming approved sandbox migration..."
    & python -m migration_factory.orchestrator.resume `
        --run-id $RunId `
        --run-dir $runDir `
        --decision approved `
        --approved-by $ApprovedBy

    if ($LASTEXITCODE -ne 0) {
        throw "Approval resume failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
