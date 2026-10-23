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

# Runs the stdlib-only preflight with the project's Python. Returns $true when there are no errors.
function Invoke-Preflight([switch]$Tunnel, [switch]$AcceptHostedLlm) {
    $root = Get-RepoRoot
    $args = @('run', '--project', (Join-Path $root 'backend'), 'python', '-I', (Join-Path $root 'scripts/ops_preflight.py'), '--env-file', (Join-Path $root '.env'))
    if ($Tunnel) { $args += '--tunnel' }
    if ($AcceptHostedLlm) { $args += '--accept-hosted-llm' }
    & uv @args
    return ($LASTEXITCODE -eq 0)
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
