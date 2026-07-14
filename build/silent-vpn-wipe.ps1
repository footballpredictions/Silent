# Full wipe of Silent VPN / SilentVPN leftovers (install + uninstall).
$ErrorActionPreference = 'SilentlyContinue'
$names = @('SilentVPN', 'Silent VPN')
$roots = @(
  'C:\ProgramData',
  'C:\Program Files',
  'C:\Program Files (x86)'
)

foreach ($r in $roots) {
  foreach ($n in $names) {
    $p = Join-Path $r $n
    if (Test-Path -LiteralPath $p) {
      Write-Host "Removing $p"
      Remove-Item -LiteralPath $p -Recurse -Force
    }
  }
}

Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue | ForEach-Object {
  foreach ($n in $names) {
    @(
      (Join-Path $_.FullName "AppData\Roaming\$n"),
      (Join-Path $_.FullName "AppData\Local\$n"),
      (Join-Path $_.FullName "AppData\Local\Programs\$n")
    ) | ForEach-Object {
      if (Test-Path -LiteralPath $_) {
        Write-Host "Removing $_"
        Remove-Item -LiteralPath $_ -Recurse -Force
      }
    }
  }
}

if (Test-Path 'C:\Users\Public') {
  foreach ($n in $names) {
    $p = Join-Path 'C:\Users\Public' $n
    if (Test-Path -LiteralPath $p) {
      Write-Host "Removing $p"
      Remove-Item -LiteralPath $p -Recurse -Force
    }
  }
}

# Extra INSTDIR from arg1 if provided
if ($args.Count -ge 1 -and $args[0]) {
  $extra = [string]$args[0]
  if ($extra -and (Test-Path -LiteralPath $extra)) {
    $leaf = Split-Path -Leaf $extra
    if ($leaf -eq 'Silent VPN' -or $leaf -eq 'SilentVPN' -or (Test-Path -LiteralPath (Join-Path $extra 'Silent VPN.exe')) -or (Test-Path -LiteralPath (Join-Path $extra 'resources\wdtt-client.exe'))) {
      Write-Host "Removing INSTDIR $extra"
      Remove-Item -LiteralPath $extra -Recurse -Force
    }
  }
}

exit 0
