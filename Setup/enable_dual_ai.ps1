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

$Lines = Set-DotEnvValue -Content $Lines -Key "OLLAMA_MODEL" -Value "qwen2.5:7b"
$Lines = Set-DotEnvValue -Content $Lines -Key "OLLAMA_RISK_MODEL" -Value "deepseek-r1:8b"
$Lines = Set-DotEnvValue -Content $Lines -Key "ENABLE_RISK_REVIEW" -Value "True"
$Lines = Set-DotEnvValue -Content $Lines -Key "OLLAMA_KEEP_ALIVE" -Value "10m"
$Lines = Set-DotEnvValue -Content $Lines -Key "OLLAMA_TIMEOUT" -Value "300"
$Lines = Set-DotEnvValue -Content $Lines -Key "OLLAMA_NUM_CTX" -Value "4096"
$Lines = Set-DotEnvValue -Content $Lines -Key "OLLAMA_NUM_PREDICT" -Value "256"

Set-Content -Path ".env" -Value $Lines -Encoding UTF8

Write-Host ".env updated for dual AI on-demand mode."
Write-Host "Main model: qwen2.5:7b"
Write-Host "Risk model: deepseek-r1:8b"
Write-Host "Risk review: True"
Write-Host "Keep alive: 10m"
