# Back up the database and the stored files to backups/<UTC timestamp>/ with a manifest.
#   pwsh scripts/ops/backup.ps1 [-Project inteltps] [-OutDir backups] [-Quiesce]
# -Quiesce stops api and worker while the backup runs, so the row counts in the manifest are exact
# even if someone is using the app. Without it, back up while the stack is idle.
param(
    [string]$Project = 'inteltps',
    [string]$OutDir = 'backups',
    [string[]]$ComposeFile = @('docker-compose.yml'),
    [switch]$Quiesce
)
. "$PSScriptRoot/common.ps1"
$root = Get-RepoRoot
Set-ComposeTarget $Project $ComposeFile
Assert-Docker

if (-not [System.IO.Path]::IsPathRooted($OutDir)) { $OutDir = Join-Path $root $OutDir }
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd'T'HHmmss'Z'")
$dir = Join-Path $OutDir $stamp
New-Item -ItemType Directory -Path $dir -Force | Out-Null

$stopped = $false
$ok = $false
try {
    Write-Step 'Checking the database is running'
    Invoke-Psql 'SELECT 1;' | Out-Null

    if ($Quiesce) {
        Write-Step 'Pausing api and worker'
        Invoke-Compose stop api worker | Out-Null
        $stopped = $true
    }

    Write-Step 'Dumping the database'
    $user = (Invoke-Compose exec -T db printenv POSTGRES_USER).Trim()
    $name = (Invoke-Compose exec -T db printenv POSTGRES_DB).Trim()
    Invoke-Compose exec -T db pg_dump -Fc -U $user -d $name -f /tmp/backup.dump
    if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed.' }
    Invoke-Compose cp db:/tmp/backup.dump (Join-Path $dir 'db.dump')
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy the dump out of the container.' }
    Invoke-Compose exec -T db rm -f /tmp/backup.dump | Out-Null

    Write-Step 'Counting rows'
    $counts = Get-TableCounts
    Set-Content -Path (Join-Path $dir 'counts.tsv') -Value $counts -Encoding utf8NoBOM
    $head = (Invoke-Psql 'SELECT version_num FROM alembic_version;') | Select-Object -First 1

    Write-Step 'Archiving the stored files'
    $volume = Get-FilesVolume $Project
    docker volume inspect $volume *> $null
    if ($LASTEXITCODE -ne 0) { throw "The files volume $volume does not exist. Is the project name right?" }
    docker run --rm -v "${volume}:/data:ro" -v "${dir}:/out" alpine sh -c 'tar czf /out/files.tar.gz -C /data . && find /data -type f | wc -l > /out/file_count.txt'
    if ($LASTEXITCODE -ne 0) { throw 'Archiving the files failed.' }
    $fileCount = [int](Get-Content (Join-Path $dir 'file_count.txt') -Raw).Trim()

    Write-Step 'Writing the manifest'
    $commit = (git -C $root rev-parse --short HEAD 2>$null)
    if (-not $commit) { $commit = 'unknown' }
    $code = Invoke-OpsPython 'ops_manifest.py' @('write', '--dir', $dir, '--counts-tsv', (Join-Path $dir 'counts.tsv'),
        '--file-count', "$fileCount", '--alembic-head', $head, '--git-commit', $commit)
    if ($code -ne 0) { throw 'Writing the manifest failed.' }
    Remove-Item (Join-Path $dir 'file_count.txt') -Force

    $ok = $true
} finally {
    if ($stopped) { Invoke-Compose start api worker | Out-Null }
    if (-not $ok) {
        # A partial backup must not look like a real one.
        Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "Backup written to $dir" -ForegroundColor Green
Write-Host 'Copy it off this machine as well; a backup on the same disk does not survive the disk.'
Write-Output $dir
