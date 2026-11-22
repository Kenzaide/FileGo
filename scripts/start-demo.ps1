# Start FileGo. Streaming mode is the default because it is the mode used for the experiments
# and the live demo. Use -Stable for the waitress server.
param([switch]$Stable)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$py = Join-Path $backend '.venv\Scripts\python.exe'

if (-not (Test-Path $py) -or -not (Test-Path (Join-Path $root 'dist\index.html'))) {
    Write-Host 'First start: running setup ...' -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot 'setup.ps1')
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

Push-Location $backend
try {
    if ($Stable) { & $py run.py } else { & $py run.py --stream }
} finally { Pop-Location }
