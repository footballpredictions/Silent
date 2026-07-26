# olcrtc (вариант 2 обхода)

Зашифрованный TCP-over-WebRTC туннель ([openlibrecommunity/olcrtc](https://github.com/openlibrecommunity/olcrtc)).
На Silent VPN — **параллельный** debug-путь рядом с WDTT/VK, без WireGuard.

## Масштаб 1000+ (Улей / соты)

- Таблица `olcrtc_rooms` + sticky `olcrtc_room_sticky` (не комната на юзера).
- Assign: sticky fingerprint → active room с `online_count < max_clients` (default 12).
- Heartbeat: `POST /api/vpn/olcrtc-heartbeat` (PC/Android debug).
- Draining в админке Bypass → пул комнат.
- Unit на Улье: `python scripts/apply_olcrtc_units_from_db.py`
- Unit на соте: `deploy_olcrtc_cell.py <ip>` + `POST /api/admin/bypass/olcrtc/rooms/{id}/push-cell` (cell-agent `/v1/olcrtc/apply`).
- Агент: `target_capacity` (дефолт **1100**) + `target_free_ratio` (~10% под нагрузкой). Jitsi расширяет пул **без** аккаунтов.
- Прогрев на Улье: `python scripts/seed_olcrtc_mass_pool.py` (`OLCRTC_TARGET_CAPACITY`, `OLCRTC_MAX_CLIENTS`).
- Метрики: `GET /api/admin/bypass/olcrtc/pool-metrics` (`ready_for_1000` при capacity≥1100).

## Схема

```
клиент → TUN (sing-box / hev) → olcrtc cnc SOCKS5 → Jitsi|WB|Telemost → olcrtc srv (Улей) → интернет
```

## Пул комнат (все провайдеры)

Одна комната **не** тянет PC + телефон одновременно.

| Slot | systemd | data-dir | Клиенты |
|------|---------|----------|---------|
| `pc` | `olcrtc@pc` | `data-pc` | PC |
| `android` | `olcrtc@android` | `data-android` | Android / TV |

**Важно:** один systemd-unit = один провайдер + один слот. Нельзя склеивать jitsi+wb+telemost failover в одном процессе — srv залипает на первом живом (обычно Jitsi), а клиент на Телемосте ждёт peer вечно.

Unit’ы: `olcrtc@pc-jitsi`, `olcrtc@pc-telemost`, `olcrtc@pc-wbstream`, `olcrtc@android-jitsi`, …

| Провайдер | Transport (default) | Создание комнаты |
|-----------|---------------------|------------------|
| Jitsi | `datachannel` | guest URL, без аккаунта |
| WB Stream | `vp8channel` | вручную / room-agent (аккаунт) |
| Телемост | `vp8channel` | вручную / room-agent (аккаунт) |

`GET /api/vpn/olcrtc-config?device_type=pc|android&fingerprint=…` выдаёт `room` sticky по типу устройства **для каждого** провайдера.

**LTE / DPI:** `meet.egovm.ru` часто рвёт WebSocket на мобильном → Android Jitsi на `meet.playform.ru`; для LTE предпочтительнее WB / Telemost (свежие room id).

Seed/upgrade без смены crypto_key:

```powershell
cd backend
python scripts\configure_olcrtc_prod.py
```

Android WB placeholder (`…ANDROID-REPLACE`) не отдаётся клиентам — замени свежим ID с сайта или через агента.

## Агент комнат (отдельно от VK)

`ai/olcrtc_room_agent.py` — **не** расширяет VK-агент хешей.

- Создаёт **Jitsi + Telemost + WB Stream** (не только Jitsi).
- Не делает рандомную регистрацию. Нужен один раз `storage_state` (cookies) Яндекс/WB.
- Chromium крутится на **хосте Улья** (systemd `silent-olcrtc-host-provision`, `:9101`), API в Docker вызывает его.
- Цикл ~30 мин: heal `error` → догнать `target_rooms_telemost/wbstream` → Jitsi до `target_capacity` → YAML.

```powershell
# 1) Host Playwright на VPS
cd backend
python scripts\deploy_olcrtc_host_provision.py

# 2) Один раз залогинься локально и вставь JSON в админке «Агент комнат»
pip install playwright
playwright install chromium
python scripts\olcrtc_room_provision_host.py login telemost
python scripts\olcrtc_room_provision_host.py login wbstream
# файлы: update/olcrtc/agent_states/*_state.json → вставить в админку

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
