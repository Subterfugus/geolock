# GeoLock one-time setup for Windows (PowerShell).
#   .\setup.ps1            # base install (CLIP + GeoCLIP on OpenVINO), ~2.5 GB download
#   .\setup.ps1 -Int8      # smaller/faster CLIP weights
#   .\setup.ps1 -Vlm       # also install the optional deep-analysis model (~6 GB more)
param([switch]$Int8, [switch]$Vlm)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-Python {
  foreach ($v in "3.12", "3.11", "3.10") {
    try { & py -$v -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { return @("py", "-$v") } } catch {}
  }
  try {
    $ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ($ver -in "3.10", "3.11", "3.12", "3.13") { return @("python") }
  } catch {}
  throw "Python 3.10-3.12 not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH') and re-run."
}

if (-not (Test-Path .venv)) {
  $py = Find-Python
  Write-Host "Creating virtual environment with $($py -join ' ')"
  if ($py.Count -gt 1) { & $py[0] $py[1] -m venv .venv } else { & $py[0] -m venv .venv }
}
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
$extras = "setup"
if ($Vlm) { $extras = "setup,vlm" }
& $python -m pip install -e ".[$extras]"
if ($LASTEXITCODE -ne 0) { throw "pip install failed (see the messages above)" }
& $python -m pip install geoclip --no-deps
if ($LASTEXITCODE -ne 0) { throw "pip install geoclip failed" }

$setupArgs = @()
if ($Int8) { $setupArgs += "--int8" }
if ($Vlm) { $setupArgs += "--vlm" }
& $python -m geolock.setup_models @setupArgs
if ($LASTEXITCODE -ne 0) { throw "Model setup failed" }

Write-Host ""
Write-Host "Done. Start GeoLock with:  .\run.bat   (or: .venv\Scripts\python -m geolock)"
