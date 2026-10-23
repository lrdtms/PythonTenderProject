# Prove a backup restores (-Verify) or restore it into a Compose project (-Apply).
#   pwsh scripts/ops/restore.ps1 -Backup backups/<stamp> -Verify
#   pwsh scripts/ops/restore.ps1 -Backup backups/<stamp> -Apply -Project inteltps_gate `
#        -ComposeFile docker-compose.yml,docker-compose.restore-test.yml -BaseUrl http://127.0.0.1:8081
# -Verify restores into a scratch database and a scratch directory and compares them with the
# manifest; it never writes to the live database or volume.
# -Apply replaces the database and files of the named project. It refuses the live project
# (inteltps) unless -IKnowThisReplacesLiveData is also given.
param(
    [Parameter(Mandatory)][string]$Backup,
    [switch]$Verify,
    [switch]$Apply,
    [string]$Project = 'inteltps',
    [string[]]$ComposeFile = @('docker-compose.yml'),
    [string]$BaseUrl = 'http://127.0.0.1:8080',
    [switch]$IKnowThisReplacesLiveData
)
. "$PSScriptRoot/common.ps1"
$root = Get-RepoRoot
$LiveProject = 'inteltps'

if (($Verify -and $Apply) -or (-not $Verify -and -not $Apply)) { throw 'Give exactly one of -Verify or -Apply.' }
if ($Apply) {
    if (-not $PSBoundParameters.ContainsKey('Project')) { throw '-Apply needs -Project <name> so it is clear what is being replaced.' }
    if ($Project -eq $LiveProject -and -not $IKnowThisReplacesLiveData) {
        throw "Refusing to replace the live project '$LiveProject'. Restore into another project, or add -IKnowThisReplacesLiveData."
    }
}

if (-not [System.IO.Path]::IsPathRooted($Backup)) { $Backup = Join-Path $root $Backup }
if (-not (Test-Path (Join-Path $Backup 'manifest.json'))) { throw "No manifest.json in $Backup" }
foreach ($f in 'db.dump', 'files.tar.gz') {
    if (-not (Test-Path (Join-Path $Backup $f))) { throw "$f is missing from $Backup" }
}

Write-Step 'Checking the backup files against the manifest'
if ((Invoke-OpsPython 'ops_manifest.py' @('checksums', '--dir', $Backup)) -ne 0) {
    throw 'The backup files do not match their manifest. Do not restore from this backup.'
}

Set-ComposeTarget $Project $ComposeFile
Assert-Docker
$volume = Get-FilesVolume $Project
$user = $null
$name = $null
$scratchDb = 'inteltps_verify'
$scratchDir = $null

function Restore-Dump([string]$Database) {
    Invoke-Compose cp (Join-Path $Backup 'db.dump') db:/tmp/restore.dump
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy the dump into the container.' }
    Invoke-Compose exec -T db pg_restore -U $user -d $Database --no-owner /tmp/restore.dump
    if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed.' }
}

try {
    if ($Apply) {
        Write-Step "Creating the containers and volumes for project $Project"
        Invoke-Compose up -d --no-start | Out-Null
        Invoke-Compose up -d db | Out-Null
    }
    $deadline = (Get-Date).AddSeconds(60)
    do { try { Invoke-Psql 'SELECT 1;' | Out-Null; $up = $true } catch { $up = $false; Start-Sleep 2 } } until ($up -or (Get-Date) -gt $deadline)
    if (-not $up) { throw 'The database did not start.' }
    $user = (Invoke-Compose exec -T db printenv POSTGRES_USER).Trim()
    $name = (Invoke-Compose exec -T db printenv POSTGRES_DB).Trim()

    if ($Verify) {
        Write-Step "Restoring into scratch database $scratchDb"
        Invoke-Psql "DROP DATABASE IF EXISTS $scratchDb;" 'postgres' | Out-Null
        Invoke-Psql "CREATE DATABASE $scratchDb;" 'postgres' | Out-Null
        Restore-Dump $scratchDb
        $countsDb = $scratchDb
        $scratchDir = Join-Path ([System.IO.Path]::GetTempPath()) ("inteltps-verify-" + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $scratchDir | Out-Null
        Write-Step 'Extracting the files archive into a scratch directory'
        $out = docker run --rm -v "${Backup}:/in:ro" -v "${scratchDir}:/out" alpine sh -c 'tar xzf /in/files.tar.gz -C /out && find /out -type f | wc -l'
        if ($LASTEXITCODE -ne 0) { throw 'Extracting the files archive failed.' }
        $fileCount = [int]($out | Select-Object -Last 1).Trim()
    } else {
        Write-Step 'Stopping everything that uses the database'
        Invoke-Compose stop api worker web caddy | Out-Null
        Write-Step "Replacing database $name"
        Invoke-Psql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$name' AND pid <> pg_backend_pid();" 'postgres' | Out-Null
        Invoke-Psql "DROP DATABASE IF EXISTS $name;" 'postgres' | Out-Null
        Invoke-Psql "CREATE DATABASE $name;" 'postgres' | Out-Null
        Restore-Dump $name
        $countsDb = $name
        Write-Step "Replacing the files in volume $volume"
        $out = docker run --rm -v "${volume}:/data" -v "${Backup}:/in:ro" alpine sh -c 'find /data -mindepth 1 -delete && tar xzf /in/files.tar.gz -C /data && find /data -type f | wc -l'
        if ($LASTEXITCODE -ne 0) { throw 'Restoring the files failed.' }
        $fileCount = [int]($out | Select-Object -Last 1).Trim()
    }

    Write-Step 'Comparing with the manifest'
    $countsFile = Join-Path ([System.IO.Path]::GetTempPath()) ("inteltps-counts-" + [guid]::NewGuid().ToString('N') + '.tsv')
    Set-Content -Path $countsFile -Value (Get-TableCounts $countsDb) -Encoding utf8NoBOM
    try {
        $code = Invoke-OpsPython 'ops_manifest.py' @('verify', '--dir', $Backup, '--counts-tsv', $countsFile, '--file-count', "$fileCount")
    } finally { Remove-Item $countsFile -Force -ErrorAction SilentlyContinue }
    if ($code -ne 0) { throw 'The restore does NOT match the manifest.' }

    if ($Apply) {
        Write-Step 'Starting the stack (the api applies any newer migrations)'
        Invoke-Compose up -d | Out-Null
        Wait-Health $BaseUrl | Out-Null
        Write-Host "Restored into project $Project and healthy at $BaseUrl" -ForegroundColor Green
    } else {
        Write-Host 'Backup verified: it restores and matches its manifest. Live data was not touched.' -ForegroundColor Green
    }
} finally {
    if ($Verify) {
        try { Invoke-Psql "DROP DATABASE IF EXISTS $scratchDb;" 'postgres' | Out-Null } catch { }
        if ($scratchDir) {
            # Files extracted by the container are root-owned inside the bind mount; remove with it.
            docker run --rm -v "${scratchDir}:/out" alpine sh -c 'find /out -mindepth 1 -delete' *> $null
            Remove-Item $scratchDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    try { Invoke-Compose exec -T db rm -f /tmp/restore.dump | Out-Null } catch { }
}
