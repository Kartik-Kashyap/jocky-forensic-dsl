# JOCKY launcher — Windows
#
#   .\run.ps1              start the console at http://127.0.0.1:8787
#   .\run.ps1 -Demo        run every script in the terminal instead
#   .\run.ps1 -Test        run the test suite
#   .\run.ps1 -Port 9000   use a different port
#
# If PowerShell blocks the script, run:
#   powershell -ExecutionPolicy Bypass -File .\run.ps1

param(
    [switch]$Demo,
    [switch]$Test,
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Find-Python {
    foreach ($candidate in @("python", "python3", "py")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $null = & $candidate --version 2>&1
                return $candidate
            } catch { }
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host ""
    Write-Host "  Python 3.8+ was not found on PATH." -ForegroundColor Red
    Write-Host "  Install it from https://www.python.org/downloads/ and tick"
    Write-Host "  'Add python.exe to PATH' during setup."
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "  JOCKY" -ForegroundColor Cyan -NoNewline
Write-Host "  forensic scripting language" -ForegroundColor DarkGray
Write-Host "  interpreter: $python ($(& $python --version 2>&1))" -ForegroundColor DarkGray
Write-Host ""

if ($Test) {
    & $python -m unittest discover -s tests -t . -v
    exit $LASTEXITCODE
}

if ($Demo) {
    Get-ChildItem -Path "scripts\*.jky" | ForEach-Object {
        Write-Host ("=" * 72) -ForegroundColor DarkGray
        Write-Host "  $($_.Name)" -ForegroundColor Cyan
        Write-Host ("=" * 72) -ForegroundColor DarkGray
        & $python -m jocky run $_.FullName
    }
    exit $LASTEXITCODE
}

Write-Host "  starting console on http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "  opening your browser in a moment..." -ForegroundColor DarkGray
Write-Host ""

Start-Job -ScriptBlock {
    param($p)
    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:$p/"
} -ArgumentList $Port | Out-Null

& $python -m jocky serve --port $Port
