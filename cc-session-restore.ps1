<#
  cc-session-restore - a small window to reopen your Claude Code (WSL) sessions.
  Unofficial; not affiliated with Anthropic.

  Lists sessions via the `cc-session-restore` script (run inside WSL) and opens the
  checked ones as Windows Terminal tabs. Run install.ps1 once to get a shortcut.

  -Distro  WSL distro where Claude Code is installed (default: your default distro)
#>
param([string]$Distro = "")

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:count = 15
$script:running = @{}

# Where this folder is, as WSL sees it. Cloned inside WSL, it shows up in Windows
# as \\wsl.localhost\<distro>\... (or \\wsl$\...): turn that back into a Linux path.
$script:here = $PSScriptRoot
if ($PSScriptRoot -match '^\\\\wsl(\.localhost|\$)\\([^\\]+)(\\.*)?$') {
    if (-not $Distro) { $Distro = $Matches[2] }
    $script:here = if ($Matches[3]) { $Matches[3] -replace '\\', '/' } else { "/" }
}

# wsl.exe arguments that run the Python script from this folder.
function Get-WslArgs([string[]]$extra) {
    $a = @()
    if ($Distro) { $a += @("-d", $Distro) }
    $a += @("--cd", $script:here, "--", "python3", "./cc-session-restore")
    return $a + $extra
}

function Get-Sessions {
    $wslArgs = Get-WslArgs @("--json", "-n", "$script:count")
    $raw = & wsl.exe @wslArgs 2>$null
    if (-not $raw) { return $null }
    try { return ($raw -join "`n") | ConvertFrom-Json } catch { return $null }
}

function Open-Sessions($ids) {
    if (-not $ids -or $ids.Count -eq 0) { return }
    # Start-Process joins arguments with spaces without quoting, so quote them here.
    $quoted = Get-WslArgs (@("--open") + $ids) | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }
    Start-Process wsl.exe -ArgumentList $quoted -WindowStyle Hidden
    $form.Close()
}

# ---- window ----
$form = New-Object System.Windows.Forms.Form
$form.Text = "Claude Code sessions"
$form.Size = New-Object System.Drawing.Size(860, 520)
$form.MinimumSize = New-Object System.Drawing.Size(600, 300)
$form.StartPosition = "CenterScreen"
$form.Font = New-Object System.Drawing.Font("Segoe UI", 10)

$header = New-Object System.Windows.Forms.Label
$header.Location = New-Object System.Drawing.Point(12, 10)
$header.Size = New-Object System.Drawing.Size(820, 24)
$header.Anchor = "Top,Left,Right"
$form.Controls.Add($header)

$list = New-Object System.Windows.Forms.ListView
$list.Location = New-Object System.Drawing.Point(12, 38)
$list.Size = New-Object System.Drawing.Size(820, 380)
$list.Anchor = "Top,Bottom,Left,Right"
$list.View = "Details"
$list.CheckBoxes = $true
$list.FullRowSelect = $true
[void]$list.Columns.Add("Session", 250)
[void]$list.Columns.Add("Status", 90)
[void]$list.Columns.Add("Last used", 90)
[void]$list.Columns.Add("Folder", 370)
$form.Controls.Add($list)

function New-Button($text, $x, $width) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $text
    $b.Location = New-Object System.Drawing.Point($x, 430)
    $b.Size = New-Object System.Drawing.Size($width, 34)
    $b.Anchor = "Bottom,Left"
    $form.Controls.Add($b)
    return $b
}
$btnOpen    = New-Button "Open checked" 12 140
$btnAll     = New-Button "All" 162 70
$btnNone    = New-Button "None" 240 70
$btnMore    = New-Button "Show more" 318 110
$btnRefresh = New-Button "Refresh" 436 90
$btnOpen.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
$form.AcceptButton = $btnOpen

$hint = New-Object System.Windows.Forms.Label
$hint.Text = "Double-click a row to open just that one"
$hint.Location = New-Object System.Drawing.Point(540, 438)
$hint.Size = New-Object System.Drawing.Size(300, 24)
$hint.Anchor = "Bottom,Left"
$hint.ForeColor = [System.Drawing.Color]::Gray
$form.Controls.Add($hint)

function Load-List {
    $form.Cursor = "WaitCursor"
    $list.BeginUpdate()
    $list.Items.Clear()
    $script:running = @{}
    $data = Get-Sessions
    if ($null -eq $data) {
        $where = if ($Distro) { "WSL distro '$Distro'" } else { "your default WSL distro" }
        $header.Text = "Couldn't read Claude Code sessions from $where. Is python3 installed there?"
    } else {
        foreach ($s in $data.sessions) {
            $item = New-Object System.Windows.Forms.ListViewItem($s.title)
            [void]$item.SubItems.Add($(if ($s.running) { "Running" } else { "" }))
            [void]$item.SubItems.Add($s.ago)
            [void]$item.SubItems.Add($s.folder)
            $item.Tag = $s.id
            if ($s.running) {
                $script:running[$s.id] = $true
                $item.ForeColor = [System.Drawing.Color]::Gray
            } else {
                $item.Checked = [bool]$s.checked
            }
            [void]$list.Items.Add($item)
        }
        $header.Text = if ($data.sessions.Count -eq 0) { "No Claude Code sessions found." }
                       else { "Checked = was open when the PC went down.   Grey = already running." }
    }
    $list.EndUpdate()
    $form.Cursor = "Default"
}

$btnOpen.Add_Click({ Open-Sessions @($list.CheckedItems | ForEach-Object { $_.Tag }) })
$btnAll.Add_Click({ foreach ($i in $list.Items) { if (-not $script:running[$i.Tag]) { $i.Checked = $true } } })
$btnNone.Add_Click({ foreach ($i in $list.Items) { $i.Checked = $false } })
$btnRefresh.Add_Click({ Load-List })
$btnMore.Add_Click({ $script:count += 25; Load-List })
# Running sessions can't be checked: opening them again would start a second copy.
$list.Add_ItemCheck({ if ($script:running[$list.Items[$_.Index].Tag]) { $_.NewValue = $_.CurrentValue } })
$list.Add_MouseDoubleClick({
    Open-Sessions @($list.SelectedItems | Where-Object { -not $script:running[$_.Tag] } | ForEach-Object { $_.Tag })
})

$form.Add_Shown({ Load-List; $form.Activate() })
[void]$form.ShowDialog()
