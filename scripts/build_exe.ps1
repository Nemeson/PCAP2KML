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

function Test-PipPackage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackageName
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & py -m pip show $PackageName > $null 2> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

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
    if (-not (Test-PipPackage -PackageName $package)) {
        $missing += $requirement
    }
}

if (-not (Test-PipPackage -PackageName "pyinstaller")) {
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
    --add-data "pcap2kml_player\assets;pcap2kml_player\assets" `
    --add-data "docs\benutzerhandbuch.html;docs" `
    $Launcher

Write-Host ""
Write-Host "EXE erstellt:" -ForegroundColor Green
Write-Host "  $(Join-Path $DistDir 'PCAP2KML-Player.exe')"
