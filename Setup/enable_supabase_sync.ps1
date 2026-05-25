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

function ConvertTo-DotEnvValue {
    param([string]$Value)
    if ($null -eq $Value) { return "" }
    $Text = [string]$Value
    if ($Text -match '[\s#"]') {
        $Escaped = $Text.Replace('\', '\\').Replace('"', '\"')
        return '"' + $Escaped + '"'
    }
    return $Text
}

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

Write-Host "Enable Supabase sync for Investment-AI_T."
Write-Host "Run Setup\supabase_schema.sql in Supabase SQL Editor first."
Write-Host "Never paste the service role key into Vercel/frontend."
Write-Host ""

$SupabaseUrl = Read-Host "Supabase project URL"
if ([string]::IsNullOrWhiteSpace($SupabaseUrl)) {
    throw "SUPABASE_URL is required."
}

$AnonKey = Read-Host "Supabase anon key"
if ([string]::IsNullOrWhiteSpace($AnonKey)) {
    throw "SUPABASE_ANON_KEY is required."
}

$ServiceRoleKey = Read-Host "Supabase service role key (backend only)"
if ([string]::IsNullOrWhiteSpace($ServiceRoleKey)) {
    throw "SUPABASE_SERVICE_ROLE_KEY is required for bot writes."
}

$MachineId = Read-Host "Machine ID [laptop-main]"
if ([string]::IsNullOrWhiteSpace($MachineId)) {
    $MachineId = "laptop-main"
}

$Lines = Get-Content -Path ".env"
$Lines = Set-DotEnvValue -Content $Lines -Key "SUPABASE_URL" -Value (ConvertTo-DotEnvValue $SupabaseUrl)
$Lines = Set-DotEnvValue -Content $Lines -Key "SUPABASE_ANON_KEY" -Value (ConvertTo-DotEnvValue $AnonKey)
$Lines = Set-DotEnvValue -Content $Lines -Key "SUPABASE_SERVICE_ROLE_KEY" -Value (ConvertTo-DotEnvValue $ServiceRoleKey)
$Lines = Set-DotEnvValue -Content $Lines -Key "SUPABASE_SYNC_ENABLED" -Value "True"
$Lines = Set-DotEnvValue -Content $Lines -Key "SUPABASE_MACHINE_ID" -Value (ConvertTo-DotEnvValue $MachineId)
$Lines = Set-DotEnvValue -Content $Lines -Key "SUPABASE_REQUEST_TIMEOUT" -Value "10"
$Lines = Set-DotEnvValue -Content $Lines -Key "PATTERN_USAGE_SYNC_ENABLED" -Value "True"
$Lines = Set-DotEnvValue -Content $Lines -Key "PATTERN_PRIMARY_LIMIT" -Value "1"
$Lines = Set-DotEnvValue -Content $Lines -Key "PATTERN_CONFLUENCE_LIMIT" -Value "8"
$Lines = Set-DotEnvValue -Content $Lines -Key "PATTERN_STATS_UPDATE_INTERVAL" -Value "10"

Set-Content -Path ".env" -Value $Lines -Encoding UTF8

Write-Host ""
Write-Host "Supabase sync enabled in Bot Engine\.env."
Write-Host "Next: deploy Dashboard\index.html to Vercel and paste only URL + anon key there."
