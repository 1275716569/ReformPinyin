$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$mode = if ($args -contains '-Remove') { 'remove' } else { 'install' }
$hostExe = Join-Path $root 'ReformHost.exe'
$dll = Join-Path $root 'ReformTIP.dll'
$tip = '0804:{A62A60A8-421D-4A86-91D7-767E708A2221}{55498CE1-7AE7-456A-A3A6-6334F8759916}'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class ReformProfiles {
    [DllImport("input.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern bool InstallLayoutOrTip(string tip, uint flags);
}
'@
$runKey='Software\Microsoft\Windows\CurrentVersion\Run'
$uninstallKey='Software\Microsoft\Windows\CurrentVersion\Uninstall\ReformPinyin'
$registrar=Join-Path $env:windir 'System32\regsvr32.exe'
$shortcutPath=Join-Path ([Environment]::GetFolderPath('Programs')) '改革拼音控制面板.lnk'
$startupPath=Join-Path ([Environment]::GetFolderPath('Startup')) '改革拼音.lnk'
if (-not (Test-Path -LiteralPath $dll)) { throw "找不到输入法组件：$dll" }
function Remove-LegacyRunEntry {
    $key=$null
    try {
        $key=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($runKey,$true)
        if ($key) { $key.DeleteValue('ReformPinyin',$false) }
    } catch {
        Write-Warning ("旧版后台启动项未能清除：" + $_.Exception.Message)
    } finally {
        if ($key) { $key.Dispose() }
    }
}
if ($mode -eq 'remove') {
    [void][ReformProfiles]::InstallLayoutOrTip($tip,1)
    $p=Start-Process $registrar -ArgumentList @('/s','/u',('"{0}"' -f $dll)) -Wait -PassThru -WindowStyle Hidden
    if ($p.ExitCode -ne 0) { throw "Cannot unregister profile ($($p.ExitCode))" }
    Remove-LegacyRunEntry
    Get-Process ReformHost -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $hostExe } | Stop-Process
    [Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($uninstallKey,$false)
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
    if (Test-Path -LiteralPath $startupPath) { Remove-Item -LiteralPath $startupPath }
    return
}
$p=Start-Process $registrar -ArgumentList @('/s',('"{0}"' -f $dll)) -Wait -PassThru -WindowStyle Hidden
if ($p.ExitCode -ne 0) {
    $code = [uint32]$p.ExitCode
    throw ("Windows text-service registration failed (0x{0:X8}), DLL: {1}" -f $code,$dll)
}
if (![ReformProfiles]::InstallLayoutOrTip($tip,0)) {
    $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    throw ("Windows could not enable the input profile (Win32 error {0}, 0x{1:X8})." -f $code,[uint32]$code)
}
Remove-LegacyRunEntry
$uninstall=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($uninstallKey,$true)
if (-not $uninstall) { throw '无法创建卸载信息注册表项。' }
try {
    $uninstall.SetValue('DisplayName','改革拼音（试用版）',[Microsoft.Win32.RegistryValueKind]::String)
    $uninstall.SetValue('DisplayVersion','0.2.4',[Microsoft.Win32.RegistryValueKind]::String)
    $uninstall.SetValue('UninstallString',('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" -Remove' -f $PSCommandPath),[Microsoft.Win32.RegistryValueKind]::String)
} finally { $uninstall.Dispose() }
$productRoot=Split-Path $root -Parent
$shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
$shortcut.TargetPath=$hostExe
$shortcut.Arguments='--control'
$shortcut.WorkingDirectory=$root
$shortcut.Save()
$startup=(New-Object -ComObject WScript.Shell).CreateShortcut($startupPath)
$startup.TargetPath=$hostExe
$startup.WorkingDirectory=$root
$startup.Save()
$knownHosts=@((Join-Path $productRoot 'app-0.1\ReformHost.exe'),(Join-Path $productRoot 'app-0.1.1\ReformHost.exe'),(Join-Path $productRoot 'app-0.1.2\ReformHost.exe'),(Join-Path $productRoot 'app-0.2.0\ReformHost.exe'),(Join-Path $productRoot 'app-0.2.1\ReformHost.exe'),(Join-Path $productRoot 'app-0.2.2\ReformHost.exe'),(Join-Path $productRoot 'app-0.2.3\ReformHost.exe'),$hostExe)
Get-Process ReformHost -ErrorAction SilentlyContinue | Where-Object { $knownHosts -contains $_.Path } | Stop-Process -Force

