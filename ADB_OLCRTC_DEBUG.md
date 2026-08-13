# ADB-фильтры для отладки olcrtc2 (Android)

## Быстрый лог VPN/olcrtc

```bat
adb logcat -c
adb logcat -v time Olcrtc:D olcrtc:D WdttTunnel:D SilentVpn:D MainViewModel:D SilentRepository:D *:S
```

## Только UI-трейс (то, что в приложении в логе VPN)

Теги из `WdttTunnelManager.logUi` / `traceApp` обычно идут как `WdttTunnel` или через `DebugLog`.

```bat
adb logcat -v time | findstr /i "olcrtc SOCKS tunnelReady code=1 hev warm reassign override config resolve"
```

PowerShell:

```powershell
adb logcat -v time | Select-String -Pattern "olcrtc|SOCKS|tunnelReady|code=1|hev|reassign|override|config resolve"
```

## Что смотреть по таймингам

| Строка | Смысл |
|--------|--------|
| `config resolve Nms` | Сколько ждали /olcrtc2-config или кеш |
| `olcrtc_hev_ms` | hev TUN + excludeRoute |
| `SOCKS dial OK` → `tunnelReady` | Диапазон до готовности туннеля |
| `olcrtc-config: override room=` | Retry после fail взял НОВЫЙ room |
| `новый канал …` vs `start … room=` | Должны совпадать; если нет — баг кеша |

## Флаги/симптомы

- `code=1` до SOCKS + ICE connected = srv не в комнате (wedged), нужен другой room
- `preferCache` на LTE без `override` = старый room из SharedPreferences
- Серые экраны YouTube при живом `tunnelReady` = узкий Telemost/vp8, не «нет интернета»
