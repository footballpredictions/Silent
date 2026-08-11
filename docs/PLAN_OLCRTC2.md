# PLAN — olcrtc 2.0 (WDTT-совместимый носитель Телемост / WB)

Дата: 2026-08-11  
Статус: старт реализации (каркас). **На Улей рядом с `wdtt` не деплоить**, пока нет изоляции на соте.

## Цель

Один продукт Silent VPN с **двумя носителями**, которые **не убивают друг друга**:

| Канал | Носитель | Exit |
|-------|----------|------|
| VK | существующий **WDTT** (DTLS/RTP → VK TURN) | `wdtt.service` на Улье |
| Телемост / WB | **olcrtc 2.0** (Pion headless → SFU) | **отдельная сота / VPS**, не queen |

«Совместим с WDTT» для нас значит:

1. Снаружи для приложений — тот же **WireGuard** (как сейчас у VK).
2. Та же **модель сессии**, что у VK-хешей: create on demand → leave = teardown.
3. Один клиентский фасад (`BypassRouter`): VK | Телемост | WB.
4. Общий crypto/session API на backend (не Playwright-шторм на Улье).
5. **Жёсткая изоляция CPU/RAM** от `wdtt` (главный урок 2026-08-11).

Не значит: впихнуть Телемост/ВБ внутрь текущего бинаря `wdtt-server` без нового транспорта.

## Что изучили на GitHub

| Репо | Урок |
|------|------|
| [openlibrecommunity/olcrtc](https://github.com/openlibrecommunity/olcrtc) | carrier = jitsi/telemost/wbstream; transport DC/VP8; SOCKS cnc↔srv. Наш v1 был этим + Playwright на Улье → конфликт с WDTT. |
| [kulikov0/whitelist-bypass](https://github.com/kulikov0/whitelist-bypass) | **Headless Pion** creator/joiner для VK/Telemost/WB/DION; без браузера; session create; SOCKS; VP8 когда DC режут. Ближайший референс для 2.0. |
| [Kavun-Sama/jazztun](https://github.com/Kavun-Sama/jazztun) | Salute Jazz как отдельный носитель (позже, не MVP). |
| [ildarmaga/wdtt](https://github.com/ildarmaga/wdtt) | WDTT = WG через VK TURN; подтверждает: носитель VK ≠ носитель Яндекс/ВБ. |
| net4people/bbs#618 | Паттерн: carrier adapter снизу, tunnel mux сверху, headless Pion. |

## Архитектура 2.0

```text
Apps → VpnService/WG
         │
         ▼
   Silent client (PC/Android)
         │  BypassRouter
         ├─ family=wdtt  → libclient/WDTT → VK TURN → queen wdtt-server → net
         └─ family=olcrtc2
               → olcrtc2-cnc (Pion) → Telemost|WB SFU
               → olcrtc2-srv (на СОТЕ) → net
```

### Слои Go-модуля `olcrtc2`

1. **carrier/** — адаптеры `telemost`, `wbstream` (join/create, ICE, pub/sub).
2. **tunnel/** — AEAD + mux (smux или свой framing как WDTT-friendly datagram).
3. **edge/** — `cnc` (SOCKS5 + optional UDP ASSOCIATE) / `srv` (egress).
4. **session/** — create/leave hooks под наш backend API.

MVP transport: **VP8 channel** (Телемост/WB стабильнее DC).  
DC — опционально для WB с account token.

### Backend

- Новый namespace API: `/api/vpn/olcrtc2-config` (не включать старый `/olcrtc-config` на queen).
- Session assign/release как у VK (sticky fingerprint, max=1).
- Room create: **только HTTP API** (WB уже есть `olcrtc_wb_api.py`; Telemost — API/headless, **без Playwright на Улье**).
- Deploy srv **только на cell** (`deploy_olcrtc2_cell.py`), UFW, Memory/CPU quota.

### Клиенты

- Снова пункт меню, но `family=olcrtc2` и бинарь `olcrtc2`, не старый olcrtc.
- Взаимное исключение: WDTT↑ ⇒ olcrtc2↓ и наоборот.
- Prefetch конфига через tunnel после логина (как hashes).

## Фазы

### Phase 0 — каркас (сейчас)
- [x] План в `.cursor/PLAN_OLCRTC2.md`
- [ ] Go module `backend/olcrtc2/` + interface Carrier
- [ ] stubs telemost/wbstream
- [ ] unit test compile
- [ ] **не** трогать prod wdtt / не поднимать на queen

### Phase 1 — srv/cnc loopback
- SOCKS cnc ↔ srv через mock carrier (без реального SFU)
- Smoke на localhost

### Phase 2 — Telemost headless
- Join существующей комнаты (API create отдельно)
- Exit на **тестовой соте**

### Phase 3 — WB Stream
- Переиспользовать JWT create/delete из `ai/olcrtc_wb_api.py`
- Account token для srv

### Phase 4 — клиенты + админка
- Меню, connect path, admin «olcrtc 2.0»
- Только после Phase 2 green на соте

### Phase 5 — harden
- CPU/mem limits, session GC, LTE проверка, OTA

## Жёсткие запреты

- Playwright / Chromium на Улье рядом с `wdtt`
- Shared pool autoscale 1000+ на queen
- Одновременный WDTT + olcrtc2 в одном процессе клиента
- Деплой olcrtc2-srv на `132.243.234.162` до явного OK

## Критерий «готово к продукту»

1. VK на Улье без регрессии (connect &lt; 15с при ~100 online).
2. Телемост и WB на соте: assign → tunnelReady → YouTube TCP → leave teardown.
3. Переключение VK↔Телемост без kill app.
4. Админка не показывает мёртвый olcrtc v1.
