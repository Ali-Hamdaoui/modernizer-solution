# =====================================================================
# AI Migration Control Tower — Minimal AMF-252 Backend Launcher
# Windows PowerShell 5.1
#
# Flow:
#   1. Validate repository branch and migration state
#   2. Configure AMF-252 environment
#   3. Make ONE tiny GPT-5 mini curl call
#   4. Print MODEL OK or MODEL WARNING
#   5. Start backend directly in foreground
#
# No Invoke-RestMethod for model smoke.
# No background jobs.
# No smoke matrix.
#
# The smoke uses temporary UTF-8 no-BOM request/response files to avoid
# Windows PowerShell 5.1 + native curl JSON quoting/BOM problems.
# =====================================================================

param(
    [switch]$SkipModelSmokeTest,
    [switch]$RequireSmokeSuccess
)

$ErrorActionPreference = "Stop"


# ---------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------

$RepoRoot = "C:\Users\abdelilah.mortaki\Desktop\modernizer-solution"

$ExpectedBranch = "feature/superposition-llm-repair-mvp"

$MigrationsDir = Join-Path `
    $RepoRoot `
    "migration_factory\control_tower\infrastructure\sqlite\migrations"

$ExpectedRepairMigrationName = `
    "0052_v2_repair_proposals_rule_id_risk.sql"

$OldConflictingRepairMigrationName = `
    "0050_v2_repair_proposals_rule_id_risk.sql"


if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
    throw "Repo root not found: $RepoRoot"
}

Set-Location $RepoRoot

$env:PYTHONPATH = "."


# ---------------------------------------------------------------------
# Local toolchain
# ---------------------------------------------------------------------

$Java11Home = "C:\Users\abdelilah.mortaki\.jdks\temurin-11.0.31"
$Java17Home = "C:\Users\abdelilah.mortaki\.jdks\ms-17.0.19"
$Java21Home = "C:\Program Files\Eclipse Adoptium\Temurin-21"

$MavenHome = "C:\Tools\apache-maven-3.9.15"

$GitCmd = "C:\Users\abdelilah.mortaki\AppData\Local\Programs\Git\cmd"
$GitBin = "C:\Users\abdelilah.mortaki\AppData\Local\Programs\Git\bin"


# ---------------------------------------------------------------------
# Azure / models
# ---------------------------------------------------------------------

$AzureOpenAIEndpoint = `
    "https://abdelilahmortaki-9971-resource.openai.azure.com/openai/v1"

$ProposerModel = "gpt-5-mini"
$MainModel = "gpt-5-mini"
$ReviewerModel = "Llama-3.3-70B-Instruct"
$FallbackModel = "gpt-5-mini"


# ---------------------------------------------------------------------
# AMF-252 model budgets
#
# Input:
#   50K configured input tokens.
#
# Output:
#   GPT-5 mini proposer  = 20,000
#   GPT-5 mini main      = 20,000
#   GPT-5 mini assistant = 20,000
#   Llama 3.3 reviewer   = 8,192
#   GPT-5 mini fallback  = 20,000
#
# Llama-3.3-70B-Instruct is configured separately because its documented
# maximum output is 8,192 tokens.
# ---------------------------------------------------------------------

$RoleMaxInputTokens = "50000"

$DefaultMaxOutputTokens = "20000"

$ProposerMaxOutputTokens = "20000"
$MainMaxOutputTokens = "20000"
$AssistantMaxOutputTokens = "20000"
$ReviewerMaxOutputTokens = "8192"
$FallbackMaxOutputTokens = "20000"

$RuntimeReasoningEffort = "medium"
$RuntimeResponseFormat = "json_schema"


# ---------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------

$BackendHost = "127.0.0.1"
$BackendPort = "8000"

$BackendUrl = "http://${BackendHost}:${BackendPort}"


# =====================================================================
# Helpers
# =====================================================================

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    [Environment]::SetEnvironmentVariable(
        $Name,
        $Value,
        "Process"
    )

    Set-Item `
        -Path "Env:$Name" `
        -Value $Value
}


function Convert-SecureStringToPlainText {
    param(
        [Parameter(Mandatory = $true)]
        [SecureString]$SecureValue
    )

    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR(
        $SecureValue
    )

    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}


function Assert-Directory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Name not found: $Path"
    }
}


function Assert-File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Name not found: $Path"
    }
}


function Assert-Command {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $command = Get-Command `
        $Name `
        -ErrorAction SilentlyContinue

    if ($null -eq $command) {
        throw "Required command not found on PATH: $Name"
    }
}


function Add-PathIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathToAdd
    )

    Assert-Directory `
        -Name "PATH entry" `
        -Path $PathToAdd

    $parts = $env:Path -split ";" |
        Where-Object {
            $_ -and $_.Trim()
        }

    if ($parts -notcontains $PathToAdd) {
        $env:Path = "$PathToAdd;$env:Path"
    }
}


function Assert-ExpectedBranch {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Expected
    )

    $branchOutput = & git branch --show-current

    if ($LASTEXITCODE -ne 0) {
        throw "Could not determine current Git branch."
    }

    $current = [string]$branchOutput
    $current = $current.Trim()

    if ([string]::IsNullOrWhiteSpace($current)) {
        throw "Current Git branch is empty or repository is in detached HEAD state."
    }

    if ($current -ne $Expected) {
        throw (
            "Wrong Git branch. " +
            "Expected '$Expected', current '$current'."
        )
    }

    return $current
}


function Assert-MigrationPreflight {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Directory,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedMigrationName,

        [Parameter(Mandatory = $true)]
        [string]$OldConflictingMigrationName
    )

    Assert-Directory `
        -Name "SQLite migrations directory" `
        -Path $Directory

    $expectedMigration = Join-Path `
        $Directory `
        $ExpectedMigrationName

    Assert-File `
        -Name "AMF-252 repair proposal migration" `
        -Path $expectedMigration


    $oldConflictingMigration = Join-Path `
        $Directory `
        $OldConflictingMigrationName

    if (Test-Path -LiteralPath $oldConflictingMigration -PathType Leaf) {
        throw (
            "Old conflicting migration still exists: " +
            $oldConflictingMigration
        )
    }


    $migrationRecords = @(
        Get-ChildItem `
            -LiteralPath $Directory `
            -Filter "*.sql" `
            -File |
        ForEach-Object {

            $match = [regex]::Match(
                $_.Name,
                '^(\d{4})_'
            )

            if ($match.Success) {
                [pscustomobject]@{
                    Version = [int]$match.Groups[1].Value
                    Name = $_.Name
                    FullName = $_.FullName
                }
            }
        }
    )


    if ($migrationRecords.Count -eq 0) {
        throw "No numbered SQLite migrations found in: $Directory"
    }


    $duplicateVersions = @(
        $migrationRecords |
        Group-Object `
            -Property Version |
        Where-Object {
            $_.Count -gt 1
        }
    )


    if ($duplicateVersions.Count -gt 0) {

        $duplicateDetails = @(
            $duplicateVersions |
            ForEach-Object {

                $names = (
                    $_.Group |
                    ForEach-Object {
                        $_.Name
                    }
                ) -join ", "

                "version $($_.Name): $names"
            }
        )

        throw (
            "Duplicate SQLite migration versions detected: " +
            ($duplicateDetails -join "; ")
        )
    }


    Write-Host ""
    Write-Host "Migration preflight OK" -ForegroundColor Green
    Write-Host (
        "Unique migration versions: " +
        $migrationRecords.Count
    )
    Write-Host (
        "Required migration found: " +
        $ExpectedMigrationName
    )
}


function Set-AzureRole {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Role,

        [Parameter(Mandatory = $true)]
        [string]$Model,

        [Parameter(Mandatory = $true)]
        [bool]$SupportsReasoning,

        [Parameter(Mandatory = $true)]
        [string]$MaxOutputTokens
    )

    $Prefix = "AZURE_OPENAI_$Role"

    Set-EnvValue "${Prefix}_DEPLOYMENT" $Model
    Set-EnvValue "${Prefix}_MODEL" $Model

    Set-EnvValue `
        "${Prefix}_MAX_INPUT_TOKENS" `
        $RoleMaxInputTokens

    Set-EnvValue `
        "${Prefix}_CONTEXT_TOKENS" `
        $RoleMaxInputTokens

    Set-EnvValue `
        "${Prefix}_MAX_CONTEXT_TOKENS" `
        $RoleMaxInputTokens

    Set-EnvValue `
        "${Prefix}_MAX_OUTPUT_TOKENS" `
        $MaxOutputTokens

    Set-EnvValue `
        "${Prefix}_MAX_COMPLETION_TOKENS" `
        $MaxOutputTokens

    Set-EnvValue `
        "${Prefix}_RESPONSE_FORMAT" `
        $RuntimeResponseFormat

    if ($SupportsReasoning) {

        Set-EnvValue `
            "${Prefix}_SUPPORTS_REASONING_EFFORT" `
            "true"

        Set-EnvValue `
            "${Prefix}_REASONING_EFFORT" `
            $RuntimeReasoningEffort
    }
    else {

        Set-EnvValue `
            "${Prefix}_SUPPORTS_REASONING_EFFORT" `
            "false"

        Set-EnvValue `
            "${Prefix}_REASONING_EFFORT" `
            ""
    }
}


function Set-MigrationRole {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Role,

        [Parameter(Mandatory = $true)]
        [string]$Model,

        [Parameter(Mandatory = $true)]
        [bool]$SupportsReasoning,

        [Parameter(Mandatory = $true)]
        [string]$MaxOutputTokens
    )

    $Prefix = "AI_MIGRATION_$Role"

    Set-EnvValue "${Prefix}_PROVIDER" "azure_openai"
    Set-EnvValue "${Prefix}_MODEL" $Model
    Set-EnvValue "${Prefix}_MODEL_DISPLAY_NAME" $Model
    Set-EnvValue "${Prefix}_ENDPOINT_TYPE" "chat_completions"

    Set-EnvValue `
        "${Prefix}_RESPONSE_FORMAT" `
        $RuntimeResponseFormat

    Set-EnvValue `
        "${Prefix}_SUPPORTS_JSON_OBJECT" `
        "true"

    Set-EnvValue `
        "${Prefix}_SUPPORTS_JSON_SCHEMA" `
        "true"

    Set-EnvValue `
        "${Prefix}_SUPPORTS_STRUCTURED_OUTPUTS" `
        "true"

    Set-EnvValue `
        "${Prefix}_SUPPORTS_TEMPERATURE" `
        "false"

    Set-EnvValue `
        "${Prefix}_MAX_INPUT_TOKENS" `
        $RoleMaxInputTokens

    Set-EnvValue `
        "${Prefix}_CONTEXT_TOKENS" `
        $RoleMaxInputTokens

    Set-EnvValue `
        "${Prefix}_MAX_CONTEXT_TOKENS" `
        $RoleMaxInputTokens

    Set-EnvValue `
        "${Prefix}_MAX_OUTPUT_TOKENS" `
        $MaxOutputTokens

    Set-EnvValue `
        "${Prefix}_MAX_COMPLETION_TOKENS" `
        $MaxOutputTokens

    Set-EnvValue `
        "${Prefix}_TIMEOUT_SECONDS" `
        "300"

    if ($SupportsReasoning) {

        Set-EnvValue `
            "${Prefix}_SUPPORTS_REASONING_EFFORT" `
            "true"

        Set-EnvValue `
            "${Prefix}_REASONING_EFFORT" `
            $RuntimeReasoningEffort
    }
    else {

        Set-EnvValue `
            "${Prefix}_SUPPORTS_REASONING_EFFORT" `
            "false"

        Set-EnvValue `
            "${Prefix}_REASONING_EFFORT" `
            ""
    }
}


# =====================================================================
# Model smoke helper
# =====================================================================

function Invoke-TinyGptSmoke {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Endpoint,

        [Parameter(Mandatory = $true)]
        [string]$Model
    )

    Write-Host ""
    Write-Host "------------------------------------------------------------"
    Write-Host "Tiny GPT-5 mini smoke call"
    Write-Host "------------------------------------------------------------"

    $url = "$($Endpoint.TrimEnd('/'))/chat/completions"

    $body = [ordered]@{
        model = $Model

        messages = @(
            [ordered]@{
                role = "user"
                content = "Reply with exactly OK."
            }
        )

        max_completion_tokens = 256
        reasoning_effort = "low"
    }

    $json = $body |
        ConvertTo-Json `
            -Depth 20 `
            -Compress


    $tempRequest = Join-Path `
        $env:TEMP `
        ("amf252-smoke-" + [guid]::NewGuid().ToString("N") + ".json")


    $tempResponse = Join-Path `
        $env:TEMP `
        ("amf252-smoke-response-" + [guid]::NewGuid().ToString("N") + ".json")


    $tempError = Join-Path `
        $env:TEMP `
        ("amf252-smoke-error-" + [guid]::NewGuid().ToString("N") + ".txt")


    try {

        $utf8NoBom = New-Object `
            System.Text.UTF8Encoding($false)


        [System.IO.File]::WriteAllText(
            $tempRequest,
            $json,
            $utf8NoBom
        )


        $firstBytes = [System.IO.File]::ReadAllBytes(
            $tempRequest
        )


        if (
            $firstBytes.Length -ge 3 -and
            $firstBytes[0] -eq 0xEF -and
            $firstBytes[1] -eq 0xBB -and
            $firstBytes[2] -eq 0xBF
        ) {
            throw "Smoke request unexpectedly contains UTF-8 BOM."
        }


        $curlArgs = @(
            "--silent",
            "--show-error",

            "--connect-timeout", "10",
            "--max-time", "30",

            "--http1.1",

            "-X", "POST",

            "-H", "Content-Type: application/json",
            "-H", "Accept: application/json",

            "-H", "api-key: $env:AZURE_OPENAI_API_KEY",

            "-o", $tempResponse,
            "-w", "%{http_code}",

            "--data-binary", "@$tempRequest",

            $url
        )


        $oldPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"


        try {

            $statusCode = [string](
                & curl.exe @curlArgs 2> $tempError
            )

            $statusCode = $statusCode.Trim()

            $curlExitCode = [int]$LASTEXITCODE
        }
        finally {

            $ErrorActionPreference = $oldPreference
        }


        $responseText = ""

        if (
            Test-Path `
                -LiteralPath $tempResponse `
                -PathType Leaf
        ) {

            $responseText = Get-Content `
                -LiteralPath $tempResponse `
                -Raw `
                -Encoding UTF8
        }


        $stderrText = ""

        if (
            Test-Path `
                -LiteralPath $tempError `
                -PathType Leaf
        ) {

            $stderrText = Get-Content `
                -LiteralPath $tempError `
                -Raw `
                -Encoding UTF8
        }


        if (
            $statusCode -match "^2" -and
            $curlExitCode -eq 0 -and
            -not [string]::IsNullOrWhiteSpace($responseText)
        ) {

            Write-Host ""
            Write-Host "MODEL OK" -ForegroundColor Green
            Write-Host "HTTP: $statusCode"


            try {

                $parsed = $responseText |
                    ConvertFrom-Json


                Write-Host "Model: $($parsed.model)"


                if (
                    $null -ne $parsed.choices -and
                    $parsed.choices.Count -gt 0
                ) {

                    Write-Host (
                        "Content: " +
                        [string]$parsed.choices[0].message.content
                    )

                    Write-Host (
                        "Finish reason: " +
                        [string]$parsed.choices[0].finish_reason
                    )
                }
            }
            catch {

                Write-Host (
                    "Response received but could not parse JSON."
                )
            }


            return $true
        }


        Write-Host ""
        Write-Host `
            "MODEL SMOKE WARNING" `
            -ForegroundColor Yellow

        Write-Host "HTTP: $statusCode"
        Write-Host "curl exit: $curlExitCode"


        if (
            -not [string]::IsNullOrWhiteSpace(
                $responseText
            )
        ) {

            Write-Host "Response:"
            Write-Host $responseText
        }


        if (
            -not [string]::IsNullOrWhiteSpace(
                $stderrText
            )
        ) {

            Write-Host "stderr:"
            Write-Host $stderrText
        }


        return $false
    }
    catch {

        Write-Host ""
        Write-Host `
            "MODEL SMOKE WARNING" `
            -ForegroundColor Yellow

        Write-Host $_.Exception.Message

        return $false
    }
    finally {

        Remove-Item `
            $tempRequest `
            -Force `
            -ErrorAction SilentlyContinue

        Remove-Item `
            $tempResponse `
            -Force `
            -ErrorAction SilentlyContinue

        Remove-Item `
            $tempError `
            -Force `
            -ErrorAction SilentlyContinue
    }
}


# =====================================================================
# Clear conflicting provider variables
# =====================================================================

$VarsToClear = @(
    "AZURE_AI_PROJECT_ENDPOINT",
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_API_KEY",
    "AZURE_AI_API_KEY",
    "AZURE_OPENAI_API_VERSION",
    "MISTRAL_API_KEY",
    "MISTRAL_ENDPOINT"
)


foreach ($var in $VarsToClear) {

    Remove-Item `
        "Env:$var" `
        -ErrorAction SilentlyContinue
}


# =====================================================================
# Azure OpenAI
# =====================================================================

Set-EnvValue `
    "AZURE_OPENAI_ENDPOINT" `
    $AzureOpenAIEndpoint


if (
    [string]::IsNullOrWhiteSpace(
        $env:AZURE_OPENAI_API_KEY
    )
) {

    $secureAzureKey = Read-Host `
        "Paste Azure OpenAI API key" `
        -AsSecureString


    $azureKeyPlain = Convert-SecureStringToPlainText `
        $secureAzureKey


    if (
        [string]::IsNullOrWhiteSpace(
            $azureKeyPlain
        )
    ) {

        throw "AZURE_OPENAI_API_KEY is empty."
    }


    Set-EnvValue `
        "AZURE_OPENAI_API_KEY" `
        $azureKeyPlain
}


# =====================================================================
# Azure role environment
# =====================================================================

Set-AzureRole `
    -Role "PROPOSER" `
    -Model $ProposerModel `
    -SupportsReasoning $true `
    -MaxOutputTokens $ProposerMaxOutputTokens


Set-AzureRole `
    -Role "MAIN" `
    -Model $MainModel `
    -SupportsReasoning $true `
    -MaxOutputTokens $MainMaxOutputTokens


Set-AzureRole `
    -Role "ASSISTANT" `
    -Model $MainModel `
    -SupportsReasoning $true `
    -MaxOutputTokens $AssistantMaxOutputTokens


Set-AzureRole `
    -Role "REVIEWER" `
    -Model $ReviewerModel `
    -SupportsReasoning $false `
    -MaxOutputTokens $ReviewerMaxOutputTokens


Set-AzureRole `
    -Role "FALLBACK" `
    -Model $FallbackModel `
    -SupportsReasoning $true `
    -MaxOutputTokens $FallbackMaxOutputTokens


# ---------------------------------------------------------------------
# Generic Azure defaults
# ---------------------------------------------------------------------

Set-EnvValue `
    "AZURE_OPENAI_REASONING_EFFORT" `
    $RuntimeReasoningEffort


Set-EnvValue `
    "AZURE_OPENAI_RESPONSE_FORMAT" `
    $RuntimeResponseFormat


Set-EnvValue `
    "AZURE_OPENAI_MAX_INPUT_TOKENS" `
    $RoleMaxInputTokens


Set-EnvValue `
    "AZURE_OPENAI_MAX_OUTPUT_TOKENS" `
    $DefaultMaxOutputTokens


Set-EnvValue `
    "AZURE_OPENAI_MAX_COMPLETION_TOKENS" `
    $DefaultMaxOutputTokens


# =====================================================================
# AI_MIGRATION role environment
# =====================================================================

Set-EnvValue `
    "AI_MIGRATION_DEFAULT_MAX_INPUT_TOKENS" `
    $RoleMaxInputTokens


Set-EnvValue `
    "AI_MIGRATION_DEFAULT_CONTEXT_TOKENS" `
    $RoleMaxInputTokens


Set-EnvValue `
    "AI_MIGRATION_DEFAULT_MAX_CONTEXT_TOKENS" `
    $RoleMaxInputTokens


Set-EnvValue `
    "AI_MIGRATION_DEFAULT_MAX_OUTPUT_TOKENS" `
    $DefaultMaxOutputTokens


Set-EnvValue `
    "AI_MIGRATION_DEFAULT_MAX_COMPLETION_TOKENS" `
    $DefaultMaxOutputTokens


Set-EnvValue `
    "AI_MIGRATION_DEFAULT_RESPONSE_FORMAT" `
    $RuntimeResponseFormat


Set-MigrationRole `
    -Role "MAIN" `
    -Model $MainModel `
    -SupportsReasoning $true `
    -MaxOutputTokens $MainMaxOutputTokens


Set-MigrationRole `
    -Role "PROPOSER" `
    -Model $ProposerModel `
    -SupportsReasoning $true `
    -MaxOutputTokens $ProposerMaxOutputTokens


Set-MigrationRole `
    -Role "REVIEWER" `
    -Model $ReviewerModel `
    -SupportsReasoning $false `
    -MaxOutputTokens $ReviewerMaxOutputTokens


Set-MigrationRole `
    -Role "FALLBACK" `
    -Model $FallbackModel `
    -SupportsReasoning $true `
    -MaxOutputTokens $FallbackMaxOutputTokens


# =====================================================================
# Java / Maven / Git
# =====================================================================

Assert-Directory `
    "JAVA11_HOME" `
    $Java11Home

Assert-Directory `
    "JAVA17_HOME" `
    $Java17Home

Assert-Directory `
    "JAVA21_HOME" `
    $Java21Home


Assert-Directory `
    "MAVEN_HOME" `
    $MavenHome

Assert-File `
    "MAVEN_CMD" `
    "$MavenHome\bin\mvn.cmd"


Assert-Directory `
    "Git cmd" `
    $GitCmd

Assert-Directory `
    "Git bin" `
    $GitBin

Assert-File `
    "Git executable" `
    "$GitCmd\git.exe"


Set-EnvValue `
    "JAVA11_HOME" `
    $Java11Home

Set-EnvValue `
    "JAVA17_HOME" `
    $Java17Home

Set-EnvValue `
    "JAVA21_HOME" `
    $Java21Home


# Backend default runtime = Java 17.

Set-EnvValue `
    "JAVA_HOME" `
    $Java17Home


Set-EnvValue `
    "MAVEN_HOME" `
    $MavenHome

Set-EnvValue `
    "MAVEN_CMD" `
    "$MavenHome\bin\mvn.cmd"


Add-PathIfExists `
    "$env:JAVA_HOME\bin"

Add-PathIfExists `
    "$env:MAVEN_HOME\bin"

Add-PathIfExists `
    $GitCmd

Add-PathIfExists `
    $GitBin


# =====================================================================
# Runtime preflight
# =====================================================================

Assert-Command "git.exe"
Assert-Command "curl.exe"
Assert-Command "py.exe"


$CurrentBranch = Assert-ExpectedBranch `
    -Expected $ExpectedBranch


Assert-MigrationPreflight `
    -Directory $MigrationsDir `
    -ExpectedMigrationName $ExpectedRepairMigrationName `
    -OldConflictingMigrationName $OldConflictingRepairMigrationName


# =====================================================================
# AMF-252 behavior flags
# =====================================================================

# ---------------------------------------------------------------------
# Copilot repair loop OFF
# ---------------------------------------------------------------------

Set-EnvValue `
    "AI_MIGRATION_COPILOT_FAILURE_AGENT_ENABLED" `
    "false"

Set-EnvValue `
    "AI_MIGRATION_COPILOT_REQUIRED" `
    "false"

Set-EnvValue `
    "AI_MIGRATION_COPILOT_PROVIDER" `
    ""

Set-EnvValue `
    "AI_MIGRATION_COPILOT_MODEL" `
    ""

Set-EnvValue `
    "AI_MIGRATION_COPILOT_ASSIST" `
    "off"

Set-EnvValue `
    "AI_MIGRATION_ENABLE_COPILOT_REPORT" `
    "false"


# ---------------------------------------------------------------------
# Human approval required for repair application
# ---------------------------------------------------------------------

Set-EnvValue `
    "AI_MIGRATION_AUTO_APPLY_SAFE_REPAIRS" `
    "false"


# ---------------------------------------------------------------------
# Existing runtime profile
# ---------------------------------------------------------------------

Set-EnvValue `
    "AI_MIGRATION_AUTO_APPROVAL_ENABLED" `
    "true"

Set-EnvValue `
    "AI_MIGRATION_H2_STARTUP_REQUIRED" `
    "false"

Set-EnvValue `
    "AI_MIGRATION_SKIP_ENDPOINT_SMOKE" `
    "true"

Set-EnvValue `
    "AI_MIGRATION_PROOF_LEVEL" `
    "build_test_verified"

Set-EnvValue `
    "AI_MIGRATION_ALLOW_GUARDED_SANDBOX_TRANSFORM" `
    "true"


# ---------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------

Set-EnvValue `
    "AI_MIGRATION_LOG_LEVEL" `
    "INFO"

Set-EnvValue `
    "AI_MIGRATION_REPAIR_TRACE" `
    "1"

Set-EnvValue `
    "AI_MIGRATION_REPAIR_DEBUG" `
    "1"

Set-EnvValue `
    "AI_MIGRATION_LLM_ACTIVITY_DIAGNOSTICS" `
    "1"


# =====================================================================
# Runtime summary
# =====================================================================

Write-Host ""
Write-Host "============================================================"
Write-Host "AMF-252 MINIMAL BACKEND LAUNCHER"
Write-Host "============================================================"

Write-Host "Repo:               $RepoRoot"
Write-Host "Branch:             $CurrentBranch"

Write-Host "Endpoint:           $AzureOpenAIEndpoint"

Write-Host ""
Write-Host "Models:"
Write-Host "  Proposer:         $ProposerModel"
Write-Host "  Main:             $MainModel"
Write-Host "  Reviewer:         $ReviewerModel"
Write-Host "  Fallback:         $FallbackModel"

Write-Host ""
Write-Host "Input budget:"
Write-Host "  All roles:        $RoleMaxInputTokens"

Write-Host ""
Write-Host "Output budgets:"
Write-Host "  Proposer:         $ProposerMaxOutputTokens"
Write-Host "  Main:             $MainMaxOutputTokens"
Write-Host "  Assistant:        $AssistantMaxOutputTokens"
Write-Host "  Reviewer:         $ReviewerMaxOutputTokens"
Write-Host "  Fallback:         $FallbackMaxOutputTokens"

Write-Host ""
Write-Host "Structured output:"
Write-Host "  Response format:  $RuntimeResponseFormat"

Write-Host ""
Write-Host "Reasoning:"
Write-Host "  Proposer:         $RuntimeReasoningEffort"
Write-Host "  Main:             $RuntimeReasoningEffort"
Write-Host "  Assistant:        $RuntimeReasoningEffort"
Write-Host "  Reviewer:         disabled / omitted"
Write-Host "  Fallback:         $RuntimeReasoningEffort"

Write-Host ""
Write-Host "Timeout:"
Write-Host "  Proposer:         300 seconds"
Write-Host "  Reviewer:         300 seconds"

Write-Host ""
Write-Host "Migration preflight:"
Write-Host "  Expected file:    $ExpectedRepairMigrationName"
Write-Host "  Duplicate check:  passed"

Write-Host ""
Write-Host "Toolchain:"
Write-Host "  JAVA_HOME:        $env:JAVA_HOME"
Write-Host "  MAVEN_CMD:        $env:MAVEN_CMD"

Write-Host ""
Write-Host "Repair policy:"
Write-Host "  Copilot repair:   disabled"
Write-Host "  Auto repair apply: disabled"
Write-Host "  Human approval:   required"

Write-Host ""
Write-Host "Backend URL:        $BackendUrl"

Write-Host ""


# =====================================================================
# Model smoke
# =====================================================================

$modelSmokePassed = $true


if (-not $SkipModelSmokeTest) {

    $modelSmokePassed = Invoke-TinyGptSmoke `
        -Endpoint $AzureOpenAIEndpoint `
        -Model $ProposerModel
}
else {

    Write-Host ""
    Write-Host `
        "Model smoke skipped." `
        -ForegroundColor Yellow
}


if (-not $modelSmokePassed) {

    if ($RequireSmokeSuccess) {

        throw (
            "Model smoke failed and " +
            "-RequireSmokeSuccess was requested. " +
            "Backend not started."
        )
    }


    Write-Host ""

    Write-Host `
        "Smoke failed, but backend startup will continue." `
        -ForegroundColor Yellow
}


# =====================================================================
# Start backend directly
#
# IMPORTANT:
# This runs Uvicorn in the foreground.
#
# The PowerShell window stays open.
# Backend logs remain visible.
# No hidden process.
# No background job.
# =====================================================================

Write-Host ""
Write-Host "============================================================"
Write-Host "STARTING BACKEND"
Write-Host "============================================================"

Write-Host "URL:     $BackendUrl"

Write-Host ""

Write-Host "The backend is running when Uvicorn prints:"

Write-Host (
    "Uvicorn running on " +
    "http://${BackendHost}:${BackendPort}"
)

Write-Host ""


py -m uvicorn `
    migration_factory.control_tower.adapters.fastapi.dev_app:app `
    --host $BackendHost `
    --port $BackendPort `
    --log-level info


$BackendExitCode = $LASTEXITCODE


if ($BackendExitCode -ne 0) {

    Write-Host ""

    Write-Host `
        "BACKEND EXITED WITH ERROR" `
        -ForegroundColor Red

    Write-Host "Exit code: $BackendExitCode"

    exit $BackendExitCode
}


exit 0