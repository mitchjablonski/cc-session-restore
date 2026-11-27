<#
  Installs a "Claude Code sessions" shortcut for cc-session-restore.

  .\install.ps1                  Start menu shortcut
  .\install.ps1 -Desktop         ...and one on the desktop
  .\install.ps1 -Startup         ...and open the window automatically when you log in
  .\install.ps1 -Distro Debian   use a WSL distro other than your default
  .\install.ps1 -Uninstall       remove every shortcut this script made

  Run it with:  powershell -ExecutionPolicy Bypass -File .\install.ps1
#>
param(
    [switch]$Desktop,
    [switch]$Startup,
    [string]$Distro = "",
    [switch]$Uninstall
)

$name = "Claude Code sessions.lnk"
$places = @{
    "Start menu" = [Environment]::GetFolderPath("Programs")
    "Desktop"    = [Environment]::GetFolderPath("Desktop")
    "Startup"    = [Environment]::GetFolderPath("Startup")
}

if ($Uninstall) {
    foreach ($p in $places.GetEnumerator()) {
        $lnk = Join-Path $p.Value $name
        if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Removed $($p.Key) shortcut" }
    }
    return
}

# Check the WSL side before making shortcuts that wouldn't work.
$d = @(); if ($Distro) { $d = @("-d", $Distro) }
$py = & wsl.exe @d -- python3 --version 2>$null
if (-not $py) { Write-Error "python3 not found in WSL$(if ($Distro) { " ($Distro)" }). Install it there first (e.g. sudo apt install python3)."; exit 1 }
$claude = & wsl.exe @d -- bash -lic "command -v claude" 2>$null
if (-not $claude) { Write-Warning "'claude' isn't on your WSL PATH in a login shell. Sessions won't open until it is." }
if (-not (Get-Command wt.exe -ErrorAction SilentlyContinue)) { Write-Warning "Windows Terminal (wt.exe) not found. Install it from the Microsoft Store." }

$target = Join-Path $PSScriptRoot "cc-session-restore.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$target`""
if ($Distro) { $arguments += " -Distro `"$Distro`"" }

$want = @("Start menu")
if ($Desktop) { $want += "Desktop" }
if ($Startup) { $want += "Startup" }

$shell = New-Object -ComObject WScript.Shell
foreach ($w in $want) {
    $lnk = $shell.CreateShortcut((Join-Path $places[$w] $name))
    $lnk.TargetPath = "powershell.exe"
    $lnk.Arguments = $arguments
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.WindowStyle = 7  # minimized, so the console doesn't flash
    $wt = (Get-Command wt.exe -ErrorAction SilentlyContinue).Source
    if ($wt) { $lnk.IconLocation = "$wt,0" }
    $lnk.Description = "Reopen your Claude Code sessions (cc-session-restore)"
    $lnk.Save()
    Write-Host "Added $w shortcut: Claude Code sessions"
}
