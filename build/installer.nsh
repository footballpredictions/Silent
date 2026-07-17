; Silent VPN — полная очистка SilentVPN/Silent VPN перед установкой и при деинсталляции.
; + Repair WireGuard (0.5.3 vs драйвер 1.1 → SCM 7024).
; Не нужен SilentVPN-Admin.bat: UAC установщика уже elevated.
; Важно: в electron-builder makensis нет $COMMONAPPDATA/$COMMONPROGRAMDATA —
; пути ProgramData только литералом C:\ProgramData (как в wireguard.js).

!define SILENT_WG_DIR "C:\ProgramData\SilentVPN\wireguard"
!define SILENT_PD_DIR "C:\ProgramData\SilentVPN"

!macro silentWgUninstallTunnel WGEXE
  ${If} ${FileExists} "${WGEXE}"
    nsExec::ExecToLog '"${WGEXE}" /uninstalltunnelservice wg-turn'
    Pop $0
  ${EndIf}
!macroend

; Останавливает процессы / службу и чистит runtime VPN (без AppData — токены/«запомнить»).
!macro silentVpnWipeRuntime
  DetailPrint "Silent VPN: очистка runtime (служба/ProgramData)..."

  nsExec::ExecToLog 'taskkill /F /IM "Silent VPN.exe"'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /IM wdtt-client.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /IM wireguard.exe'
  Pop $0

  !insertmacro silentWgUninstallTunnel "$PROGRAMFILES64\WireGuard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "$PROGRAMFILES\WireGuard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "$INSTDIR\resources\wireguard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "${SILENT_WG_DIR}\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "$PROGRAMFILES64\Silent VPN\resources\wireguard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "$PROGRAMFILES\Silent VPN\resources\wireguard\wireguard.exe"

  nsExec::ExecToLog 'sc.exe stop "WireGuardTunnel$$wg-turn"'
  Pop $0
  nsExec::ExecToLog 'sc.exe delete "WireGuardTunnel$$wg-turn"'
  Pop $0
  Sleep 400

  RMDir /r "${SILENT_PD_DIR}"
!macroend

; Полная очистка включая AppData (только чистая установка / uninstall).
!macro silentVpnWipeAll
  DetailPrint "Silent VPN: полная очистка SilentVPN / Silent VPN..."

  !insertmacro silentVpnWipeRuntime

  ; Известные каталоги (быстрый путь без PowerShell)
  RMDir /r "$PROGRAMFILES64\Silent VPN"
  RMDir /r "$PROGRAMFILES\Silent VPN"
  RMDir /r "$PROGRAMFILES64\SilentVPN"
  RMDir /r "$PROGRAMFILES\SilentVPN"
  RMDir /r "$APPDATA\Silent VPN"
  RMDir /r "$APPDATA\SilentVPN"
  RMDir /r "$LOCALAPPDATA\Silent VPN"
  RMDir /r "$LOCALAPPDATA\SilentVPN"
  RMDir /r "$LOCALAPPDATA\Programs\Silent VPN"
  RMDir /r "$LOCALAPPDATA\Programs\SilentVPN"

  ; Все профили Users + Program Files / ProgramData
  InitPluginsDir
  File "/oname=$PLUGINSDIR\silent-vpn-wipe.ps1" "${BUILD_RESOURCES_DIR}\silent-vpn-wipe.ps1"
  ${If} $INSTDIR != ""
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\silent-vpn-wipe.ps1" "$INSTDIR"'
  ${Else}
    nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\silent-vpn-wipe.ps1"'
  ${EndIf}
  Pop $0

  DetailPrint "Silent VPN: очистка завершена (ps exit=$0)"
!macroend

; До копирования файлов — убрать старые остатки
!macro customInit
  ${if} ${isUpdated}
    ; OTA: не трогаем AppData (JWT / «Запомнить меня»)
    !insertmacro silentVpnWipeRuntime
  ${else}
    !insertmacro silentVpnWipeAll
  ${endif}
!macroend

!macro customInstall
  DetailPrint "Silent VPN: WireGuard repair (service + ProgramData 1.1)..."

  ; Без /T — см. silentVpnWipeAll (OTA self-kill)
  nsExec::ExecToLog 'taskkill /F /IM "Silent VPN.exe"'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /IM wdtt-client.exe'
  Pop $0
  nsExec::ExecToLog 'taskkill /F /IM wireguard.exe'
  Pop $0

  !insertmacro silentWgUninstallTunnel "$PROGRAMFILES64\WireGuard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "$PROGRAMFILES\WireGuard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "$INSTDIR\resources\wireguard\wireguard.exe"
  !insertmacro silentWgUninstallTunnel "${SILENT_WG_DIR}\wireguard.exe"

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

  Delete "${SILENT_WG_DIR}\wintun.dll"

  ; Маркер для клиента: первый запуск после install — подождать WG
  CreateDirectory "${SILENT_PD_DIR}"
  FileOpen $0 "${SILENT_PD_DIR}\post-install.stamp" w
  FileWrite $0 "1"
  FileClose $0

  Sleep 1500
  DetailPrint "WireGuard repair done"
!macroend

; Полное удаление каталога установки
!macro customRemoveFiles
  ${if} ${isUpdated}
    ; OTA/update — стандартная замена
  ${else}
    DetailPrint "Silent VPN: удаление $INSTDIR..."
    RMDir /r "$INSTDIR"
  ${endif}
!macroend

!macro customUnInstall
  ${ifNot} ${isUpdated}
    DetailPrint "Silent VPN: полная деинсталляция..."
    !insertmacro silentVpnWipeAll
    ${If} $INSTDIR != ""
      RMDir /r "$INSTDIR"
    ${EndIf}
    DetailPrint "Silent VPN: деинсталляция завершена"
  ${endIf}
!macroend
