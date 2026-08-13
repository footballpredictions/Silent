# PLAN — olcrtc 2.0 (продукт: session-mode + агент)

Дата: 2026-08-11  
Статус: **цель = продукт на 100–500+ online**, не smoke одной комнаты.  
Жёстко: exit и create комнат — **только на соте**. Playwright/Chromium **никогда** рядом с `wdtt` на Улье.

## Что заказчик хочет (канон)

Как у VK-хешей / olcrtc v1 **session-mode**:

1. Клиент включает «Телемост» → `GET /api/vpn/olcrtc2-config`  
2. Backend **сам** выдаёт комнату под fingerprint (sticky)  
3. Если комнаты нет → **агент создаёт** новую (1 юзер = 1 комната, `max_clients=1`)  
4. Leave / stale heartbeat → **teardown** комнаты + unit на соте  
5. Одновременно могут сидеть **сотни** людей — у каждого своя комната/сессия  
6. Админ **не** вставляет Room ID вручную для каждого юзера (ручная комната — только diag)

Одна галка «Room ID» в админке — **временный stub**, не продукт. Заменяется агентом.

## Носители

| Канал | Носитель | Exit |
|-------|----------|------|
| VK | WDTT | Улей `wdtt.service` |
| Телемост / WB | olcrtc 2.0 | **Сота** (`olcrtc2@…`), не queen |

## Поток продукта

```text
Клиент (PC/Android debug → потом release)
    → GET /olcrtc2-config?fingerprint=&device_type=
    → queen API: sticky | create-on-demand
         ├─ DB: Olcrtc2Room + Sticky (max=1)
         ├─ create room: cell-agent / host на СОТЕ (не Улей)
         └─ apply unit: olcrtc2@<id> на СОТЕ (Memory/CPU quota)
    → клиент: olcrtc2-cnc join room → AEAD/smux → SOCKS → WG/TUN
    → heartbeat
    → leave / stale → teardown room+unit на соте
```

## Фазы (переставлены под продукт)

### Phase 0–2 — фундамент ✅
- Go `olcrtc2` (carrier Telemost, AEAD, smux, cnc/srv)
- Деплой бинаря на Соту 1, изоляция от WDTT

### Phase P (продукт session) — **smoke PASS 2026-08-11**
- [x] Модели `Olcrtc2Room` / `Olcrtc2Sticky`
- [x] `olcrtc2_assign.py`: sticky + create on demand + leave teardown + heartbeat
- [x] `GET /olcrtc2-config` → assign
- [x] Агент `ai/olcrtc2_room_agent.py`: prune stale
- [x] Create Telemost на **соте** `:9101` (Playwright)
- [x] cell-agent: `/v1/olcrtc2/apply|teardown|create`
- [x] Админка: агент + pool stats
- [x] Deploy host-provision на Соту 1 + enable agent
- [x] Server smoke: assign → unit → release
- [ ] PC debug live YouTube (ручной тест)
- [ ] Android native olcrtc2
- [ ] Loadtest 100 / 500 session

### Phase C — клиенты
- [ ] PC debug: уже cnc; переключить на assign-конфиг
- [ ] Android: **native olcrtc2** (обязательно для выбора в меню)
- [ ] Release: после green на 50–100 session

### Phase W — WB Stream
- JWT create/delete из `olcrtc_wb_api.py` в тот же assign

### Phase H — harden
- 100 / 500 online loadtest, LTE, OTA, лимиты Memory/CPU на соте

## Жёсткие запреты

- Playwright / Chromium на Улье рядом с `wdtt`
- Одна общая комната на всех как «продукт»
- olcrtc2-srv на `132.243.234.162`
- Одновременный WDTT + olcrtc2 в одном клиентском процессе

## Критерий «готово к продукту»

1. VK на Улье без регрессии.  
2. 100+ одновременных Telemost-сессий на соте (assign → ready → YouTube → leave teardown).  
3. Админ не клепает Room ID руками.  
4. Android и PC переключают VK ↔ Телемост без kill app.
