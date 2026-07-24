# olcrtc (вариант 2 обхода)

Зашифрованный TCP-over-WebRTC туннель ([openlibrecommunity/olcrtc](https://github.com/openlibrecommunity/olcrtc)).
На Silent VPN — **параллельный** debug-путь рядом с WDTT/VK, без WireGuard.

## Схема

```
клиент → TUN (sing-box / hev) → olcrtc cnc SOCKS5 → Jitsi|WB|Telemost → olcrtc srv (Улей) → интернет
```

## Пул комнат (MVP)

Одна Jitsi-комната **не** тянет PC + телефон одновременно (и не масштабируется на 1000+).

| Slot | Комната | systemd | Клиенты |
|------|---------|---------|---------|
| `pc` | `https://meet.egovm.ru/SilentVpnOlcrtcHive` | `olcrtc@pc` | PC |
| `android` | `https://meet.playform.ru/SilentVpnOlcrtcHiveAndroid` | `olcrtc@android` | Android / TV |

`GET /api/vpn/olcrtc-config?device_type=pc|android&fingerprint=…` выдаёт `room` + `assigned_slot` sticky по типу устройства.

На Улье: **один процесс srv на комнату**, **разные `data-pc` / `data-android`**.

**LTE / DPI:** `meet.egovm.ru` часто рвёт WebSocket на мобильном. Android-слот → `meet.playform.ru`. Дополнительно CONNECT-прокси Улья `:8080` (`jitsi_https_proxy`, `deploy_olcrtc_proxy.py`) — на случай если olcrtc учитывает `HTTPS_PROXY`.

Seed/upgrade без смены crypto_key:

```powershell
cd backend
python scripts\configure_olcrtc_prod.py
```

## Админка

Раздел **Варианты обхода** (`/bypass`):

1. VK / WDTT — как раньше  
2. olcrtc — `crypto.key`, **пул комнат Jitsi** (slot id / URL / device_types), «Записать YAML»

## API

| Метод | Путь | Назначение |
|-------|------|------------|
| GET/PUT | `/api/admin/bypass/olcrtc` | настройки (+ `providers.jitsi.rooms[]`) |
| POST | `/api/admin/bypass/olcrtc/generate-key` | новый key |
| GET | `/api/admin/bypass/olcrtc/server-yaml` | превью (`files`: pc/android/default) |
| POST | `/api/admin/bypass/olcrtc/apply` | запись `update/olcrtc/server*.yaml` |
| GET | `/api/vpn/olcrtc-config?device_type=&fingerprint=` | публичный конфиг (room из пула) |

## Деплой srv на Улей

```powershell
cd backend\admin-ui
npm run build
cd ..
# положить linux-бинарь в backend\olcrtc\olcrtc (или OLCRTC_BIN=...)
python scripts\deploy_olcrtc.py
```

На VPS:

- бинарь + yaml: `/opt/silent-vpn/olcrtc/` (`server-pc.yaml`, `server-android.yaml`, legacy `server.yaml`)
- systemd: `olcrtc@.service` → `olcrtc@pc`, `olcrtc@android` (legacy `olcrtc.service` отключается при пуле)

Бинарь не в git — собрать у себя (`mage build` / `mage cross`) или скачать release.

## Клиенты (только debug)

- PC / Android: меню «Варианты обхода» → вариант 2 → Jitsi / WB Stream / Телемост  
- Release всегда форсирует вариант 1 (WDTT/VK)
- В логах: `olcrtc-config ok slot=android room=…HiveAndroid` — проверка, что пул сработал
