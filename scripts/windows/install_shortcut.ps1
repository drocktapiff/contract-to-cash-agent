[CmdletBinding()]
param(
    [string]$Destination = [Environment]::GetFolderPath('Desktop'),
    [switch]$Force,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$Launcher = Join-Path $ProjectRoot 'Start Ledgerline.cmd'
if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) { throw 'Start Ledgerline.cmd was not found. Keep the installer inside the project checkout.' }
if ([string]::IsNullOrWhiteSpace($Destination)) { throw 'Windows did not return a desktop folder. Supply -Destination explicitly.' }
$ShortcutPath = Join-Path $Destination 'Ledgerline Operations Console.lnk'
$Shortcut = $null
$Existing = $null
$Shell = New-Object -ComObject WScript.Shell
try {
    if (Test-Path -LiteralPath $ShortcutPath) {
        $Existing = $Shell.CreateShortcut($ShortcutPath)
        if ($Remove) {
            if ($Existing.TargetPath -ne $Launcher) { throw 'This shortcut belongs to a different checkout. It was not removed.' }
            Remove-Item -LiteralPath $ShortcutPath
            Write-Host 'Ledgerline shortcut removed. Application, credentials and history were not changed.'
            return
        }
        if (-not $Force) { throw 'Shortcut already exists. Use -Force to replace it, or -Remove to uninstall this checkout shortcut.' }
    } elseif ($Remove) {
        Write-Host 'No shortcut to remove.'
        return
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $Launcher
    $Shortcut.WorkingDirectory = $ProjectRoot
    $Shortcut.Description = 'Ledgerline local console. Keep the console open; Ctrl+C shuts down cleanly.'
    $Shortcut.WindowStyle = 1
    $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,21"
    $Shortcut.Save()
    Write-Host 'Ledgerline desktop shortcut installed. No server was started and no credentials were stored.'
} finally {
    foreach ($Object in @($Shortcut, $Existing, $Shell)) {
        if ($null -ne $Object) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($Object) }
    }
}
