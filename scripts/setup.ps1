param([string]$Python = "python", [string]$Pnpm = "pnpm")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
& $Python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Python venv creation failed. Install a full Python 3.12 distribution, or use the bundled-runtime instructions in README.md." }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
& $Pnpm --dir apps/web install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
& $Pnpm --dir apps/web build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
Write-Host "Ready. Run: .\.venv\Scripts\python.exe scripts/run.py"
