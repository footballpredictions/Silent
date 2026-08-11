# olcrtc (вариант 2 обхода)

Зашифрованный TCP-over-WebRTC туннель ([openlibrecommunity/olcrtc](https://github.com/openlibrecommunity/olcrtc)).
На Silent VPN — **параллельный** путь рядом с WDTT/VK.

## Session-mode («как VK») — текущий прод (2026-08-11)

Модель lifecycle как у VK-хешей: **создал комнату под сессию → srv host в комнате → при leave удалил**.

| Правило | Значение |
|---------|----------|
| Create | on demand в `ensure_session_room` при `/olcrtc-config` |
| max_clients | **1** (одна сессия = одна комната = один unit) |
| Leave | `olcrtc-heartbeat online=false` / failure → `release_session_room` (sticky + delete + `systemctl stop`) |
| Playwright | только `silent-olcrtc-host-provision`, `Semaphore(1)` / `OLCRTC_HOST_CREATE_PARALLEL=1`; in-container fallback **выкл** (`OLCRTC_HOST_ONLY=1`) |
| Агент | prune host-unhealthy + heal `error` + optional `bootstrap_warm`; **без** `_autoscale_pool` / create-spam |
| Провайдер | **Telemost** (WB/Jitsi выкл. в агенте до стабилизации) |

Wipe / reset:

```powershell
cd backend
python scripts\olcrtc_session_reset.py
python scripts\olcrtc_enable_session_agent.py   # session_mode + enabled
python scripts\olcrtc_smoke_session.py          # PC+Android assign/release
```

Админка Bypass → Агент: чекбокс **Session-mode**, без «держать свободных ≥4».

Legacy pool-mode (`session_mode=false`) оставлен в коде, на проде не использовать.

## Legacy: масштаб 1000+ (отключён)

- Таблица `olcrtc_rooms` + sticky `olcrtc_room_sticky`.
- Старый shared-пул + `min_free_per_slot` autoscale — вызывал Chromium-шторм на Улье (инцидент 11.08).
- Документ ниже сохранён как справочник API/unit’ов.

## Схема

```
клиент → TUN (sing-box / hev) → olcrtc cnc SOCKS5 → Telemost → olcrtc srv (Улей) → интернет
```

## Пул / слоты

Одна комната **не** тянет PC + телефон одновременно.

| Slot | systemd | data-dir | Клиенты |
|------|---------|----------|---------|
| `pc` | `olcrtc@pc-telemost*` | `data-pc-telemost*` | PC |
| `android` | `olcrtc@android-telemost*` | `data-android-telemost*` | Android / TV |

| Провайдер | Transport (default) | Создание комнаты |
|-----------|---------------------|------------------|
| Телемост | `vp8channel` | session ensure / host Playwright |
| WB Stream | `vp8channel` | выкл. до стабилизации |
| Jitsi | — | purge |

`GET /api/vpn/olcrtc-config?device_type=pc|android&fingerprint=…&provider=telemost` → session room.

## Агент комнат (отдельно от VK)

`ai/olcrtc_room_agent.py` — **не** расширяет VK-агент хешей.

- Session-mode: prune + heal error; `bootstrap_warm` (0–1 spare).
- Chromium на **хосте Улья** (`silent-olcrtc-host-provision`, `:9101`).
- Цикл ~2.5 мин.

```powershell
cd backend
python scripts\deploy_olcrtc_host_provision.py
python scripts\olcrtc_session_reset.py
```

# 3) В админке: агент ON → «Создать недостающие сейчас»
```

Fallback: room id вручную → «Записать YAML» → `deploy_olcrtc.py`.

## Админка

Раздел **Варианты обхода** (`/bypass`):

1. VK / WDTT — как раньше  
2. olcrtc — `crypto.key`, **пул комнат** у Jitsi / WB / Telemost, «Записать YAML», блок **Агент комнат**

## API

| Метод | Путь | Назначение |
|-------|------|------------|
| GET/PUT | `/api/admin/bypass/olcrtc` | настройки (+ `providers.*.rooms[]`) |
| POST | `/api/admin/bypass/olcrtc/generate-key` | новый key |
| GET | `/api/admin/bypass/olcrtc/server-yaml` | превью (`files`: pc/android/default) |
| POST | `/api/admin/bypass/olcrtc/apply` | запись `update/olcrtc/server*.yaml` |
| GET/PUT | `/api/admin/bypass/olcrtc/room-agent` | enable / статус агента |
| POST | `/api/admin/bypass/olcrtc/room-agent/run` | создать недостающие комнаты сейчас |
| PUT | `/api/admin/bypass/olcrtc/room-accounts` | storage_state / path аккаунтов |
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
- systemd: `olcrtc@.service` → `olcrtc@pc`, `olcrtc@android`

Бинарь не в git — собрать у себя (`mage build` / `mage cross`) или скачать release.

## Клиенты (только debug)

- PC / Android: меню «Варианты обхода» → вариант 2 → Jitsi / WB Stream / Телемост  
- Release всегда форсирует вариант 1 (WDTT/VK)
- Кэш конфига: PC `olcrtc_config_cache_v4`, Android `olcrtc_config_cache_v5`
