param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'

# Read the packaged PE resource without launching the VPN or requesting elevation.
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class SilentPeManifestReader {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern IntPtr LoadLibraryEx(string file, IntPtr zero, uint flags);
 [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr FindResource(IntPtr module, IntPtr name, IntPtr type);
 [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr LoadResource(IntPtr module, IntPtr resource);
 [DllImport("kernel32.dll")] public static extern IntPtr LockResource(IntPtr resource);
 [DllImport("kernel32.dll")] public static extern uint SizeofResource(IntPtr module, IntPtr resource);
 [DllImport("kernel32.dll")] public static extern bool FreeLibrary(IntPtr module);
}
'@
$module = [SilentPeManifestReader]::LoadLibraryEx((Resolve-Path -LiteralPath $Path).Path, [IntPtr]::Zero, 2)
if ($module -eq [IntPtr]::Zero) { throw 'Cannot read packaged Windows executable resources' }
try {
    $resource = [SilentPeManifestReader]::FindResource($module, [IntPtr]1, [IntPtr]24)
    if ($resource -eq [IntPtr]::Zero) { throw 'Packaged Windows executable has no application manifest' }
    $size = [SilentPeManifestReader]::SizeofResource($module, $resource)
    $pointer = [SilentPeManifestReader]::LockResource([SilentPeManifestReader]::LoadResource($module, $resource))
    if ($pointer -eq [IntPtr]::Zero -or $size -eq 0) { throw 'Cannot read packaged application manifest' }
    $bytes = [byte[]]::new($size)
    [Runtime.InteropServices.Marshal]::Copy($pointer, $bytes, 0, $size)
    $manifest = [Text.Encoding]::UTF8.GetString($bytes)
    $level = [regex]::Match($manifest, 'requestedExecutionLevel\s+level="([^"]+)"').Groups[1].Value
    if ($level -ne 'requireAdministrator') {
        throw "Windows release requires an administrator manifest; actual: $level. Enable signAndEditExecutable."
    }
    Write-Output 'Packaged Windows manifest verified: requireAdministrator'
} finally {
    [void][SilentPeManifestReader]::FreeLibrary($module)
}
