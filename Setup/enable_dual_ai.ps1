param(
    [string]$TargetDir = (Join-Path $PSScriptRoot "..\Bot Engine")
)

$ErrorActionPreference = "Stop"

$TargetDir = (Resolve-Path -Path $TargetDir).Path
Set-Location -Path $TargetDir

if (-not (Test-Path ".env")) {
    Write-Host ".env not found. Starting first-time setup first..."
    & "$PSScriptRoot\setup_env.ps1" -TargetDir $TargetDir
}

if (-not (Test-Path ".env")) {
    throw ".env still not found after setup."
}

$Lines = Get-Content -Path ".env"

function Set-DotEnvValue {
    param(
        [string[]]$Content,
        [string]$Key,
        [string]$Value
    )

    $Pattern = "^\s*$([regex]::Escape($Key))\s*="
    $Found = $false
    $Updated = foreach ($Line in $Content) {
        if ($Line -match $Pattern) {
            $Found = $true
            "$Key=$Value"
        }
        else {
            $Line
        }
    }

    if (-not $Found) {
        $Updated += "$Key=$Value"
    }

    return $Updated
}

$Lines = Set-DotEnvValue -Content $Lines -Key "AI_PROVIDER" -Value "openrouter"
$Lines = Set-DotEnvValue -Content $Lines -Key "AI_FALLBACK_PROVIDER" -Value "huggingface"
$Lines = Set-DotEnvValue -Content $Lines -Key "AI_MAIN_MODEL" -Value "openai/gpt-oss-20b:free"
$Lines = Set-DotEnvValue -Content $Lines -Key "AI_RISK_MODEL" -Value "openai/gpt-oss-120b:free"
$Lines = Set-DotEnvValue -Content $Lines -Key "AI_FALLBACK_MODEL" -Value "qwen/qwen3-next-80b-a3b-instruct:free"
$Lines = Set-DotEnvValue -Content $Lines -Key "HF_MAIN_MODEL" -Value "Qwen/Qwen3-4B-Instruct-2507"
$Lines = Set-DotEnvValue -Content $Lines -Key "HF_RISK_MODEL" -Value "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"
$Lines = Set-DotEnvValue -Content $Lines -Key "ENABLE_RISK_REVIEW" -Value "True"
$Lines = Set-DotEnvValue -Content $Lines -Key "AI_TIMEOUT" -Value "300"
$Lines = Set-DotEnvValue -Content $Lines -Key "AI_RETRIES" -Value "2"
$Lines = Set-DotEnvValue -Content $Lines -Key "AI_TEMPERATURE" -Value "0.1"
$Lines = Set-DotEnvValue -Content $Lines -Key "AI_MAX_TOKENS" -Value "256"

Set-Content -Path ".env" -Value $Lines -Encoding UTF8

Write-Host ".env updated for cloud dual AI on-demand mode."
Write-Host "Provider: openrouter"
Write-Host "Main model: openai/gpt-oss-20b:free"
Write-Host "Risk model: openai/gpt-oss-120b:free"
Write-Host "Risk review: True"
