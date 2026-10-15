# CI test of the real installer on a Windows runner: install silently, start GeoLock from
# its install folder, drive the backend the app started (first-run download, locate a
# photo), take screenshots of the window, then check that closing the app also stops the
# backend. Usage: pwsh tools/installer_test.ps1 <setup.exe> <screenshot folder>
param([string]$Setup, [string]$Shots)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Shots | Out-Null
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

function Shot($name) {
  $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
  $bmp.Save((Join-Path $Shots "$name.png"), [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  Write-Host "screenshot $name ($($b.Width)x$($b.Height))"
}

function Backend {
  Get-CimInstance Win32_Process -Filter "Name = 'geolock-backend.exe'" | Select-Object -First 1
}

Write-Host "Installing $Setup"
Start-Process $Setup -ArgumentList "/S" -Wait
$app = Get-ChildItem "$env:LOCALAPPDATA" -Recurse -Filter "GeoLock.exe" -ErrorAction SilentlyContinue |
  Select-Object -First 1
if (-not $app) { throw "GeoLock.exe not found after install" }
Write-Host "Installed: $($app.FullName)"
Get-ChildItem $app.DirectoryName | Format-Table Name, Length
$lnk = Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu" -Recurse -Filter "GeoLock*.lnk" -ErrorAction SilentlyContinue
Write-Host "Start menu shortcut: $($lnk.FullName)"

function Start-App {
  $p = Start-Process $app.FullName -PassThru
  $t = 0
  while (-not (Backend)) { Start-Sleep 1; $t++; if ($t -gt 60) { throw "the app did not start its backend" } }
  $cmd = (Backend).CommandLine
  $port = [regex]::Match($cmd, '--port (\d+)').Groups[1].Value
  $token = [regex]::Match($cmd, '--token (\w+)').Groups[1].Value
  Write-Host "app pid $($p.Id), backend on port $port"
  return @{ Proc = $p; Port = $port; Token = $token }
}

$a = Start-App
Start-Sleep 12
Shot "1-first-launch"
$job = Start-Job { param($dir, $port, $token)
  Set-Location $dir; python tools/desktop_smoke.py attach $port $token setup 2>&1 } -ArgumentList (Get-Location).Path, $a.Port, $a.Token
Start-Sleep 8
Shot "2-setup-running"
Receive-Job $job -Wait -AutoRemoveJob | Write-Host
Start-Sleep 5
Shot "3-ready"
python tools/desktop_smoke.py attach $a.Port $a.Token locate
if ($LASTEXITCODE -ne 0) { throw "locate failed" }

# Restart so the window shows the library with the analysed photo.
Stop-Process -Id $a.Proc.Id
Start-Sleep 5
if (Backend) { throw "the backend kept running after the app was closed" }
Write-Host "backend stopped with the app"
$a = Start-App
Start-Sleep 15
[void][System.Reflection.Assembly]::LoadWithPartialName("Microsoft.VisualBasic")
try { [Microsoft.VisualBasic.Interaction]::AppActivate($a.Proc.Id) } catch {}
Start-Sleep 1
[System.Windows.Forms.SendKeys]::SendWait("{DOWN}")
Start-Sleep 4
Shot "4-library"
python tools/desktop_smoke.py attach $a.Port $a.Token status
Stop-Process -Id $a.Proc.Id
Start-Sleep 3
Get-ChildItem "$env:LOCALAPPDATA\com.geolock.desktop\logs" -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "--- $($_.Name)"; Get-Content $_.FullName -Tail 30
}
Write-Host "installer test passed"
