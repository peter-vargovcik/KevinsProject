# Deploy this project to the Raspberry Pi over SSH (Windows PowerShell).
#
# Usage:
#   .\scripts\deploy.ps1 -PiHost 192.168.1.50 -PiUser pi
#   .\scripts\deploy.ps1 -PiHost kevin-pi.local -PiUser kevin -RemotePath /home/kevin/KevinsProject

param(
    [Parameter(Mandatory = $true)]
    [string]$PiHost,

    [string]$PiUser = "pi",

    [string]$RemotePath = "/home/pi/KevinsProject"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Write-Host "Deploying $RepoRoot -> ${PiUser}@${PiHost}:${RemotePath}"

ssh "${PiUser}@${PiHost}" "mkdir -p '${RemotePath}'"

# Copy the pieces we need (simple and reliable with Windows OpenSSH)
$items = @(
    "src",
    "scripts",
    "models",
    "README.md",
    "requirements-pi.txt"
)

foreach ($item in $items) {
    $local = Join-Path $RepoRoot $item
    if (-not (Test-Path $local)) {
        Write-Warning "Skipping missing $item"
        continue
    }
    Write-Host "  scp $item ..."
    scp -r $local "${PiUser}@${PiHost}:${RemotePath}/"
}

Write-Host ""
Write-Host "Deploy complete. On the Pi:"
Write-Host "  source ~/arrow-env/bin/activate"
Write-Host "  cd ${RemotePath}"
Write-Host "  python src/main.py --stream"
