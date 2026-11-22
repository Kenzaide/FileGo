# One-time setup for the FileGo demo on Windows.
# Creates the Python environment, installs the backend packages, builds the web interface
# and creates the demo accounts. Safe to run again.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$venv = Join-Path $backend '.venv'
$py = Join-Path $venv 'Scripts\python.exe'

function Fail($message) { Write-Host ''; Write-Host "ERROR: $message" -ForegroundColor Red; exit 1 }

Write-Host '== FileGo setup ==' -ForegroundColor Cyan

# 1. Python 3.11 or newer
$launcher = $null
foreach ($candidate in @('py', 'python')) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) { $launcher = $candidate; break }
}
if (-not $launcher) { Fail 'Python was not found. Install Python 3.11 or newer from python.org and tick "Add python.exe to PATH".' }
if ($launcher -eq 'py') { $version = & py -3 -c "import sys; print('%d.%d' % sys.version_info[:2])" } else { $version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" }
Write-Host "Python $version found."
$parts = $version.Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) { Fail "Python 3.11 or newer is required (found $version)." }

# 2. Virtual environment and packages
if (-not (Test-Path $py)) {
    Write-Host 'Creating the Python environment (backend\.venv) ...'
    if ($launcher -eq 'py') { & py -3 -m venv $venv } else { & python -m venv $venv }
    if ($LASTEXITCODE -ne 0) { Fail 'Could not create the Python environment.' }
}
Write-Host 'Installing backend packages ...'
& $py -m pip install --quiet --disable-pip-version-check -r (Join-Path $backend 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'pip install failed. Check your internet connection and try again.' }

# 3. Web interface
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Fail 'Node.js was not found. Install Node.js 20 or newer from nodejs.org.' }
Push-Location $root
try {
    Write-Host 'Installing web interface packages ...'
    npm install --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { Fail 'npm install failed.' }
    Write-Host 'Building the web interface ...'
    npm run build
    if ($LASTEXITCODE -ne 0) { Fail 'npm run build failed.' }
} finally { Pop-Location }

# 4. Demo accounts (only when there is no database yet, so real data is never touched)
Push-Location $backend
try {
    if (-not (Test-Path (Join-Path $backend 'filego.db'))) {
        Write-Host 'Creating the demo accounts ...'
        & $py seed.py
        if ($LASTEXITCODE -ne 0) { Fail 'Could not create the demo accounts.' }
    } else {
        Write-Host 'Database already exists: demo accounts left as they are.'
    }
} finally { Pop-Location }

Write-Host ''
Write-Host 'Setup finished. Start the server with start-demo.bat' -ForegroundColor Green
