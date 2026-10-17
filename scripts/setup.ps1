param([string]$Python = "python", [string]$Pnpm = "pnpm")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$detectedVersion = (& $Python --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Python not detected. Install Python 3.12 or 3.14 and retry." }
Write-Host "Detected $detectedVersion"
$requirements = if ($detectedVersion -match '^Python 3\.14\.') { "requirements-py314.txt" } else { "requirements.txt" }
if (Test-Path ".venv\Scripts\python.exe") {
  $existingVersion = (& ".\.venv\Scripts\python.exe" --version 2>&1 | Out-String).Trim()
  if ($existingVersion -ne $detectedVersion) {
    throw "Existing .venv uses $existingVersion, but selected interpreter uses $detectedVersion. Remove .venv manually if you want to replace it."
  }
} else {
  & $Python -m venv .venv
  if ($LASTEXITCODE -ne 0) { throw "Python venv creation failed." }
}
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
if ($requirements -eq "requirements-py314.txt") {
  & ".\.venv\Scripts\python.exe" -m pip install --only-binary=:all: -r $requirements
} else {
  & ".\.venv\Scripts\python.exe" -m pip install -r $requirements
}
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed. See installer output." }
& ".\.venv\Scripts\python.exe" -m pip check
if ($LASTEXITCODE -ne 0) { throw "Python dependency consistency check failed." }
& $Pnpm --dir apps/web install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
& $Pnpm --dir apps/web build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
Write-Host "Ready. Run: .\START-CIVICSIGNAL.bat"
