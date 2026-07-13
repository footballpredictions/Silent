; Silent VPN — при установке/OTA чинит WireGuard (0.5.3 vs драйвер 1.1 → SCM 7024).
; Не нужен SilentVPN-Admin.bat: UAC установщика уже elevated.
; Важно: в electron-builder makensis нет $COMMONAPPDATA/$COMMONPROGRAMDATA —
; пути ProgramData только литералом C:\ProgramData (как в wireguard.js).

!define SILENT_WG_DIR "C:\ProgramData\SilentVPN\wireguard"

!macro silentWgUninstallTunnel WGEXE
  ${If} ${FileExists} "${WGEXE}"
    nsExec::ExecToLog '"${WGEXE}" /uninstalltunnelservice wg-turn'
    Pop $0
  ${EndIf}
!macroend

!macro customInstall
  DetailPrint "Silent VPN: WireGuard repair (service + ProgramData 1.1)..."

  ; Снять процессы, которые держат wireguard.exe в ProgramData
  nsExec::ExecToLog 'taskkill /F /IM "Silent VPN.exe" /T'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /IM wdtt-client.exe /T'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /IM wireguard.exe /T'
  Pop $0

  ; Снять старую службу любым доступным wireguard.exe
  !insertmacro silentWgUninstallTunnel "$PROGRAMFILES64\WireGuard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "$PROGRAMFILES\WireGuard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "$INSTDIR\resources\wireguard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "${SILENT_WG_DIR}\wireguard.exe"

  ; $$ → литеральный $ в имени службы WireGuardTunnel$wg-turn
  nsExec::ExecToLog 'sc.exe stop "WireGuardTunnel$$wg-turn"'
  Pop $0
  nsExec::ExecToLog 'sc.exe delete "WireGuardTunnel$$wg-turn"'
  Pop $0
  Sleep 400

  ; Если системного WireGuard нет — тихий MSI (драйвер WireGuardNT 1.1)
  ${If} ${FileExists} "$INSTDIR\resources\wireguard-installer.msi"
    ${IfNot} ${FileExists} "$PROGRAMFILES64\WireGuard\wireguard.exe"
      ${IfNot} ${FileExists} "$PROGRAMFILES\WireGuard\wireguard.exe"
        DetailPrint "Installing WireGuard 1.1 (MSI)..."
        nsExec::ExecToLog 'msiexec /i "$INSTDIR\resources\wireguard-installer.msi" /qn /norestart'
        Pop $0
        DetailPrint "msiexec exit=$0"
        Sleep 800
      ${EndIf}
    ${EndIf}
  ${EndIf}

  ; ProgramData всегда актуальный 1.1 (сначала бандл, потом Program Files если есть)
  CreateDirectory "${SILENT_WG_DIR}"
  ${If} ${FileExists} "$INSTDIR\resources\wireguard\wireguard.exe"
    DetailPrint "Copy bundled WireGuard → ProgramData\SilentVPN\wireguard"
    CopyFiles /SILENT "$INSTDIR\resources\wireguard\wireguard.exe" "${SILENT_WG_DIR}\wireguard.exe"
    ${If} ${FileExists} "$INSTDIR\resources\wireguard\wg.exe"
      CopyFiles /SILENT "$INSTDIR\resources\wireguard\wg.exe" "${SILENT_WG_DIR}\wg.exe"
    ${EndIf}
  ${EndIf}

  ${If} ${FileExists} "$PROGRAMFILES64\WireGuard\wireguard.exe"
    DetailPrint "Refresh ProgramData from Program Files\WireGuard"
    CopyFiles /SILENT "$PROGRAMFILES64\WireGuard\wireguard.exe" "${SILENT_WG_DIR}\wireguard.exe"
    ${If} ${FileExists} "$PROGRAMFILES64\WireGuard\wg.exe"
      CopyFiles /SILENT "$PROGRAMFILES64\WireGuard\wg.exe" "${SILENT_WG_DIR}\wg.exe"
    ${EndIf}
  ${ElseIf} ${FileExists} "$PROGRAMFILES\WireGuard\wireguard.exe"
    CopyFiles /SILENT "$PROGRAMFILES\WireGuard\wireguard.exe" "${SILENT_WG_DIR}\wireguard.exe"
    ${If} ${FileExists} "$PROGRAMFILES\WireGuard\wg.exe"
      CopyFiles /SILENT "$PROGRAMFILES\WireGuard\wg.exe" "${SILENT_WG_DIR}\wg.exe"
    ${EndIf}
  ${EndIf}

  ; wintun.dll рядом с 1.1 ломает службу (SCM 7024) — только WireGuardNT
  Delete "${SILENT_WG_DIR}\wintun.dll"

  DetailPrint "WireGuard repair done"
!macroend

!macro customUnInstall
  DetailPrint "Silent VPN: remove WireGuardTunnel$$wg-turn..."
  !insertmacro silentWgUninstallTunnel "$PROGRAMFILES64\WireGuard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "$PROGRAMFILES\WireGuard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "$INSTDIR\resources\wireguard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "${SILENT_WG_DIR}\wireguard.exe"
  nsExec::ExecToLog 'sc.exe stop "WireGuardTunnel$$wg-turn"'
  Pop $0
  nsExec::ExecToLog 'sc.exe delete "WireGuardTunnel$$wg-turn"'
  Pop $0
  ; Оставляем Program Files\WireGuard (общий драйвер). Чистим только наш runtime.
  RMDir /r "${SILENT_WG_DIR}"
!macroend
