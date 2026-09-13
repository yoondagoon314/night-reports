$ErrorActionPreference = 'Stop'
$exePath = Join-Path $PSScriptRoot 'MaisonNightReports.exe'
if (-not (Test-Path $exePath)) { throw 'Extract the complete Windows application folder before creating a shortcut.' }
$desktopPath = [Environment]::GetFolderPath('Desktop')
$linkPath = Join-Path $desktopPath 'MAISON Night Reports.lnk'
if (Test-Path $linkPath) { throw 'The MAISON Night Reports shortcut already exists. Remove it manually only if you intend to replace it.' }
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut($linkPath)
$shortcut.TargetPath = $exePath
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Check 23 Night Reports PDFs and prepare one Outlook draft'
$shortcut.Save()
Write-Host 'Desktop shortcut created.'
