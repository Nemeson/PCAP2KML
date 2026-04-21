param(
    [switch]$InstallMissing,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")
$Requirements = Join-Path $ProjectRoot "pcap2kml_player\requirements.txt"
$Launcher = Join-Path $ProjectRoot "pcap2kml_launcher.py"
$DistDir = Join-Path $ProjectRoot "dist"
$BuildDir = Join-Path $ProjectRoot "build"
$SpecFile = Join-Path $ProjectRoot "PCAP2KML-Player.spec"

Set-Location $ProjectRoot

if ($Clean) {
    foreach ($path in @($DistDir, $BuildDir, $SpecFile)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $Requirements)) {
    throw "Requirements-Datei nicht gefunden: $Requirements"
}

if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "Launcher nicht gefunden: $Launcher"
}

$missing = @()
foreach ($line in Get-Content -LiteralPath $Requirements) {
    $requirement = $line.Trim()
    if (-not $requirement -or $requirement.StartsWith("#")) {
        continue
    }
    $package = ($requirement -split "==|>=|<=|~=|!=|>|<|\[")[0].Trim()
    $probe = @"
import importlib.metadata
import sys
try:
    importlib.metadata.version("$package")
except importlib.metadata.PackageNotFoundError:
    sys.exit(1)
"@
    py -c $probe
    if ($LASTEXITCODE -ne 0) {
        $missing += $requirement
    }
}

py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    $missing += "pyinstaller>=6.0"
}

if ($missing.Count -gt 0) {
    Write-Host "Fehlende Build-/Runtime-Abhaengigkeiten:" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "  - $_" }
    if (-not $InstallMissing) {
        Write-Host ""
        Write-Host "Erneut mit -InstallMissing ausfuehren, um fehlende Pakete automatisch zu installieren."
        exit 2
    }
    py -m pip install @missing
}

py -m PyInstaller `
    --noconfirm `
    --onefile `
    --name "PCAP2KML-Player" `
    --collect-all PyQt6 `
    --collect-all PyQt6.QtWebEngineWidgets `
    --add-data "pcap2kml_player\requirements.txt;pcap2kml_player" `
    $Launcher

Write-Host ""
Write-Host "EXE erstellt:" -ForegroundColor Green
Write-Host "  $(Join-Path $DistDir 'PCAP2KML-Player.exe')"
