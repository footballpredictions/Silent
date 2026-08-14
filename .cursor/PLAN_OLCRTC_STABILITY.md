# ПЛАН — olcrtc: комнаты, конфиги, меню обхода

Дата: 2026-08-14  
Статус: **код влит (A–D), API задеплоен.** 2026-08-14 вечер: Сота1 warm срезан 73→11 (cap TM=2); Android recover без 60с assign на первом stream_dead. Endurance — ручной прогон на новом debug APK.  
Цель: стабильный olcrtc2 (Telemost + WB) на PC и Android, в т.ч. LTE с белыми списками оператора.

Полный контекст сервиса: WireGuard → WDTT/VK TURN **или** TUN→SOCKS → olcrtc2-cnc → Telemost/WB → olcrtc2-srv на соте.

---

## Канон (что должно быть)

| Правило | Значение |
|---------|----------|
| Occupancy | **1 клиент = 1 комната** (WB уже так; Телемост сейчас `max_clients=3` — исправить) |
| Leave | soft: снять sticky, комнату оставить в warm (урок session-mode 11.08: teardown на leave убивал кеш) |
| Failure / carrier dead | teardown этой комнаты + unit |
| Доставка конфига | **только через VPN-туннель** `10.66.66.1`, если публичный nip.io недоступен (БС) |
| Dual-cache | слоты TM и WB **не затирают** друг друга |
| Меню PC | как 1.0.160: выбор pending + кнопка **«Применить» внизу** |

Не путать с session-mode 11.08 (`leave=teardown`). Нужна **1:1 занятость**, не уничтожение комнаты при каждом выкл.

---

## Проблема 1 — комнаты отваливаются (WB / Телемост)

### Симптом
Peer живёт минуты, потом ICE/RTP closed, SOCKS мёртв, UI зелёный или reconnect на 404.

### Корни (backend + клиенты)

1. **Shared Telemost `max_clients=3`** (`olcrtc2_assign.py`: `TELEMOST_MAX_CLIENTS = 3`). Узкий vp8channel: сосед по комнате рвёт SFU → падают все. WB уже `WBSTREAM_MAX_CLIENTS = 1`.
2. **Heartbeat не доходит на БС.** Android: Silent в disallow → nip.io с underlying режется whitelist. PC: `tunnel-api-request` режет timeout до **8 с** и падает в **public HTTPS**. Sticky протухает (`HEARTBEAT_STALE_SEC=300`) → prune снимает сессию; excess warm может tear комнату.
3. **Ложный failure → teardown.** Клиент шлёт `/olcrtc2-room-failure` при transient SOCKS; сервер hard-teardown. Сосед на той же TM-комнате тоже мёртв.
4. **Кеш мёртвой room.** Dual-cache + preferCache поднимает join 404 (WB) / code=1 (TM).
5. **Агент.** Carrier HTTP-join на WB warm опасен (antibot/404); prune excess при пропавшем sticky.

### Решение (порядок)

**B1. Occupancy 1:1**
- `TELEMOST_MAX_CLIENTS = 1` (как WB).
- Assign: только комнаты с `stickies == 0` (не `online < 3`).
- Heal БД: `UPDATE olcrtc2_rooms SET max_clients = 1` для telemost **и** wbstream.
- Удалить/не запускать `heal_olcrtc2_max_by_provider.py` (там TM=3, WB=25) и `heal_olcrtc2_pool_max_clients.py` (всем 25).

**B2. Heartbeat только по data-plane**
- Android: HB/leave/failure **только SOCKS** `127.0.0.1:8808` (уже начато 13.08) — добить, чтобы не было fallback на underlying.
- PC: HB через SOCKS olcrtc **или** строго `10.66.66.1` без public fallback; timeout ≥15 с, не `Math.min(..., 8000)`.
- Prune: не tear комнаты с `last_healthy_at < 15 мин` даже без sticky (уже `RECENT_HEALTHY_KEEP_SEC=900` — проверить, что работает на проде).

**B3. Failure ≠ reconnect spam**
- `reportOlcrtcRoomFailure` только после liveness (missed_pong + SOCKS fail streak), не на первом ICE glitch.
- После failure: wipe **только** слот этого провайдера, не соседний TM/WB.
- Не стартовать `lastFailed` room из кеша.

**B4. Проверка**
- Админка: online sticky, `max_clients=1`, нет 2+ fp на одну room.
- Endurance 40 мин WB+TM, PC+Android, Wi‑Fi и LTE.
- `loadtest_olcrtc2_sessions.py`: unique rooms ≈ N fingerprint.

---

## Проблема 2 — конфиги доставляются криво / затираются

### Симптом (заказчик)
- ПК: Wi‑Fi без БС (или редко) — в целом живёт.
- Android: Wi‑Fi без БС — ок; **мобильный интернет почти всегда белые списки** → до API Улья **только через VPN** (`10.66.66.1`), nip.io с LTE мёртв.

### Корни

1. **PC `tunnel-api-request`** (`pc/src/main/main.js`): даже при `timeout: 90_000` с renderer режет до 8 с → public nip.io. На БС public не работает. На Wi‑Fi public **создаёт второй assign** на тот же fingerprint → **затирает** комнату под живым peer.
2. **Android public fallback** после tunnel fail: `GET https://nip.io/olcrtc2-config` на LTE hang/timeout; иногда 200 с **новой** room → overwrite dual-cache.
3. **`saveOlcrtcCache` пишет весь `cfg`.** API отдаёт `{ providers: { telemost: … } }` без соседа — ок. Но если в JSON случайно два слота / denied — чужой ключ затирается. Нужна запись **только запрошенного** provider.
4. **prefetchBoth на login/sync** заново assign’ит оба слота и может сменить room, пока пользователь на старой.
5. **Denied/пустой ответ** в части путей всё ещё может пройти в cache (PC `parseAndCache` сохраняет при `enabled && crypto_key`, без жёсткого `shouldAcceptAssign` как на Android).

### Решение (порядок)

**C1. Канал доставки конфига**

| Сеть | Как брать `/olcrtc2-config`, HB, failure |
|------|------------------------------------------|
| Wi‑Fi без БС, VPN выкл | public nip.io **или** ephemeral VK → tunnel |
| LTE / БС | **только** ephemeral VK bootstrap → `http://10.66.66.1:8000` → стоп bootstrap. Public **запрещён** |
| VPN/olcrtc уже up | только tunnel `10.66.66.1` или SOCKS. **Без** public fallback |

- PC: для путей `/olcrtc2-config`, `/olcrtc2-heartbeat`, `/olcrtc2-room-failure` — не резать timeout до 8 с; **не** `viaPublic()` если tunnel был поднят (5xx/timeout → retry tunnel, не nip.io).
- Android: `fetchOlcrtcConfigTunnelOnly` как основной путь на LTE; public только явный Wi‑Fi probe с коротким timeout, без записи в кеш при fail.

**C2. Изоляция dual-cache**
- `saveOlcrtcCache(cfg, forProvider)`: в ключ `v12/v16_<provider>` класть JSON **только с этим слотом**. Соседа не трогать.
- Не overwrite слота, если `room` совпадает с текущим connected (ignore same-room refresh ок; смена room — только после failure/leave).
- Denied / `pool_denied` / пустой room → кеш не писать (PC = паритет `OlcrtcSessionPolicy.shouldAcceptAssign`).

**C3. Prefetch**
- `prefetchOlcrtcBothProviders`: сеть **только если слот пуст**. Живой слот не refresh.
- Login/sync не должен менять room активного VPN.

**C4. Проверка**
- Лог: `olcrtc-config OK via tunnel` на LTE; **ноль** `nip.io/olcrtc2-config` при БС.
- После fetch TM слот WB не меняется (юнит-тест PC + Android).
- Wi‑Fi и LTE: connect по кешу без «нет конфига».

---

## Проблема 3 — меню обхода PC как в 1.0.160

### Сейчас
`pc/src/renderer/components/MenuBypassPanel.tsx`: выбор **применяется сразу** (без «Применить»). При живом VPN — стоп и смена. Android уже pending + диалог «Применить?».

### Нужно
Как 1.0.160 и Android: радио только ставят **pending**, подтверждение — диалог **«Применить?»** с строкой **«VK → olcrtc»** (не футер «Было/Будет»). Пока не нажали — prefs/VPN не трогать.

### Решение (только PC, UI)

**U1.** Состояние `pendingFamily` / `pendingVk` / `pendingOlc` (как Android).
**U2.** Нижний диалог как Android 1.0.160: заголовок «Применить?», строка смены, Отмена + Применить. Не футер VkCredMode.
**U3.** Apply: если VPN up — стоп, затем `setBypassFamily` / `setOlcrtcProvider`. Dual-cache без сети (как Android Apply).
**U4.** Пока VPN up — можно выбрать pending, Apply сам остановит.
**U5.** Тема: цвета из `clientTheme`, без хардкода hex.

Референс UI: Android `MenuBypassScreen` AlertDialog (не `MenuVkCredModePanel`).

---

## Порядок работ (по команде)

Не делать всё сразу. Три фазы, каждая с проверкой.

### Фаза A — меню PC (быстро, без деплоя backend)
1. `MenuBypassPanel.tsx` → pending + кнопка внизу.
2. Debug-сборка PC, ручной клик VK↔olcrtc / TM↔WB.

### Фаза B — occupancy 1:1 (backend)
1. `TELEMOST_MAX_CLIENTS = 1`, assign только empty rooms.
2. Heal прод-БД max_clients=1.
3. Запретить старые heal-скрипты max=3/25.
4. `deploy_api.py`. Смоук assign: 5 fp → 5 разных TM rooms.

### Фаза C — доставка конфигов (PC + Android)
1. PC: olcrtc API без public fallback при живом tunnel; timeout 90 с.
2. Android: LTE = tunnel-only + ephemeral VK; public не затирает кеш.
3. Изоляция dual-cache + тесты.
4. HB через SOCKS/tunnel на обоих клиентах.
5. Debug APK + PC debug. Прогон Wi‑Fi / LTE БС.

### Фаза D — устойчивость комнат
1. Failure только после liveness streak.
2. Не стартовать lastFailed room.
3. Endurance 40 мин WB+TM.

Деплой: backend `python scripts/deploy_api.py` (из `backend/`). Клиенты — debug, не release, пока три фазы зелёные. **Перед release спросить bootstrap VK-хеш.**

---

## Файлы (ориентир)

| Слой | Файлы |
|------|--------|
| Backend | `app/services/olcrtc2_assign.py`, `olcrtc2_settings.py`, `ai/olcrtc2_room_agent.py`, `app/api/vpn.py` |
| PC | `src/renderer/components/MenuBypassPanel.tsx`, `bypassStore.ts`, `src/main/main.js` (`tunnel-api-request`) |
| Android | `Repository.kt` (fetch/save cache), `OlcrtcSessionPolicy.kt`, `OlcrtcTunnelManager.kt` (SOCKS HB), `MenuBypassScreen.kt` (не ломать pending+Apply) |
| Тесты | `test_olcrtc2_session_rules_unit.py`, `OlcrtcSessionPolicyTest.kt`, новый тест save-cache isolation |
| Запрещено трогать | `heal_olcrtc2_pool_max_clients.py` / `heal_olcrtc2_max_by_provider.py` без правки под max=1 |

---

## Критерий «готово»

1. Один fingerprint — одна комната TM и отдельно одна WB. В админке нет `online>1` на room.
2. LTE с БС: конфиг только через `10.66.66.1`; слот соседа не затирается.
3. WB/TM держат ≥20–40 мин на PC и Android (Wi‑Fi + LTE) без 404/code=1 из-за нашего prune/overwrite.
4. PC меню: выбор не применяется до кнопки внизу.
