# Pull project files from the Raspberry Pi onto this laptop.
# Use after editing on the Pi so nothing lives only on the device.
#
# Usage:
#   .\scripts\pull_from_pi.ps1
#   .\scripts\pull_from_pi.ps1 -PiHost 192.168.1.152 -PiUser pi

param(
    [string]$PiHost = "192.168.1.152",
    [string]$PiUser = "pi",
    [string]$RemotePath = "/home/pi/KevinsProject",
    [string]$Key = "$env:USERPROFILE\.ssh\id_ed25519_pi"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ssh = @("-i", $Key, "-o", "IdentitiesOnly=yes")

Write-Host "Pulling ${PiUser}@${PiHost}:${RemotePath} -> $RepoRoot"

$items = @(
    "src",
    "scripts",
    "models",
    "docs",
    "README.md",
    "PI.md",
    "CONTEXT.md",
    "COMMANDS.md",
    "requirements-pi.txt"
)

foreach ($item in $items) {
    $remote = "${PiUser}@${PiHost}:${RemotePath}/$item"
    $local = Join-Path $RepoRoot $item
    Write-Host "  scp $item ..."
    # For directories, scp into parent; for files, scp onto path
    $check = ssh @ssh "${PiUser}@${PiHost}" "test -e '${RemotePath}/$item' && echo yes || echo no"
    if ($check.Trim() -ne "yes") {
        Write-Warning "Remote missing $item — skip"
        continue
    }
    $isDir = ssh @ssh "${PiUser}@${PiHost}" "test -d '${RemotePath}/$item' && echo dir || echo file"
    if ($isDir.Trim() -eq "dir") {
        $destParent = Split-Path $local -Parent
        if (-not (Test-Path $destParent)) { New-Item -ItemType Directory -Path $destParent | Out-Null }
        scp @ssh -r $remote $destParent
    }
    else {
        scp @ssh $remote $local
    }
}

Write-Host "Pull complete. Local project is updated from the Pi."
