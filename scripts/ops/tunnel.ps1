# Cloudflare quick tunnel to the local stack (Caddy on 127.0.0.1:8080).
#   pwsh scripts/ops/tunnel.ps1 [-AcceptHostedLlm]
#   pwsh scripts/ops/tunnel.ps1 -Stop
param(
    [switch]$Stop,
    [switch]$AcceptHostedLlm
)
. "$PSScriptRoot/common.ps1"
$demo = Get-DemoDir
$pidFile = Join-Path $demo 'cloudflared.pid'
$urlFile = Join-Path $demo 'tunnel-url.txt'
$logFile = Join-Path $demo 'cloudflared.log'

function Stop-Tunnel {
    if (Test-Path $pidFile) {
        $p = Get-Process -Id ([int](Get-Content $pidFile -Raw)) -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -like 'cloudflared*') { Stop-Process -Id $p.Id -Force }
        Remove-Item $pidFile -Force
    }
    if (Test-Path $urlFile) { Remove-Item $urlFile -Force }
}

if ($Stop) { Stop-Tunnel; Write-Host 'Tunnel stopped.'; return }

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host 'cloudflared is not installed. Install it with: winget install --id Cloudflare.cloudflared' -ForegroundColor Red
    exit 2
}

Write-Step 'Checking configuration for a public tunnel'
if (-not (Invoke-Preflight -Tunnel -AcceptHostedLlm:$AcceptHostedLlm)) { exit 1 }

try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/v1/health' -TimeoutSec 5 | Out-Null
} catch {
    Write-Host 'The local stack is not answering on http://127.0.0.1:8080. Start it first.' -ForegroundColor Red
    exit 1
}

Stop-Tunnel
if (Test-Path $logFile) { Remove-Item $logFile -Force }
Write-Step 'Starting cloudflared'
$proc = Start-Process cloudflared -ArgumentList @('tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:8080') `
    -WindowStyle Hidden -RedirectStandardError $logFile -PassThru
Set-Content -Path $pidFile -Value $proc.Id

$url = $null
$deadline = (Get-Date).AddSeconds(30)
while (-not $url -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) { break }
    if (Test-Path $logFile) {
        $m = Select-String -Path $logFile -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value }
    }
}
if (-not $url) {
    Stop-Tunnel
    Write-Host 'cloudflared did not give a public address within 30 seconds. See .demo/cloudflared.log' -ForegroundColor Red
    exit 1
}

Write-Step "Checking $url"
$ok = $false
for ($i = 0; $i -lt 10 -and -not $ok; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "$url/api/v1/health" -TimeoutSec 10
        $ok = ($r.status -eq 'ok')
    } catch { Start-Sleep -Seconds 3 }
}
if (-not $ok) {
    Stop-Tunnel
    Write-Host 'The public address does not reach the app. The tunnel was stopped.' -ForegroundColor Red
    exit 1
}
Set-Content -Path $urlFile -Value $url
Write-Host "Public URL: $url" -ForegroundColor Green
