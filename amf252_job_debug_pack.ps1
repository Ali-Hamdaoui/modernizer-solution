# =====================================================================
# AMF-252 Job Debug Pack -- HTTP 400 / Reviewed Repair Unavailable
# Windows / PowerShell
#
# Output:
#   C:\Users\abdelilah.mortaki\Desktop\LOGS\AMF252-DEBUG-<job>-<timestamp>
#
# Purpose:
#   Diagnose why UI shows:
#     Reviewed Repair unavailable
#     Reason: REPAIR_BLOCKED / PRIMARY_INVALID_RESPONSE
#     Detail: primary repair model failed closed: http_400
#
# This script does NOT rerun migration and does NOT call LLMs.
# It only reads backend APIs, local run artifacts, local code extracts,
# and local log-like files to explain what happened.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File "C:\Users\abdelilah.mortaki\Desktop\modernizer-solution\amf252_job_debug_pack_HTTP400.ps1" -JobUrl "http://127.0.0.1:3000/migrations/<JOB_ID>" -OpenFolder
#
# Or:
#   powershell -ExecutionPolicy Bypass -File ".\amf252_job_debug_pack_HTTP400.ps1" -JobId "<JOB_ID>" -OpenFolder
# =====================================================================

param(
    [string]$JobUrl = "",
    [string]$JobId = "",
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$RepoRoot = "C:\Users\abdelilah.mortaki\Desktop\modernizer-solution",
    [string]$LogsRoot = "C:\Users\abdelilah.mortaki\Desktop\LOGS",
    [int]$MaxTimeSeconds = 10,
    [int]$MaxArtifactFiles = 600,
    [int]$MaxPreviewChars = 12000,
    [switch]$OpenFolder
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------
# Resolve JobId
# ---------------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($JobId)) {
    if ($JobUrl -match "/migrations/([a-fA-F0-9\-]+)") {
        $JobId = $Matches[1]
    }
}

if ([string]::IsNullOrWhiteSpace($JobId)) {
    throw "JobId could not be resolved. Pass -JobId or -JobUrl."
}

$JobPrefix = $JobId
if ($JobPrefix.Length -gt 8) {
    $JobPrefix = $JobPrefix.Substring(0, 8)
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutDir = Join-Path $LogsRoot "AMF252-DEBUG-$JobId-$Timestamp"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
function Save-Text {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text
    )

    $path = Join-Path $OutDir $Name
    $Text | Out-File -FilePath $path -Encoding utf8
    return $path
}

function Save-JsonObject {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Data
    )

    $path = Join-Path $OutDir $Name
    $Data | ConvertTo-Json -Depth 100 | Out-File -FilePath $path -Encoding utf8
    return $path
}

function Load-JsonFile {
    param([string]$Path)

    try {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            return $null
        }

        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return $null
        }

        return $raw | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Get-Prop {
    param($Object, [string]$Name)

    if ($null -eq $Object) {
        return $null
    }

    if ($Object.PSObject.Properties.Name -contains $Name) {
        return $Object.$Name
    }

    return $null
}

function As-Array {
    param($Value)

    if ($null -eq $Value) {
        return @()
    }

    if ($Value -is [System.Array]) {
        return @($Value)
    }

    return @($Value)
}

function Get-Items {
    param($Response)

    if ($null -eq $Response) {
        return @()
    }

    foreach ($key in @("events", "items", "data", "stages", "rows", "failures", "attempts", "gates", "approvals", "invocations", "activity")) {
        if ($Response.PSObject.Properties.Name -contains $key) {
            return @(As-Array $Response.$key)
        }
    }

    if ($Response -is [System.Array]) {
        return @($Response)
    }

    return @($Response)
}

function Truncate-Text {
    param(
        [AllowEmptyString()][string]$Text,
        [int]$MaxChars = 4000
    )

    if ($null -eq $Text) {
        return ""
    }

    if ($Text.Length -le $MaxChars) {
        return $Text
    }

    return $Text.Substring(0, $MaxChars) + "`n...[truncated]..."
}

function Invoke-ApiNoHang {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $url = "$BaseUrl$Path"
    $outFile = Join-Path $OutDir "$Name.json"
    $errFile = Join-Path $OutDir "$Name.stderr.txt"

    Write-Host "GET $url" -ForegroundColor Cyan

    $curlArgs = @(
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--connect-timeout", "3",
        "--max-time", "$MaxTimeSeconds",
        "--http1.1",
        "-H", "Connection: close",
        "-H", "Accept: application/json",
        "-o", $outFile,
        "-w", "%{http_code}",
        $url
    )

    $started = Get-Date
    $statusCode = & curl.exe @curlArgs 2> $errFile
    $exitCode = $LASTEXITCODE
    $ended = Get-Date

    $responsePreview = ""
    if (Test-Path -LiteralPath $outFile -PathType Leaf) {
        try {
            $responsePreview = Truncate-Text -Text (Get-Content -LiteralPath $outFile -Raw -Encoding UTF8) -MaxChars 2000
        } catch {
            $responsePreview = ""
        }
    }

    $stderrPreview = ""
    if (Test-Path -LiteralPath $errFile -PathType Leaf) {
        try {
            $stderrPreview = Truncate-Text -Text (Get-Content -LiteralPath $errFile -Raw -Encoding UTF8) -MaxChars 2000
        } catch {
            $stderrPreview = ""
        }
    }

    $meta = [ordered]@{
        name = $Name
        url = $url
        status_code = "$statusCode"
        curl_exit_code = $exitCode
        duration_seconds = [Math]::Round(($ended - $started).TotalSeconds, 3)
        output_file = $outFile
        stderr_file = $errFile
        response_preview = $responsePreview
        stderr_preview = $stderrPreview
    }

    if ($exitCode -eq 0) {
        Write-Host "  OK $statusCode -> $Name.json" -ForegroundColor Green
    }
    else {
        Write-Host "  FAILED curl_exit=$exitCode http=$statusCode -> $Name.json" -ForegroundColor Yellow
    }

    return $meta
}

function Get-CodeExtract {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string[]]$Patterns,
        [int]$Context = 25
    )

    $filePath = Join-Path $RepoRoot $RelativePath
    $sections = @()

    if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
        return "## $RelativePath`n`nFILE NOT FOUND: $filePath`n"
    }

    $lines = Get-Content -LiteralPath $filePath -Encoding UTF8

    foreach ($pattern in $Patterns) {
        $hits = @()

        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match $pattern) {
                $hits += $i
            }
        }

        if ($hits.Count -eq 0) {
            $sections += "### Pattern: " + $pattern + "`nNo hits.`n"
            continue
        }

        $hitIndex = 0
        foreach ($hit in ($hits | Select-Object -First 8)) {
            $hitIndex += 1
            $start = [Math]::Max(0, $hit - $Context)
            $end = [Math]::Min($lines.Count - 1, $hit + $Context)

            $snippet = New-Object System.Collections.Generic.List[string]
            for ($j = $start; $j -le $end; $j++) {
                $lineNo = $j + 1
                $snippet.Add(("{0,6}: {1}" -f $lineNo, $lines[$j]))
            }

            $sections += "### Pattern: $pattern hit $hitIndex around line $($hit + 1)"
            $sections += ""
            $sections += '```text'
            $sections += ($snippet -join "`n")
            $sections += '```'
            $sections += ""
        }
    }

    return "## $RelativePath`n`n" + ($sections -join "`n")
}

function Read-FilePreview {
    param(
        [string]$Path,
        [int64]$MaxBytes = 2097152
    )

    try {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            return $null
        }

        $item = Get-Item -LiteralPath $Path
        if ($item.Length -gt $MaxBytes) {
            return [ordered]@{
                path = $Path
                skipped = $true
                reason = "file_too_large"
                length = $item.Length
                last_write_time = $item.LastWriteTime.ToString("s")
            }
        }

        $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        $json = $null
        try {
            $json = $raw | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            $json = $null
        }

        return [ordered]@{
            path = $Path
            skipped = $false
            length = $item.Length
            last_write_time = $item.LastWriteTime.ToString("s")
            raw_preview = (Truncate-Text -Text $raw -MaxChars $MaxPreviewChars)
            json = $json
        }
    }
    catch {
        return [ordered]@{
            path = $Path
            skipped = $true
            reason = $_.Exception.Message
        }
    }
}

function Add-RootIfExists {
    param(
        [System.Collections.Generic.List[string]]$Roots,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    try {
        if (Test-Path -LiteralPath $Path -PathType Container) {
            $Roots.Add((Resolve-Path -LiteralPath $Path).Path)
        }
    } catch {
        # ignore bad roots
    }
}

function Add-ParentIfFileExists {
    param(
        [System.Collections.Generic.List[string]]$Roots,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    try {
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            $parent = Split-Path -Parent $Path
            Add-RootIfExists -Roots $Roots -Path $parent
        }
    } catch {
        # ignore bad refs
    }
}

function Find-ValuesByPropertyName {
    param(
        $Object,
        [string[]]$Names,
        [int]$Depth = 0,
        [int]$MaxDepth = 12
    )

    $found = New-Object System.Collections.Generic.List[object]

    if ($null -eq $Object -or $Depth -gt $MaxDepth) {
        return @()
    }

    if ($Object -is [System.Array]) {
        foreach ($item in $Object) {
            foreach ($x in (Find-ValuesByPropertyName -Object $item -Names $Names -Depth ($Depth + 1) -MaxDepth $MaxDepth)) {
                $found.Add($x)
            }
        }
        return @($found)
    }

    if ($Object.PSObject -and $Object.PSObject.Properties) {
        foreach ($prop in $Object.PSObject.Properties) {
            if ($Names -contains $prop.Name) {
                $found.Add($prop.Value)
            }

            $value = $prop.Value
            if ($null -ne $value -and -not ($value -is [string]) -and -not ($value -is [ValueType])) {
                foreach ($x in (Find-ValuesByPropertyName -Object $value -Names $Names -Depth ($Depth + 1) -MaxDepth $MaxDepth)) {
                    $found.Add($x)
                }
            }
        }
    }

    return @($found)
}

function Get-SafeEnvSnapshot {
    $names = @(
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_PROPOSER_DEPLOYMENT",
        "AZURE_OPENAI_PROPOSER_MODEL",
        "AZURE_OPENAI_PROPOSER_MAX_INPUT_TOKENS",
        "AZURE_OPENAI_PROPOSER_MAX_OUTPUT_TOKENS",
        "AZURE_OPENAI_PROPOSER_MAX_COMPLETION_TOKENS",
        "AZURE_OPENAI_PROPOSER_RESPONSE_FORMAT",
        "AZURE_OPENAI_PROPOSER_REASONING_EFFORT",
        "AZURE_OPENAI_MAIN_DEPLOYMENT",
        "AZURE_OPENAI_MAIN_MODEL",
        "AZURE_OPENAI_MAIN_MAX_INPUT_TOKENS",
        "AZURE_OPENAI_MAIN_MAX_OUTPUT_TOKENS",
        "AZURE_OPENAI_MAIN_MAX_COMPLETION_TOKENS",
        "AZURE_OPENAI_MAIN_RESPONSE_FORMAT",
        "AZURE_OPENAI_MAIN_REASONING_EFFORT",
        "AZURE_OPENAI_REVIEWER_DEPLOYMENT",
        "AZURE_OPENAI_REVIEWER_MODEL",
        "AZURE_OPENAI_REVIEWER_MAX_INPUT_TOKENS",
        "AZURE_OPENAI_REVIEWER_MAX_OUTPUT_TOKENS",
        "AZURE_OPENAI_REVIEWER_MAX_COMPLETION_TOKENS",
        "AZURE_OPENAI_REVIEWER_RESPONSE_FORMAT",
        "AZURE_OPENAI_REVIEWER_REASONING_EFFORT",
        "AZURE_OPENAI_FALLBACK_DEPLOYMENT",
        "AZURE_OPENAI_FALLBACK_MODEL",
        "AZURE_OPENAI_FALLBACK_MAX_INPUT_TOKENS",
        "AZURE_OPENAI_FALLBACK_MAX_OUTPUT_TOKENS",
        "AZURE_OPENAI_FALLBACK_MAX_COMPLETION_TOKENS",
        "AZURE_OPENAI_FALLBACK_RESPONSE_FORMAT",
        "AZURE_OPENAI_FALLBACK_REASONING_EFFORT",
        "AI_MIGRATION_MAIN_RESPONSE_FORMAT",
        "AI_MIGRATION_MAIN_MAX_INPUT_TOKENS",
        "AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS",
        "AI_MIGRATION_MAIN_MAX_COMPLETION_TOKENS",
        "AI_MIGRATION_PROPOSER_RESPONSE_FORMAT",
        "AI_MIGRATION_PROPOSER_MAX_INPUT_TOKENS",
        "AI_MIGRATION_PROPOSER_MAX_OUTPUT_TOKENS",
        "AI_MIGRATION_PROPOSER_MAX_COMPLETION_TOKENS",
        "AI_MIGRATION_REVIEWER_RESPONSE_FORMAT",
        "AI_MIGRATION_REVIEWER_MAX_INPUT_TOKENS",
        "AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS",
        "AI_MIGRATION_REVIEWER_MAX_COMPLETION_TOKENS",
        "AI_MIGRATION_AUTO_APPLY_SAFE_REPAIRS",
        "AI_MIGRATION_REPAIR_TRACE",
        "AI_MIGRATION_REPAIR_DEBUG"
    )

    $snapshot = [ordered]@{}
    foreach ($name in $names) {
        $value = [Environment]::GetEnvironmentVariable($name, "Process")
        if ($name -match "KEY|SECRET|TOKEN|PASSWORD") {
            $snapshot[$name] = if ([string]::IsNullOrWhiteSpace($value)) { "" } else { "[set-redacted]" }
        } else {
            $snapshot[$name] = $value
        }
    }

    $snapshot["AZURE_OPENAI_API_KEY"] = if ([string]::IsNullOrWhiteSpace($env:AZURE_OPENAI_API_KEY)) { "" } else { "[set-redacted]" }
    return $snapshot
}

function Get-SignalText {
    param(
        $CurrentProposal,
        $LlmActivity,
        $RepairEvents,
        $DiagnosticArtifacts,
        $ApiMeta
    )

    $parts = New-Object System.Collections.Generic.List[string]

    try { $parts.Add(($CurrentProposal | ConvertTo-Json -Depth 80)) } catch {}
    try { $parts.Add(($LlmActivity | ConvertTo-Json -Depth 80)) } catch {}
    try { $parts.Add(($RepairEvents | ConvertTo-Json -Depth 80)) } catch {}
    try { $parts.Add(($DiagnosticArtifacts | ConvertTo-Json -Depth 80)) } catch {}
    try { $parts.Add(($ApiMeta | ConvertTo-Json -Depth 80)) } catch {}

    return ($parts -join "`n")
}

function Build-Http400Diagnosis {
    param(
        [AllowEmptyString()][string]$SignalText
    )

    $lower = $SignalText.ToLowerInvariant()
    $signals = New-Object System.Collections.Generic.List[string]
    $hypotheses = New-Object System.Collections.Generic.List[string]
    $nextChecks = New-Object System.Collections.Generic.List[string]

    if ($lower -match "http_400|status.?400|bad request|invalid_request") {
        $signals.Add("HTTP 400 / bad request detected. The provider rejected the request before a usable proposer response was produced.")
    }

    if ($lower -match "response_format|json_schema|structured output|structured_output") {
        $signals.Add("response_format/json_schema/structured-output signal detected.")
        $hypotheses.Add("The Azure/OpenAI deployment may reject the supplied response_format=json_schema payload, or the request schema shape is incompatible with the endpoint/model/API version.")
        $nextChecks.Add("Open 15-current-code-extracts.md and inspect v2_assistant_model_client.py around response_format/json_schema request construction.")
        $nextChecks.Add("Open 08-llm-activity.json and check response_format_used plus redacted_error.")
    }

    if ($lower -match "max_completion_tokens|max_output_tokens|too many tokens|maximum context|context length|token") {
        $signals.Add("Token budget signal detected.")
        $hypotheses.Add("The provider may reject 20000 output tokens or the selected max token parameter may be wrong for the active endpoint path.")
        $nextChecks.Add("Verify the active request path uses max_completion_tokens for Chat Completions and max_output_tokens for Responses API.")
        $nextChecks.Add("Temporarily lower output budget only for diagnosis if redacted_error proves provider token-limit rejection.")
    }

    if ($lower -match "reasoning_effort|unsupported parameter|unrecognized request argument|unknown parameter") {
        $signals.Add("Unsupported parameter signal detected.")
        $hypotheses.Add("The request may be sending reasoning_effort or another unsupported parameter to a model/provider that rejects it.")
        $nextChecks.Add("Check role config: reviewer reasoning must remain disabled for Llama-style reviewer; proposer/main should only send reasoning_effort when supported.")
    }

    if ($lower -match "schema|additionalproperties|strict|required|minlength|pattern") {
        $signals.Add("Schema validation / schema compatibility signal detected.")
        $hypotheses.Add("The JSON Schema may violate provider-supported schema restrictions, or strict mode may require additionalProperties=false / required fields alignment.")
        $nextChecks.Add("Inspect the exact schema in code extracts and any request/error artifact. Compare required/properties/additionalProperties.")
    }

    if ($lower -match "deployment|model|not found|does not support|unsupported model") {
        $signals.Add("Deployment/model support signal detected.")
        $hypotheses.Add("The selected deployment may not support the requested response format, endpoint type, reasoning parameter, or budget.")
        $nextChecks.Add("Check proposer/main deployment name and model capabilities in 20-safe-env-snapshot.json and /llm/activity.")
    }

    if ($signals.Count -eq 0) {
        $signals.Add("No specific HTTP 400 sub-signal found in captured API/activity/artifacts. Need backend terminal logs or request diagnostics.")
        $hypotheses.Add("The exact provider rejection body was not captured by the current APIs/artifacts.")
        $nextChecks.Add("Open backend terminal/log output around the proposer request timestamp.")
        $nextChecks.Add("Ensure v2_assistant_model_client records provider status code and response body redacted_error on HTTP failures.")
    }

    return [ordered]@{
        signals = @($signals)
        likely_hypotheses = @($hypotheses)
        next_checks = @($nextChecks | Select-Object -Unique)
    }
}

function Search-LocalLogSignals {
    param(
        [string[]]$Roots,
        [string]$JobId,
        [string]$JobPrefix
    )

    $matches = New-Object System.Collections.Generic.List[object]
    $patterns = @(
        [regex]::Escape($JobId),
        [regex]::Escape($JobPrefix),
        "http_400",
        "HTTP 400",
        "Bad Request",
        "response_format",
        "json_schema",
        "max_completion_tokens",
        "max_output_tokens",
        "reasoning_effort",
        "invalid_request",
        "repair_diagnostic_proposer",
        "PRIMARY_INVALID_RESPONSE",
        "reviewed_repair_unavailable"
    )

    $extensions = @("*.log", "*.txt", "*.json", "*.jsonl", "*.stderr", "*.out")

    foreach ($root in ($Roots | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }

        foreach ($ext in $extensions) {
            $files = @()
            try {
                $files = Get-ChildItem -LiteralPath $root -Recurse -File -Filter $ext -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending |
                    Select-Object -First 150
            } catch {
                $files = @()
            }

            foreach ($file in $files) {
                if ($matches.Count -ge 300) {
                    return @($matches)
                }

                try {
                    $content = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 -ErrorAction Stop
                    foreach ($pattern in $patterns) {
                        if ($content -match $pattern) {
                            $matches.Add([ordered]@{
                                file = $file.FullName
                                name = $file.Name
                                length = $file.Length
                                last_write_time = $file.LastWriteTime.ToString("s")
                                matched_pattern = $pattern
                                preview = Truncate-Text -Text $content -MaxChars 3000
                            })
                            break
                        }
                    }
                } catch {
                    # ignore unreadable files
                }
            }
        }
    }

    return @($matches)
}

# ---------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================"
Write-Host "AMF-252 JOB DEBUG PACK - HTTP 400 MODE"
Write-Host "JobId:    $JobId"
Write-Host "BaseUrl:  $BaseUrl"
Write-Host "RepoRoot: $RepoRoot"
Write-Host "OutDir:   $OutDir"
Write-Host "============================================================"
Write-Host ""

# ---------------------------------------------------------------------
# 1. API capture -- bounded
# ---------------------------------------------------------------------
$apiMeta = @()

$apiPaths = [ordered]@{
    "01-job" = "/v1/v2/migration-jobs/$JobId"
    "02-current-repair-proposal" = "/v1/v2/jobs/$JobId/repair/proposals/current"
    "03-failure-summary" = "/v1/v2/migration-jobs/$JobId/failure-summary"
    "04-pipeline" = "/v1/v2/migration-jobs/$JobId/pipeline"
    "05-stages" = "/v1/v2/migration-jobs/$JobId/stages"
    "06-events-snapshot" = "/v1/v2/migration-jobs/$JobId/events/snapshot?after=0"
    "07-repair-attempts" = "/v1/v2/jobs/$JobId/repair/attempts"
    "08-llm-activity" = "/v1/v2/jobs/$JobId/llm/activity"
    "09-gates" = "/v1/v2/jobs/$JobId/gates"
    "10-open-gate" = "/v1/v2/jobs/$JobId/gates/open"
    "11-approvals" = "/v1/v2/jobs/$JobId/approvals"
}

foreach ($name in $apiPaths.Keys) {
    $apiMeta += Invoke-ApiNoHang -Name $name -Path $apiPaths[$name]
}

Save-JsonObject -Name "19-api-metadata.json" -Data $apiMeta | Out-Null

# ---------------------------------------------------------------------
# 2. Parse core state
# ---------------------------------------------------------------------
$currentProposal = Load-JsonFile (Join-Path $OutDir "02-current-repair-proposal.json")
$failureSummary = Load-JsonFile (Join-Path $OutDir "03-failure-summary.json")
$pipeline = Load-JsonFile (Join-Path $OutDir "04-pipeline.json")
$eventsSnapshot = Load-JsonFile (Join-Path $OutDir "06-events-snapshot.json")
$repairAttempts = Load-JsonFile (Join-Path $OutDir "07-repair-attempts.json")
$llmActivity = Load-JsonFile (Join-Path $OutDir "08-llm-activity.json")

$proposal = Get-Prop $currentProposal "proposal"
$repairState = Get-Prop $currentProposal "repair_state"

$proposalPresent = $false
if ($null -ne $proposal) {
    $proposalPresent = $true
}

$repairStatus = ""
$reasonCode = ""
$detail = ""
$eventType = ""

if ($null -ne $repairState) {
    $repairStatus = [string](Get-Prop $repairState "status")
    $reasonCode = [string](Get-Prop $repairState "reason_code")
    $detail = [string](Get-Prop $repairState "detail")
    $eventType = [string](Get-Prop $repairState "event_type")
}

# ---------------------------------------------------------------------
# 3. Event classification
# ---------------------------------------------------------------------
$events = Get-Items $eventsSnapshot
$repairEvents = @()
$http400Events = @()
$repairRefEvents = @()

foreach ($ev in $events) {
    $type = [string](Get-Prop $ev "event_type")
    if (-not $type) {
        $type = [string](Get-Prop $ev "type")
    }

    $status = [string](Get-Prop $ev "status")
    $message = [string](Get-Prop $ev "message")
    $payload = Get-Prop $ev "payload"
    $payloadJson = ""
    try { $payloadJson = $payload | ConvertTo-Json -Depth 80 } catch { $payloadJson = "" }

    $eventText = "$type $status $message $payloadJson"

    if (
        $type -match "repair|review|proposal|validation|llm|diagnos|failed|failure" -or
        $status -match "failed|blocked|ready|unavailable|exhausted" -or
        $eventText -match "invalid_response|proposed_diff|review chain|repair|http_400|response_format|json_schema"
    ) {
        $repairEvents += $ev
    }

    if ($eventText -match "http_400|HTTP 400|Bad Request|invalid_request|response_format|json_schema|max_completion_tokens|max_output_tokens|reasoning_effort") {
        $http400Events += $ev
    }

    if ($eventText -match "_repair_|repair_failure_evidence|repair_context_pack|repair_run_dir") {
        $repairRefEvents += $ev
    }
}

Save-JsonObject -Name "12-repair-events.json" -Data $repairEvents | Out-Null
Save-JsonObject -Name "12a-http400-events.json" -Data $http400Events | Out-Null
Save-JsonObject -Name "12b-repair-ref-events.json" -Data $repairRefEvents | Out-Null

# ---------------------------------------------------------------------
# 4. Safe env snapshot
# ---------------------------------------------------------------------
$safeEnv = Get-SafeEnvSnapshot
Save-JsonObject -Name "20-safe-env-snapshot.json" -Data $safeEnv | Out-Null

# ---------------------------------------------------------------------
# 5. Discover run roots / diagnostic artifacts
# ---------------------------------------------------------------------
$runRoots = New-Object System.Collections.Generic.List[string]

# Correct known actual runtime root pattern:
# C:\Users\<user>\Desktop\modernized-v2-runs\.migration\runs\v2-<job-prefix>
$knownModernizedRuns = Join-Path (Join-Path $env:USERPROFILE "Desktop\modernized-v2-runs") ".migration\runs"
Add-RootIfExists -Roots $runRoots -Path $knownModernizedRuns

# Keep backward compatibility with any accidentally used old malformed root.
$legacyMalformedRoot = Join-Path (Join-Path $env:USERPROFILE "Desktop") "modernized-v2-runs.migration\runs"
Add-RootIfExists -Roots $runRoots -Path $legacyMalformedRoot

# Repo-local root.
$repoRuns = Join-Path $RepoRoot ".migration\runs"
Add-RootIfExists -Roots $runRoots -Path $repoRuns

# Logs root and repo root can contain stderr/json diagnostics too.
Add-RootIfExists -Roots $runRoots -Path $LogsRoot
Add-RootIfExists -Roots $runRoots -Path $RepoRoot

# Add exact v2-<prefix> directories if present.
if (Test-Path -LiteralPath $knownModernizedRuns -PathType Container) {
    try {
        $jobRunDirs = Get-ChildItem -LiteralPath $knownModernizedRuns -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "v2-$JobPrefix*" } |
            Sort-Object LastWriteTime -Descending
        foreach ($dir in $jobRunDirs) {
            Add-RootIfExists -Roots $runRoots -Path $dir.FullName
        }
    } catch {}
}

# Extract refs/dirs from all captured API responses.
$allApiObjects = @($currentProposal, $failureSummary, $pipeline, $eventsSnapshot, $repairAttempts, $llmActivity)
$dirPropNames = @(
    "_repair_run_dir", "repair_run_dir", "run_dir", "output_dir", "artifact_dir",
    "workspace_dir", "sandbox_path", "_repair_sandbox_path"
)
$fileRefNames = @(
    "_repair_failure_evidence_ref", "_repair_context_pack_ref",
    "failure_evidence_ref", "context_pack_ref", "repair_context_ref",
    "diff_ref", "artifact_ref", "ref", "path", "file_path", "diagnostic_ref"
)

foreach ($obj in $allApiObjects) {
    foreach ($val in (Find-ValuesByPropertyName -Object $obj -Names $dirPropNames)) {
        Add-RootIfExists -Roots $runRoots -Path ([string]$val)
    }

    foreach ($val in (Find-ValuesByPropertyName -Object $obj -Names $fileRefNames)) {
        $s = [string]$val
        if ($s -match "^[A-Za-z]:\\") {
            Add-ParentIfFileExists -Roots $runRoots -Path $s
            Add-RootIfExists -Roots $runRoots -Path $s
        }
    }
}

$runRootsUnique = @($runRoots | Select-Object -Unique)
Save-JsonObject -Name "15-searched-roots.json" -Data $runRootsUnique | Out-Null

$artifactIndex = @()
$diagnosticArtifacts = @()
$http400Artifacts = @()

$artifactNamePattern = "repair_diagnostic_proposer|primary_repair_llm_output|review_chain|final_reviewed_repair|repair_failure_evidence|repair_context_pack|llm|invocation|proposer|reviewer|http|azure|openai|request|response|error|diagnostic|structured|schema"
$contentSignalPattern = "$JobId|$JobPrefix|http_400|HTTP 400|Bad Request|invalid_request|response_format|json_schema|max_completion_tokens|max_output_tokens|reasoning_effort|PRIMARY_INVALID_RESPONSE|reviewed_repair_unavailable"

foreach ($root in $runRootsUnique) {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        continue
    }

    $candidateFiles = @()
    try {
        $candidateFiles = Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.FullName -match [regex]::Escape($JobPrefix) -or
                $_.Name -match $artifactNamePattern
            } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First $MaxArtifactFiles
    } catch {
        $candidateFiles = @()
    }

    foreach ($file in $candidateFiles) {
        $artifactIndex += [ordered]@{
            name = $file.Name
            path = $file.FullName
            root = $root
            length = $file.Length
            last_write_time = $file.LastWriteTime.ToString('s')
        }

        if ($file.Name -match "repair_diagnostic_proposer|primary_repair_llm_output|review_chain|repair_failure_evidence|repair_context_pack|final_reviewed_repair|invocation|llm|request|response|error") {
            $previewObj = Read-FilePreview -Path $file.FullName
            if ($null -ne $previewObj) {
                $diagnosticArtifacts += $previewObj

                $previewText = ""
                try { $previewText = $previewObj | ConvertTo-Json -Depth 80 } catch { $previewText = "" }
                if ($previewText -match $contentSignalPattern) {
                    $http400Artifacts += $previewObj
                }
            }
        }
    }
}

Save-JsonObject -Name "13-run-artifact-index.json" -Data $artifactIndex | Out-Null
Save-JsonObject -Name "14-diagnostic-artifacts.json" -Data $diagnosticArtifacts | Out-Null
Save-JsonObject -Name "14a-http400-artifacts.json" -Data $http400Artifacts | Out-Null

if ($diagnosticArtifacts.Count -eq 0) {
    Save-Text -Name "14-diagnostic-artifacts-notes.txt" -Text ("No diagnostic artifacts found. Searched roots:`n" + ($runRootsUnique -join "`n"))
    Write-Host "No diagnostic artifacts found. Searched roots were written to 14-diagnostic-artifacts-notes.txt" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------
# 6. Local log-like search
# ---------------------------------------------------------------------
$logSearchRoots = @(
    $OutDir,
    $LogsRoot,
    $RepoRoot,
    $knownModernizedRuns
) + $runRootsUnique

$localLogMatches = Search-LocalLogSignals -Roots $logSearchRoots -JobId $JobId -JobPrefix $JobPrefix
Save-JsonObject -Name "18-local-log-signal-matches.json" -Data $localLogMatches | Out-Null

# ---------------------------------------------------------------------
# 7. Current code extracts
# ---------------------------------------------------------------------
$codeExtract = New-Object System.Collections.Generic.List[string]
$codeExtract.Add("# AMF-252 Current Code Extracts")
$codeExtract.Add("")
$codeExtract.Add("Generated: $((Get-Date).ToString('s'))")
$codeExtract.Add("Job: $JobId")
$codeExtract.Add("")

$codeTargets = @(
    @{
        path = "migration_factory\orchestrator\repair_review_chain.py"
        patterns = @(
            "produce_repair_review_chain",
            "_coerce_primary_repair_output",
            "_validate_primary_repair_output",
            "repair_diagnostic_proposer",
            "invalid_response_missing_proposed_diff",
            "http_400",
            "proposed_diff",
            "RepairPrimaryOutput"
        )
    },
    @{
        path = "migration_factory\control_tower\application\v2_assistant_model_client.py"
        patterns = @(
            "_role_max_output_tokens",
            "_role_max_input_tokens",
            "_role_response_format",
            "response_format",
            "json_schema",
            "json_object",
            "max_completion_tokens",
            "max_output_tokens",
            "reasoning_effort",
            "http_400",
            "redacted_error",
            "fail_closed",
            "request",
            "payload"
        )
    },
    @{
        path = "migration_factory\control_tower\application\v2_model_role_router.py"
        patterns = @(
            "max_input",
            "max_output",
            "max_completion",
            "response_format",
            "json_schema",
            "supports_reasoning",
            "supports_structured"
        )
    },
    @{
        path = "migration_factory\control_tower\application\v2_settings.py"
        patterns = @(
            "MAX_INPUT",
            "MAX_OUTPUT",
            "MAX_COMPLETION",
            "RESPONSE_FORMAT",
            "JSON_SCHEMA",
            "REASONING_EFFORT"
        )
    },
    @{
        path = "migration_factory\control_tower\application\v2_repair_gate_service.py"
        patterns = @(
            "create_reviewed_repair_proposal_on_failure",
            "reviewed_repair_unavailable",
            "repair_completed",
            "REPAIR_BLOCKED",
            "PRIMARY_INVALID_RESPONSE",
            "http_400",
            "invocation_ledger",
            "repair_diagnostic_proposer"
        )
    },
    @{
        path = "migration_factory\control_tower\adapters\fastapi\app.py"
        patterns = @(
            "get_current_repair_proposal",
            "_build_repair_state_from_events",
            "llm/activity",
            "redacted_error",
            "repair_completed",
            "modernized-v2-runs",
            "reviewed_repair_unavailable"
        )
    },
    @{
        path = "migration_factory\control_tower\application\v2_llm_invocation_ledger.py"
        patterns = @(
            "redacted_error",
            "record",
            "failed",
            "response_format",
            "max_completion",
            "max_output",
            "to_dto"
        )
    },
    @{
        path = "migration_factory\control_tower\application\dto.py"
        patterns = @(
            "redacted_error",
            "LLM",
            "Invocation",
            "response_format",
            "max_completion",
            "max_output"
        )
    },
    @{
        path = "web\control-tower\app\migrations\[jobId]\RepairProposalPanel.tsx"
        patterns = @(
            "unavailable",
            "repairState",
            "Reviewed repair unavailable",
            "repairRefreshKey",
            "No apply action",
            "REPAIR_BLOCKED"
        )
    }
)

foreach ($target in $codeTargets) {
    $codeExtract.Add((Get-CodeExtract -RelativePath $target.path -Patterns $target.patterns -Context 20))
}

Save-Text -Name "15-current-code-extracts.md" -Text ($codeExtract -join "`n") | Out-Null

# ---------------------------------------------------------------------
# 8. Build specific diagnosis
# ---------------------------------------------------------------------
$llmInvocations = Get-Items $llmActivity
$failedInvocations = @()

foreach ($inv in $llmInvocations) {
    $status = [string](Get-Prop $inv "status")
    $err = [string](Get-Prop $inv "redacted_error")
    if ($status -match "failed|error" -or $err) {
        $failedInvocations += $inv
    }
}

$signalText = Get-SignalText -CurrentProposal $currentProposal -LlmActivity $llmActivity -RepairEvents $repairEvents -DiagnosticArtifacts $diagnosticArtifacts -ApiMeta $apiMeta
$http400Diagnosis = Build-Http400Diagnosis -SignalText $signalText
Save-JsonObject -Name "17-http400-diagnosis.json" -Data $http400Diagnosis | Out-Null

$rootCause = "UNKNOWN"

if ($detail -match "http_400" -or $signalText -match "http_400|HTTP 400|Bad Request|invalid_request") {
    $rootCause = "PRIMARY_MODEL_HTTP_400_REQUEST_REJECTED"
}
elseif ($reasonCode -eq "PRIMARY_INVALID_RESPONSE" -and $detail -match "missing_proposed_diff") {
    $rootCause = "PROPOSER_RETURNED_NO_USABLE_PROPOSED_DIFF"
}
elseif ($reasonCode -eq "PRIMARY_INVALID_RESPONSE") {
    $rootCause = "PROPOSER_INVALID_RESPONSE"
}
elseif ($repairStatus -eq "ready" -and $proposalPresent) {
    $rootCause = "REPAIR_PROPOSAL_READY"
}
elseif ($repairStatus -eq "blocked" -or $repairStatus -eq "unavailable") {
    $rootCause = "REPAIR_BLOCKED_OR_UNAVAILABLE"
}

$errorSignals = [ordered]@{
    job_id = $JobId
    root_cause = $rootCause
    proposal_present = $proposalPresent
    repair_status = $repairStatus
    reason_code = $reasonCode
    detail = $detail
    event_type = $eventType
    failed_invocations = $failedInvocations
    http400_events_count = $http400Events.Count
    http400_artifacts_count = $http400Artifacts.Count
    diagnostic_artifacts_count = $diagnosticArtifacts.Count
    local_log_signal_matches_count = $localLogMatches.Count
    http400_diagnosis = $http400Diagnosis
}
Save-JsonObject -Name "17-error-signals.json" -Data $errorSignals | Out-Null

# ---------------------------------------------------------------------
# 9. Summary JSON
# ---------------------------------------------------------------------
$summary = [ordered]@{
    job_id = $JobId
    inspected_at = (Get-Date).ToString('s')
    url = $JobUrl
    backend_base_url = $BaseUrl
    output_dir = $OutDir

    proposal_present = $proposalPresent
    repair_status = $repairStatus
    reason_code = $reasonCode
    detail = $detail
    event_type = $eventType
    root_cause = $rootCause

    repair_events_count = $repairEvents.Count
    http400_events_count = $http400Events.Count
    repair_ref_events_count = $repairRefEvents.Count
    llm_invocations_count = $llmInvocations.Count
    failed_llm_invocations_count = $failedInvocations.Count
    run_roots = $runRootsUnique
    artifact_index_count = $artifactIndex.Count
    diagnostic_artifacts_count = $diagnosticArtifacts.Count
    http400_artifacts_count = $http400Artifacts.Count
    local_log_signal_matches_count = $localLogMatches.Count

    http400_diagnosis = $http400Diagnosis

    next_actions = @(
        "Open 17-error-signals.json first.",
        "Open 17-http400-diagnosis.json to see whether the failure is response_format/json_schema, token budget, reasoning_effort, schema compatibility, or model/deployment support.",
        "Open 08-llm-activity.json and check redacted_error, response_format_used, configured token budget, model/deployment, and status.",
        "Open 14a-http400-artifacts.json for request/response/error artifacts related to HTTP 400.",
        "Open 15-current-code-extracts.md around v2_assistant_model_client.py request payload construction.",
        "If all artifacts are empty, inspect backend terminal output around the timestamp and make the model client persist provider error body."
    )
}
Save-JsonObject -Name "00-summary.json" -Data $summary | Out-Null

# ---------------------------------------------------------------------
# 10. Debug summary markdown
# ---------------------------------------------------------------------
$mdLines = New-Object System.Collections.Generic.List[string]
$mdLines.Add("# AMF-252 Job Debug Summary — HTTP 400 Mode")
$mdLines.Add("")
$mdLines.Add("Generated: $((Get-Date).ToString('s'))")
$mdLines.Add("")
$mdLines.Add("Job: $JobId")
$mdLines.Add("")
$mdLines.Add("URL: $JobUrl")
$mdLines.Add("")
$mdLines.Add("Output: $OutDir")
$mdLines.Add("")
$mdLines.Add("## Verdict")
$mdLines.Add("")
$mdLines.Add($rootCause)
$mdLines.Add("")
$mdLines.Add("## Current State")
$mdLines.Add("")
$mdLines.Add("- Proposal present: $proposalPresent")
$mdLines.Add("- Repair status: $repairStatus")
$mdLines.Add("- Reason code: $reasonCode")
$mdLines.Add("- Detail: $detail")
$mdLines.Add("- Event type: $eventType")
$mdLines.Add("- Repair events: $($repairEvents.Count)")
$mdLines.Add("- HTTP 400 events: $($http400Events.Count)")
$mdLines.Add("- Repair ref events: $($repairRefEvents.Count)")
$mdLines.Add("- LLM invocations: $($llmInvocations.Count)")
$mdLines.Add("- Failed LLM invocations: $($failedInvocations.Count)")
$mdLines.Add("- Diagnostic artifacts found: $($diagnosticArtifacts.Count)")
$mdLines.Add("- HTTP 400 artifacts found: $($http400Artifacts.Count)")
$mdLines.Add("- Local log signal matches: $($localLogMatches.Count)")
$mdLines.Add("")
$mdLines.Add("## What This Means")
$mdLines.Add("")
if ($rootCause -eq "PRIMARY_MODEL_HTTP_400_REQUEST_REJECTED") {
    $mdLines.Add("The UI/projection path is working: it correctly shows reviewed repair unavailable and no apply action.")
    $mdLines.Add("")
    $mdLines.Add("The current blocker is now the primary/proposer model request itself. HTTP 400 means the provider rejected the request before returning a usable repair proposal.")
    $mdLines.Add("")
    $mdLines.Add("Most likely buckets:")
    foreach ($h in $http400Diagnosis.likely_hypotheses) {
        $mdLines.Add("- $h")
    }
} else {
    $mdLines.Add("The current blocker is not proven to be HTTP 400 from captured data. Open 17-error-signals.json for exact signals.")
}
$mdLines.Add("")
$mdLines.Add("## Signals")
$mdLines.Add("")
foreach ($s in $http400Diagnosis.signals) {
    $mdLines.Add("- $s")
}
$mdLines.Add("")
$mdLines.Add("## Next Checks")
$mdLines.Add("")
foreach ($n in $http400Diagnosis.next_checks) {
    $mdLines.Add("- $n")
}
$mdLines.Add("")
$mdLines.Add("## Open These First")
$mdLines.Add("")
$mdLines.Add("1. 00-summary.json")
$mdLines.Add("2. 17-error-signals.json")
$mdLines.Add("3. 17-http400-diagnosis.json")
$mdLines.Add("4. 08-llm-activity.json")
$mdLines.Add("5. 14a-http400-artifacts.json")
$mdLines.Add("6. 14-diagnostic-artifacts.json")
$mdLines.Add("7. 12a-http400-events.json")
$mdLines.Add("8. 15-current-code-extracts.md")
$mdLines.Add("9. 18-local-log-signal-matches.json")
$mdLines.Add("10. 20-safe-env-snapshot.json")
$mdLines.Add("")
$mdLines.Add("## Important")
$mdLines.Add("")
$mdLines.Add("If 14a-http400-artifacts.json and 08-llm-activity.json do not contain the provider error body, fix v2_assistant_model_client.py to persist the provider HTTP 400 response body in a redacted diagnostic artifact.")

Save-Text -Name "16-debug-summary.md" -Text ($mdLines -join "`n") | Out-Null

# ---------------------------------------------------------------------
# 11. Console output
# ---------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================"
Write-Host "DONE - AMF-252 HTTP 400 DEBUG PACK"
Write-Host "============================================================"
Write-Host "Output: $OutDir" -ForegroundColor Cyan
Write-Host "Root cause: $rootCause"
Write-Host "Proposal present: $proposalPresent"
Write-Host "Repair status: $repairStatus"
Write-Host "Reason code: $reasonCode"
Write-Host "Detail: $detail"
Write-Host "Repair events: $($repairEvents.Count)"
Write-Host "HTTP 400 events: $($http400Events.Count)"
Write-Host "Repair ref events: $($repairRefEvents.Count)"
Write-Host "LLM invocations: $($llmInvocations.Count)"
Write-Host "Failed LLM invocations: $($failedInvocations.Count)"
Write-Host "Diagnostic artifacts: $($diagnosticArtifacts.Count)"
Write-Host "HTTP 400 artifacts: $($http400Artifacts.Count)"
Write-Host "Local log signal matches: $($localLogMatches.Count)"
Write-Host "Artifacts indexed: $($artifactIndex.Count)"

Write-Host ""
Write-Host "Open these first:"
Write-Host "$OutDir\16-debug-summary.md"
Write-Host "$OutDir\00-summary.json"
Write-Host "$OutDir\17-error-signals.json"
Write-Host "$OutDir\17-http400-diagnosis.json"
Write-Host "$OutDir\08-llm-activity.json"
Write-Host "$OutDir\14a-http400-artifacts.json"
Write-Host "$OutDir\15-current-code-extracts.md"
Write-Host "$OutDir\20-safe-env-snapshot.json"

if ($OpenFolder) {
    explorer.exe $OutDir
}
