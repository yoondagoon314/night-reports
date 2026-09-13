# Run on an approved Windows build PC with Python 3.12 (64-bit) installed.
# Builds a portable folder, not an installer. No guest PDF files are included.
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Build this package on Windows.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $buildTag = Get-Date -Format 'yyyyMMdd-HHmmss'
    $venvRoot = Join-Path $projectRoot '.venv-build'
    if (-not (Test-Path "$venvRoot\Scripts\python.exe")) {
        & python -m venv $venvRoot
        if ($LASTEXITCODE -ne 0) { throw 'Install 64-bit Python 3.12 and put it on PATH on the build PC.' }
    }
    $buildPython = Join-Path $venvRoot 'Scripts\python.exe'
    & $buildPython -c "import sys,struct; assert sys.platform == 'win32' and struct.calcsize('P') == 8, '64-bit Windows Python required'"
    if ($LASTEXITCODE -ne 0) { throw 'Python compatibility check failed.' }
    & $buildPython -m pip install -r requirements-build.txt -r requirements-test.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $releaseRoot = Join-Path $projectRoot "releases\$buildTag"
    New-Item -ItemType Directory -Path $releaseRoot | Out-Null
    $env:MAISON_GUI_TESTS = '1'
    & $buildPython scripts\run_tests.py "$releaseRoot\windows-test-results.txt"
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; no application will be packaged.' }
    & $buildPython -m PyInstaller --noconfirm --onedir --windowed --name MaisonNightReports --paths . --hidden-import win32timezone --distpath $releaseRoot --workpath ".build\$buildTag" --specpath ".build\$buildTag" run_app.py
    if ($LASTEXITCODE -ne 0) { throw 'Windows packaging failed.' }
    $portableRoot = Join-Path $releaseRoot 'MaisonNightReports'
    $probePath = Join-Path $releaseRoot 'packaged-self-test.json'
    $exePath = Join-Path $portableRoot 'MaisonNightReports.exe'
    $probe = Start-Process -FilePath $exePath -ArgumentList @('--self-test', ('"' + $probePath + '"')) -Wait -PassThru
    if ($probe.ExitCode -ne 0 -or -not (Test-Path $probePath)) { throw 'Packaged application smoke test failed.' }
    $probeResult = Get-Content $probePath -Raw | ConvertFrom-Json
    if ($probeResult.result -ne 'PASS' -or -not $probeResult.frozen) { throw 'Packaged runtime check did not pass.' }
    Copy-Item $probePath $portableRoot
    Copy-Item README.md $portableRoot
    Copy-Item docs "$portableRoot\docs" -Recurse
    Copy-Item config "$portableRoot\config" -Recurse
    Copy-Item scripts\create_desktop_shortcut.ps1 $portableRoot
    Copy-Item "$releaseRoot\windows-test-results.txt" $portableRoot
    & $buildPython -m pip freeze | Out-File "$portableRoot\build-dependencies.txt" -Encoding utf8
    & $buildPython scripts\dependency_notices.py "$portableRoot\DEPENDENCY-LICENSES.txt"
    if ($LASTEXITCODE -ne 0) { throw 'Dependency license collection failed.' }
    $archivePath = Join-Path $releaseRoot 'MaisonNightReports-Windows-x64.zip'
    Compress-Archive -Path $portableRoot -DestinationPath $archivePath
    Get-FileHash -Algorithm SHA256 $archivePath | Format-List | Out-File "$archivePath.sha256.txt"
    Write-Host "Portable application built: $archivePath"
    Write-Host 'Extract the entire folder on the hotel PC. Complete compatibility and pilot checks before regular use.'
} finally {
    Remove-Item Env:MAISON_GUI_TESTS -ErrorAction SilentlyContinue
    Pop-Location
}
