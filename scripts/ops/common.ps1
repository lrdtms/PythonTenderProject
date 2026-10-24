# Shared helpers for the ops scripts. Dot-source it: . "$PSScriptRoot/common.ps1"
# PowerShell 7. Nothing here prints a secret.

$ErrorActionPreference = 'Stop'

function Get-RepoRoot { Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Warn([string]$Message) { Write-Host "warning: $Message" -ForegroundColor Yellow }

# Value of KEY in the repo's .env, or $Default. Comments, quotes and "export " are handled.
function Get-EnvValue([string]$Name, [string]$Default = '') {
    $file = Join-Path (Get-RepoRoot) '.env'
    if (-not (Test-Path $file)) { return $Default }
    foreach ($raw in Get-Content $file) {
        $line = $raw.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { continue }
        if ($line.StartsWith('export ')) { $line = $line.Substring(7) }
        $i = $line.IndexOf('=')
        if ($i -lt 1) { continue }
        if ($line.Substring(0, $i).Trim() -ne $Name) { continue }
        $value = $line.Substring($i + 1).Trim()
        if ($value.Length -ge 2 -and $value[0] -eq $value[-1] -and ($value[0] -eq '"' -or $value[0] -eq "'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        return $value
    }
    return $Default
}

function Assert-Docker {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker is not running. Start Docker Desktop and try again.' }
}

# Runs the stdlib-only preflight with the project's Python and shows its findings. Returns a
# plain $true / $false (the tool's output goes to the console, never into the return value).
function Invoke-Preflight([switch]$Tunnel, [switch]$AcceptHostedLlm, [string]$EnvFile = '') {
    $root = Get-RepoRoot
    if ($EnvFile -eq '') { $EnvFile = Join-Path $root '.env' }
    $uvArgs = @('run', '--project', (Join-Path $root 'backend'), 'python', '-I', (Join-Path $root 'scripts/ops_preflight.py'), '--env-file', $EnvFile)
    if ($Tunnel) { $uvArgs += '--tunnel' }
    if ($AcceptHostedLlm) { $uvArgs += '--accept-hosted-llm' }
    & uv @uvArgs | Out-Host
    return [bool]($LASTEXITCODE -eq 0)
}

# Poll the public status endpoint until the database reports ok.
function Wait-Health([string]$BaseUrl = 'http://127.0.0.1:8080', [int]$TimeoutSec = 180) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-RestMethod -Uri "$BaseUrl/api/v1/health/status" -TimeoutSec 5
            if ($r.database -eq 'ok') { return $r }
        } catch { }
        Start-Sleep -Seconds 3
    }
    throw "The stack did not become healthy within $TimeoutSec seconds. Run: docker compose logs api"
}

function Get-DemoDir {
    $dir = Join-Path (Get-RepoRoot) '.demo'
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    return $dir
}

# ---- Compose and database helpers (backup / restore) ------------------------------------------

$script:Compose = @()

# Select the Compose project (and optional extra -f files) for every Invoke-Compose call.
function Set-ComposeTarget([string]$Project, [string[]]$ComposeFile = @('docker-compose.yml')) {
    $script:Compose = @('compose', '-p', $Project)
    # `pwsh -File` hands a comma list over as one string, so split it here.
    foreach ($f in ($ComposeFile | ForEach-Object { $_ -split ',' } | Where-Object { $_ })) {
        $script:Compose += @('-f', (Join-Path (Get-RepoRoot) $f.Trim()))
    }
}

function Invoke-Compose { & docker @script:Compose @args }

# Run psql in the db container, SQL from stdin (no shell quoting). Returns output lines.
function Invoke-Psql([string]$Sql, [string]$Database = '') {
    $user = (Invoke-Compose exec -T db printenv POSTGRES_USER).Trim()
    if ($Database -eq '') { $Database = (Invoke-Compose exec -T db printenv POSTGRES_DB).Trim() }
    $out = $Sql | & docker @script:Compose exec -T db psql -v ON_ERROR_STOP=1 -U $user -d $Database -At -F "`t"
    if ($LASTEXITCODE -ne 0) { throw "psql failed: $Sql" }
    return $out
}

# One "table<TAB>rows" line per public table, exact counts.
function Get-TableCounts([string]$Database = '') {
    $sql = "SELECT table_name, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1;"
    return Invoke-Psql $sql $Database
}

# Run a Python tool from scripts/ with the project's interpreter.
function Invoke-OpsPython([string]$Script, [string[]]$ScriptArgs) {
    $root = Get-RepoRoot
    & uv run --project (Join-Path $root 'backend') python -I (Join-Path $root "scripts/$Script") @ScriptArgs | Out-Host
    return $LASTEXITCODE
}

function Get-FilesVolume([string]$Project) { "${Project}_files" }
