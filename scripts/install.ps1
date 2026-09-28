# ByteBuddhi CLI Installer — Windows PowerShell
#
# Install:  irm https://github.com/Navin45/bytebuddhi/releases/latest/download/install.ps1 | iex
# Options:  $env:BYTEBUDDHI_VERSION = "0.1.4"   — pin a specific release
#           $env:BYTEBUDDHI_HOME = "D:\bb"       — custom install root

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Owner    = "Navin45"
$Repo     = "bytebuddhi"
$BaseUrl  = "https://github.com/$Owner/$Repo/releases"

$InstallDir = if ($env:BYTEBUDDHI_HOME) { $env:BYTEBUDDHI_HOME }
              else { Join-Path $env:LOCALAPPDATA "ByteBuddhi" }
$BinDir     = Join-Path $InstallDir "bin"

# ── Helpers ────────────────────────────────────────────────────────────

function Info($msg)  { Write-Host $msg -ForegroundColor Cyan }
function Ok($msg)    { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Fail($msg)  { Write-Host "  ✗ $msg" -ForegroundColor Red; exit 1 }

function Sha256($path) {
    (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
}

# ── Managed Runtime (No System Python Required) ───────────────────────

function Get-ManagedRuntime {
    $runtimeDir = Join-Path $InstallDir "runtime"
    $uvExe = Join-Path $runtimeDir "uv.exe"
    if (Test-Path $uvExe) { return @{ Mode = "uv"; Exe = $uvExe } }

    $sysUv = Get-Command uv -ErrorAction SilentlyContinue
    if ($sysUv) { return @{ Mode = "uv"; Exe = $sysUv.Source } }

    # If Python >= 3.13 is already available, can use it
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
    if ($py) {
        $pyVer = & $py.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($pyVer) {
            $parts = $pyVer.Split(".")
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 13) {
                return @{ Mode = "python"; Exe = $py.Source }
            }
        }
    }

    # Clean machine fallback: bootstrap standalone uv
    Info "Bootstrapping self-contained runtime manager (no system Python required) …"
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $zipPath = Join-Path $runtimeDir "uv.zip"
    $uvUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
    try {
        Invoke-WebRequest -Uri $uvUrl -OutFile $zipPath -TimeoutSec 120
        Expand-Archive -Path $zipPath -DestinationPath $runtimeDir -Force
        Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
    } catch {
        Fail "Failed to download self-contained runtime manager: $_"
    }

    if (-not (Test-Path $uvExe)) {
        $found = Get-ChildItem -Path $runtimeDir -Filter "uv.exe" -Recurse | Select-Object -First 1
        if ($found) { Move-Item -Path $found.FullName -Destination $uvExe -Force }
    }
    if (-not (Test-Path $uvExe)) { Fail "Could not initialize self-contained runtime manager." }
    Ok "Provisioned self-contained runtime manager"
    return @{ Mode = "uv"; Exe = $uvExe }
}

# ── Resolve version ──────────────────────────────────────────────────

$Version = $env:BYTEBUDDHI_VERSION

if (-not $Version) {
    Info "Resolving latest stable release …"
    $manifestUrl = "$BaseUrl/latest/download/release.json"
    try {
        $manifest = Invoke-RestMethod -Uri $manifestUrl -TimeoutSec 30
        $Version = $manifest.version
    } catch {
        Fail "Could not fetch release manifest: $_"
    }
}

Info "ByteBuddhi Installer"
Write-Host ""
Write-Host "  Version:  $Version"
Write-Host "  Platform: Windows $([System.Environment]::Is64BitOperatingSystem ? 'x64' : 'x86')"
Write-Host "  Target:   $InstallDir"
Write-Host ""

# ── Download wheel ────────────────────────────────────────────────────

# PEP 440 drops the hyphen in pre-releases: 0.1.4-rc.1 -> 0.1.4rc1.
$wheelVersion = $Version -replace '-rc\.','rc' -replace '-a\.','a' -replace '-b\.','b'
$wheelName = "bytebuddhi-$wheelVersion-py3-none-any.whl"
$wheelUrl  = "$BaseUrl/download/v$Version/$wheelName"
$sumsUrl   = "$BaseUrl/download/v$Version/SHA256SUMS"

$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) "bytebuddhi-install-$(Get-Random)"
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

try {
    $wheelPath = Join-Path $tmpDir $wheelName

    Info "Downloading release …"
    try {
        Invoke-WebRequest -Uri $wheelUrl -OutFile $wheelPath -TimeoutSec 120
    } catch {
        Fail "Download failed: $_"
    }
    Ok "Downloaded $wheelName"

    Info "Verifying integrity …"
    try {
        $sums = (Invoke-WebRequest -Uri $sumsUrl -TimeoutSec 30).Content
    } catch {
        Fail "Could not fetch checksums: $_"
    }
    $expectedLine = ($sums -split "`n") | Where-Object { $_ -match [regex]::Escape($wheelName) }
    if (-not $expectedLine) { Fail "Wheel not found in SHA256SUMS" }
    $expected = ($expectedLine.Trim() -split "\s+")[0]
    $actual   = Sha256 $wheelPath
    if ($actual -ne $expected) {
        Fail "SHA-256 mismatch: expected $expected, got $actual"
    }
    Ok "Verified SHA-256"

    # ── Install into versioned venv ───────────────────────────────

    $venvDir = Join-Path $InstallDir "installs\$Version"

    Info "Installing into $venvDir …"
    if (Test-Path $venvDir) { Remove-Item -Recurse -Force $venvDir }

    $runtime = Get-ManagedRuntime
    if ($runtime.Mode -eq "uv") {
        & $runtime.Exe venv "$venvDir" --python 3.13
        if ($LASTEXITCODE -ne 0) { Fail "Failed to create isolated virtual environment" }
        & $runtime.Exe pip install --python "$venvDir" --quiet $wheelPath
        if ($LASTEXITCODE -ne 0) { Fail "Package installation failed" }
    } else {
        & $runtime.Exe -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { Fail "Failed to create virtual environment" }
        $venvPip = Join-Path $venvDir "Scripts\pip.exe"
        & $venvPip install --quiet $wheelPath
        if ($LASTEXITCODE -ne 0) { Fail "Wheel installation failed" }
    }
    Ok "Installed"

    # ── Activate + launcher ───────────────────────────────────────

    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    Set-Content -Path (Join-Path $InstallDir "current") -Value $Version -NoNewline

    $shimContent = @"
@echo off
setlocal enabledelayedexpansion
set "BASE_DIR=%~dp0.."
set /p VERSION=<"%BASE_DIR%\current"
set "VERSION=!VERSION: =!"
if "!VERSION!"=="" (
    echo ByteBuddhi is not installed. Run the installer first. >&2
    exit /b 1
)
set "EXE=%BASE_DIR%\installs\!VERSION!\Scripts\bytebuddhi.exe"
if not exist "!EXE!" (
    echo ByteBuddhi !VERSION! is not found. Run bytebuddhi update. >&2
    exit /b 1
)
"!EXE!" %*
"@
    Set-Content -Path (Join-Path $BinDir "bytebuddhi.cmd") -Value $shimContent
    Ok "Created launcher"

    # ── Verify ────────────────────────────────────────────────────

    $testExe = Join-Path $BinDir "bytebuddhi.cmd"
    $testResult = & $testExe --version 2>$null
    if ($testResult -match $Version) {
        Ok "Verified bytebuddhi --version"
    } else {
        Fail "Version verification failed: expected $Version, got $testResult"
    }

    # ── PATH guidance ─────────────────────────────────────────────

    Write-Host ""
    Info "ByteBuddhi $Version is ready."
    Write-Host ""

    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($userPath -notlike "*$BinDir*") {
        Write-Host "  Adding $BinDir to your user PATH …"
        [Environment]::SetEnvironmentVariable("PATH", "$BinDir;$userPath", "User")
        Ok "Added to PATH (restart your terminal to apply)"
    }
} finally {
    if (Test-Path $tmpDir) { Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue }
}
