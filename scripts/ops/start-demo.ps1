# One command to bring the demo up: checks, model preload, stack, health, optional tunnel.
#   pwsh scripts/ops/start-demo.ps1 [-Tunnel] [-SkipModel] [-AcceptHostedLlm]
#   pwsh scripts/ops/start-demo.ps1 -Stop
param(
    [switch]$Tunnel,
    [switch]$SkipModel,
    [switch]$AcceptHostedLlm,
    [switch]$Stop
)
. "$PSScriptRoot/common.ps1"
$root = Get-RepoRoot
Set-Location $root

if ($Stop) {
    Write-Step 'Stopping the tunnel (if any) and the stack (data volumes are kept)'
    & "$PSScriptRoot/tunnel.ps1" -Stop
    docker compose down
    return
}

if (-not (Test-Path (Join-Path $root '.env'))) {
    throw 'No .env file. Copy .env.example to .env and set SECRET_KEY first.'
}

Write-Step 'Checking configuration'
if (-not (Invoke-Preflight -Tunnel:$Tunnel -AcceptHostedLlm:$AcceptHostedLlm)) {
    throw 'Fix the errors above, then run this again.'
}

Write-Step 'Checking Docker'
Assert-Docker

if (-not $SkipModel) {
    $model = Get-EnvValue 'LLM_MODEL' 'qwen3:4b'
    $hostUrl = (Get-EnvValue 'LLM_BASE_URL' 'http://host.docker.internal:11434') -replace 'host\.docker\.internal', '127.0.0.1'
    Write-Step "Checking the language model ($model)"
    try {
        $tags = Invoke-RestMethod -Uri "$hostUrl/api/tags" -TimeoutSec 5
    } catch {
        throw "Ollama is not reachable at $hostUrl. Start Ollama (it must listen on all interfaces: set OLLAMA_HOST=0.0.0.0)."
    }
    if (-not ($tags.models | Where-Object { $_.name -eq $model })) {
        throw "The model $model is not installed. Run: ollama pull $model"
    }
    Write-Step 'Loading the model into memory (kept for 30 minutes)'
    $body = @{ model = $model; keep_alive = '30m' } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri "$hostUrl/api/generate" -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 300 | Out-Null
}

Write-Step 'Starting the stack'
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'docker compose failed.' }

Write-Step 'Waiting for the stack to be healthy'
$status = Wait-Health
Write-Host "Server: $($status.api)  Database: $($status.database)  Model: $($status.model)"

$publicUrl = $null
if ($Tunnel) {
    Write-Step 'Opening the public tunnel'
    & "$PSScriptRoot/tunnel.ps1" -AcceptHostedLlm:$AcceptHostedLlm
    $urlFile = Join-Path (Get-DemoDir) 'tunnel-url.txt'
    if (Test-Path $urlFile) { $publicUrl = (Get-Content $urlFile -Raw).Trim() }
}

Write-Host ''
Write-Host 'The demo is up.' -ForegroundColor Green
Write-Host '  Local:   http://127.0.0.1:8080'
Write-Host '  Status:  http://127.0.0.1:8080/status'
if ($publicUrl) { Write-Host "  Public:  $publicUrl  (changes every time the tunnel restarts)" }
Write-Host ''
Write-Host 'Marking-window checklist:'
Write-Host '  [ ] Machine on, plugged in, sleep and hibernate off, Windows updates paused'
Write-Host '  [ ] Status page shows server, database and model working'
Write-Host '  [ ] The current public URL is posted in the submission, with a note that the demo runs on the developer machine'
Write-Host '  [ ] Synthetic data only while the tunnel is open'
Write-Host '  [ ] A screen recording of the full flow is saved as a backup'
Write-Host '  [ ] A backup was taken: pwsh scripts/ops/backup.ps1'
