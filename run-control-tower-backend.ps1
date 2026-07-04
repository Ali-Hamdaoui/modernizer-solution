# =====================================================================
# AI Migration Control Tower — Clean Backend Launcher
# Windows / PowerShell
# =====================================================================

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------
# Repo
# ---------------------------------------------------------------------
$RepoRoot = "C:\Users\abdelilah.mortaki\Desktop\modernizer-solution"

if (-not (Test-Path -LiteralPath $RepoRoot -PathType Container)) {
    throw "Repo root not found: $RepoRoot"
}

Set-Location $RepoRoot
$env:PYTHONPATH = "."

# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------
function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Add-PathIfExists {
    param([Parameter(Mandatory = $true)][string]$PathToAdd)

    if (-not (Test-Path -LiteralPath $PathToAdd -PathType Container)) {
        throw "Required PATH entry does not exist: $PathToAdd"
    }

    $parts = $env:Path -split ";" | Where-Object { $_ -and $_.Trim() }
    if ($parts -notcontains $PathToAdd) {
        $env:Path = "$PathToAdd;$env:Path"
    }
}

function Assert-ValidHttpUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Name is empty."
    }

    if ($Value -like "*<*" -or $Value -like "*>*") {
        throw "$Name contains placeholder text."
    }

    $parsed = $null
    if (-not [System.Uri]::TryCreate($Value, [System.UriKind]::Absolute, [ref]$parsed)) {
        throw "$Name is not a valid absolute URI."
    }

    if ($parsed.Scheme -notin @("http", "https")) {
        throw "$Name must start with http or https."
    }

    return $parsed
}

# ---------------------------------------------------------------------
# Clear conflicting old provider/model env
# ---------------------------------------------------------------------
$VarsToClear = @(
    "AZURE_AI_PROJECT_ENDPOINT",
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_API_KEY",
    "AZURE_AI_API_KEY",
    "AZURE_OPENAI_API_VERSION",
    "MISTRAL_API_KEY",
    "MISTRAL_ENDPOINT",

    "AI_MIGRATION_MAIN_PROVIDER",
    "AI_MIGRATION_MAIN_MODEL",
    "AI_MIGRATION_MAIN_MODEL_DISPLAY_NAME",
    "AI_MIGRATION_MAIN_ENDPOINT_TYPE",
    "AI_MIGRATION_MAIN_RESPONSE_FORMAT",
    "AI_MIGRATION_MAIN_MAX_INPUT_TOKENS",
    "AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS",
    "AI_MIGRATION_MAIN_REASONING_EFFORT",
    "AI_MIGRATION_MAIN_TIMEOUT_SECONDS",

    "AI_MIGRATION_REVIEWER_PROVIDER",
    "AI_MIGRATION_REVIEWER_MODEL",
    "AI_MIGRATION_REVIEWER_MODEL_DISPLAY_NAME",
    "AI_MIGRATION_REVIEWER_ENDPOINT_TYPE",
    "AI_MIGRATION_REVIEWER_RESPONSE_FORMAT",
    "AI_MIGRATION_REVIEWER_MAX_INPUT_TOKENS",
    "AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS",
    "AI_MIGRATION_REVIEWER_REASONING_EFFORT",
    "AI_MIGRATION_REVIEWER_TIMEOUT_SECONDS",

    "AI_MIGRATION_FALLBACK_PROVIDER",
    "AI_MIGRATION_FALLBACK_MODEL",
    "AI_MIGRATION_FALLBACK_MODEL_DISPLAY_NAME",
    "AI_MIGRATION_FALLBACK_ENDPOINT_TYPE",
    "AI_MIGRATION_FALLBACK_RESPONSE_FORMAT",
    "AI_MIGRATION_FALLBACK_MAX_INPUT_TOKENS",
    "AI_MIGRATION_FALLBACK_MAX_OUTPUT_TOKENS",
    "AI_MIGRATION_FALLBACK_REASONING_EFFORT",
    "AI_MIGRATION_FALLBACK_TIMEOUT_SECONDS"
)

foreach ($var in $VarsToClear) {
    Remove-Item "Env:$var" -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------
# Azure OpenAI
# Endpoint = URL only.
# API key = secret only.
# ---------------------------------------------------------------------
Set-EnvValue "AZURE_OPENAI_ENDPOINT" "https://abdelilahmortaki-9971-resource.openai.azure.com/openai/v1"

$parsedEndpoint = Assert-ValidHttpUrl "AZURE_OPENAI_ENDPOINT" $env:AZURE_OPENAI_ENDPOINT

$secureAzureKey = Read-Host "Paste ROTATED Azure OpenAI API key" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureAzureKey)
try {
    $azureKeyPlain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}

if ([string]::IsNullOrWhiteSpace($azureKeyPlain)) {
    throw "AZURE_OPENAI_API_KEY is empty."
}

Set-EnvValue "AZURE_OPENAI_API_KEY" $azureKeyPlain

# ---------------------------------------------------------------------
# Role-based model config
# ---------------------------------------------------------------------
Set-EnvValue "AI_MIGRATION_DEFAULT_MAX_INPUT_TOKENS" "50000"
Set-EnvValue "AI_MIGRATION_DEFAULT_MAX_OUTPUT_TOKENS" "20000"

# MAIN / PROPOSER
Set-EnvValue "AI_MIGRATION_MAIN_PROVIDER" "azure_openai"
Set-EnvValue "AI_MIGRATION_MAIN_MODEL" "gpt-5-mini"
Set-EnvValue "AI_MIGRATION_MAIN_MODEL_DISPLAY_NAME" "GPT-5 mini"
Set-EnvValue "AI_MIGRATION_MAIN_ENDPOINT_TYPE" "chat_completions"
Set-EnvValue "AI_MIGRATION_MAIN_RESPONSE_FORMAT" "json_object"
Set-EnvValue "AI_MIGRATION_MAIN_MAX_INPUT_TOKENS" "50000"
Set-EnvValue "AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS" "20000"
Set-EnvValue "AI_MIGRATION_MAIN_REASONING_EFFORT" "medium"
Set-EnvValue "AI_MIGRATION_MAIN_TIMEOUT_SECONDS" "120"

# REVIEWER
Set-EnvValue "AI_MIGRATION_REVIEWER_PROVIDER" "azure_openai"
Set-EnvValue "AI_MIGRATION_REVIEWER_MODEL" "gpt-5-mini"
Set-EnvValue "AI_MIGRATION_REVIEWER_MODEL_DISPLAY_NAME" "GPT-5 mini Reviewer"
Set-EnvValue "AI_MIGRATION_REVIEWER_ENDPOINT_TYPE" "chat_completions"
Set-EnvValue "AI_MIGRATION_REVIEWER_RESPONSE_FORMAT" "json_object"
Set-EnvValue "AI_MIGRATION_REVIEWER_MAX_INPUT_TOKENS" "50000"
Set-EnvValue "AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS" "20000"
Set-EnvValue "AI_MIGRATION_REVIEWER_REASONING_EFFORT" "medium"
Set-EnvValue "AI_MIGRATION_REVIEWER_TIMEOUT_SECONDS" "120"

# FALLBACK
Set-EnvValue "AI_MIGRATION_FALLBACK_PROVIDER" "azure_openai"
Set-EnvValue "AI_MIGRATION_FALLBACK_MODEL" "gpt-5-mini"
Set-EnvValue "AI_MIGRATION_FALLBACK_MODEL_DISPLAY_NAME" "GPT-5 mini Fallback"
Set-EnvValue "AI_MIGRATION_FALLBACK_ENDPOINT_TYPE" "chat_completions"
Set-EnvValue "AI_MIGRATION_FALLBACK_RESPONSE_FORMAT" "json_object"
Set-EnvValue "AI_MIGRATION_FALLBACK_MAX_INPUT_TOKENS" "50000"
Set-EnvValue "AI_MIGRATION_FALLBACK_MAX_OUTPUT_TOKENS" "20000"
Set-EnvValue "AI_MIGRATION_FALLBACK_REASONING_EFFORT" "medium"
Set-EnvValue "AI_MIGRATION_FALLBACK_TIMEOUT_SECONDS" "120"

# Backward-compatible Azure deployment vars
Set-EnvValue "AZURE_OPENAI_ASSISTANT_DEPLOYMENT" "gpt-5-mini"
Set-EnvValue "AZURE_OPENAI_PROPOSER_DEPLOYMENT" "gpt-5-mini"
Set-EnvValue "AZURE_OPENAI_REVIEWER_DEPLOYMENT" "gpt-5-mini"
Set-EnvValue "AZURE_OPENAI_FALLBACK_DEPLOYMENT" "gpt-5-mini"
Set-EnvValue "AZURE_OPENAI_REASONING_EFFORT" "medium"

# ---------------------------------------------------------------------
# Java / Maven
# ---------------------------------------------------------------------
Set-EnvValue "JAVA11_HOME" "C:\Users\abdelilah.mortaki\.jdks\temurin-11.0.31"
Set-EnvValue "JAVA17_HOME" "C:\Users\abdelilah.mortaki\.jdks\ms-17.0.19"
Set-EnvValue "JAVA21_HOME" "C:\Program Files\Eclipse Adoptium\Temurin-21"

# Keep Java 17 default for current Control Tower runs unless intentionally testing Java 21.
Set-EnvValue "JAVA_HOME" $env:JAVA17_HOME

Set-EnvValue "MAVEN_HOME" "C:\Tools\apache-maven-3.9.15"
Set-EnvValue "MAVEN_CMD" "C:\Tools\apache-maven-3.9.15\bin\mvn.cmd"

# ---------------------------------------------------------------------
# Git / PATH
# AMF-237/238 happy path requires Git visible to backend.
# Do NOT hide Git.
# ---------------------------------------------------------------------
$GitCmd = "C:\Users\abdelilah.mortaki\AppData\Local\Programs\Git\cmd"
$GitBin = "C:\Users\abdelilah.mortaki\AppData\Local\Programs\Git\bin"
$JavaBin = "$env:JAVA_HOME\bin"
$MavenBin = "$env:MAVEN_HOME\bin"

Add-PathIfExists $JavaBin
Add-PathIfExists $MavenBin
Add-PathIfExists $GitCmd
Add-PathIfExists $GitBin

# ---------------------------------------------------------------------
# Reviewed repair policy
# ---------------------------------------------------------------------
Set-EnvValue "AI_MIGRATION_COPILOT_FAILURE_AGENT_ENABLED" "false"
Set-EnvValue "AI_MIGRATION_COPILOT_REQUIRED" "false"
Set-EnvValue "AI_MIGRATION_COPILOT_PROVIDER" ""
Set-EnvValue "AI_MIGRATION_COPILOT_MODEL" ""
Set-EnvValue "AI_MIGRATION_COPILOT_ASSIST" "off"
Set-EnvValue "AI_MIGRATION_ENABLE_COPILOT_REPORT" "false"

# Human approval required. No auto-apply.
Set-EnvValue "AI_MIGRATION_AUTO_APPLY_SAFE_REPAIRS" "false"

Set-EnvValue "AI_MIGRATION_H2_STARTUP_REQUIRED" "false"
Set-EnvValue "AI_MIGRATION_SKIP_ENDPOINT_SMOKE" "true"
Set-EnvValue "AI_MIGRATION_PROOF_LEVEL" "build_test_verified"
Set-EnvValue "AI_MIGRATION_ALLOW_GUARDED_SANDBOX_TRANSFORM" "true"

# ---------------------------------------------------------------------
# Safe verify
# ---------------------------------------------------------------------
"`n--- Runtime verify ---"

"Repo: $RepoRoot"
"Endpoint host: " + $parsedEndpoint.Host
"API key configured: " + [bool]$env:AZURE_OPENAI_API_KEY

"`nJava:"
java -version

"`nMaven:"
& $env:MAVEN_CMD -version

"`nGit:"
$gitWhere = where.exe git
$gitWhere

py -3 -c "import shutil, subprocess, sys; p=shutil.which('git'); print('git which:', p); sys.exit(1 if not p else 0)"
py -3 -c "import subprocess; r=subprocess.run(['git','--version'],capture_output=True,text=True); print(r.returncode, r.stdout.strip(), r.stderr); raise SystemExit(r.returncode)"

# ---------------------------------------------------------------------
# Live Azure smoke test
# If this fails, backend does NOT start.
# ---------------------------------------------------------------------
"`n--- Azure GPT smoke test ---"

$smokeHeaders = @{
    "api-key" = $env:AZURE_OPENAI_API_KEY
    "Content-Type" = "application/json"
}

$smokeBody = @{
    model = $env:AI_MIGRATION_MAIN_MODEL
    messages = @(
        @{
            role = "system"
            content = "You are a JSON-only assistant. Return valid JSON only."
        },
        @{
            role = "user"
            content = "Return only JSON with this exact shape: {`"ok`": true, `"model`": string}. No markdown."
        }
    )
    response_format = @{
        type = "json_object"
    }
    max_completion_tokens = 2000
} | ConvertTo-Json -Depth 20

try {
    $smoke = Invoke-RestMethod `
        -Method Post `
        -Uri "$env:AZURE_OPENAI_ENDPOINT/chat/completions" `
        -Headers $smokeHeaders `
        -Body $smokeBody
} catch {
    "Smoke test FAILED: " + $_.Exception.Message
    throw
}

if ($null -eq $smoke -or $null -eq $smoke.choices -or $smoke.choices.Count -eq 0) {
    throw "Smoke test returned no choices. Refusing to start backend."
}

$content = $smoke.choices[0].message.content
if ([string]::IsNullOrWhiteSpace($content)) {
    throw "Smoke test returned empty assistant content. Refusing to start backend."
}

try {
    $parsedSmoke = $content | ConvertFrom-Json
} catch {
    throw "Smoke test did not return valid JSON. Refusing to start backend."
}

if ($parsedSmoke.ok -ne $true) {
    throw "Smoke test JSON did not contain ok=true. Refusing to start backend."
}

"Smoke test OK: true"
"Smoke model: " + $smoke.model
"Smoke finish_reason: " + $smoke.choices[0].finish_reason

# ---------------------------------------------------------------------
# Start backend
# ---------------------------------------------------------------------
"`n--- Starting backend on http://127.0.0.1:8000 ---"
py -m uvicorn migration_factory.control_tower.adapters.fastapi.dev_app:app --host 127.0.0.1 --port 8000