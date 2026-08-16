# TASKS — Silent VPN

Формат: `[ ]` — не выполнено, `[x]` — выполнено.  
Agent приступает к **первой невыполненной** задаче.  
Статус сверен с коммитами `origin/main`, `origin/pc`, `origin/android` (2026-06-20).

---

## Открытые задачи

### olcrtc стабильность (план 2026-08-14)

Полный план: `.cursor/PLAN_OLCRTC_STABILITY.md`.

- [x] **Фаза A — PC меню обхода как 1.0.160:** диалог «Применить?» + `VK → olcrtc` (не футер Было/Будет)
- [x] **Фаза B — 1 комната на клиента:** Telemost `max_clients=1`; assign empty; heal БД на проде; скрипты max=3/25 исправлены
- [x] **Фаза C — доставка конфигов:** LTE/БС без public fallback при живом tunnel; dual-cache изоляция; PC timeout olcrtc 90с
- [x] **Фаза D — устойчивость (код):** HB через SOCKS/tunnel; failure после liveness streak; lastFailed не стартуем
- [x] **Сота 1 CPU:** warm TM cap=2 (агент больше не ставит 20); prune 73→11 — 2026-08-14
- [x] **Сота 1 idle 20–50% без клиентов:** idle `olcrtc2-srv` warm; TM warm=0, units сняты, CPU≈0% — 2026-08-14
- [x] **PC SOCKS miss после warm=0:** warm TM=1 + retry новой комнаты; debug `build-debug-144543` — 2026-08-14
- [x] **TM Wi‑Fi старт >30с:** без carrier-probe на assign; ICE wait 8с; PC `496328` + APK — 2026-08-14
- [x] **WDTT-баланс мимо olcrtc:** Сота 1/2 не spill; только 3+ / Улей — 2026-08-14
- [x] **Android: не рвать комнату** на liveness/stream_dead — native reconnect; рестарт только process_exit
- [x] **Android: TM freeze / нет конфига WB / вылет VK** — без gstatic-проб на живом туннеле; Apply fetch пустых слотов; hardReset при уходе на VK
- [x] **Сота 1 сеть/CPU:** egress ~320 Мбит ок; снят `CPUQuota=50%` с живых olcrtc2 (без рестарта сессий)
- [x] **Сота 2 сеть/CPU:** то же (WB); egress ~540 Мбит, steal 0%; квота снята без рестарта
- [x] **Android TM reconnect + PC тумблер/лог/обход:** epoch не убивает новый SOCKS; PC статус как Android; лог чистится на connect; bypass commit/localStorage
- [x] **Первая загрузка медленная:** DNS шёл через VP8-несущую; вернули fake-ip (PC sing-box) / `mapdns` 198.19.0.0/16 (Android) — резолв на соте. APK + PC `build-debug-182837` — 2026-08-14
- [x] **olcrtc2 cache safety + меню lock:** без раннего wipe слота на room-failure (Android/PC), debounce failure, soft→hard failure на backend; переключение обхода отключено при VPN ON — 2026-08-14
- [x] **Улей: журнал инцидентов в админке:** отдельный поток только ошибок/падений (`/api/admin/hive/incidents`) с подсказками по DPI/портам/DNS/ресурсам — 2026-08-14
- [x] **Улей: security-инциденты:** фиксация подозрительных вмешательств (admin host guard, brute-force admin/MFA, burst register rate-limit) в том же `/api/admin/hive/incidents` — 2026-08-14
- [x] **Улей: авто-сброс stale online:** если `is_connected=true`, но heartbeat/`last_connected` просрочен — устройство автоматически уходит в offline (фон. maintenance loop) — 2026-08-14
- [x] **olcrtc2 burst warm:** при серии `Нет свободных комнат` временно +1 warm по провайдеру (окно 25с, hold 180с, авто-откат) — 2026-08-15
- [x] **Smart Apply Refresh (Android+PC):** после смены TM/WB — background refresh слота (TTL/dirty-aware, с тайм-бюджетом, без блокировки Apply) — 2026-08-15
- [x] **UX исключений + DNS + splash:** `Выделить все` в исключениях (Android/PC), без авто-выбора в БС; DNS упрощён до `Яндекс (как на сервере)` + `Свой DNS`; тёмный splash на Android — 2026-08-15
- [x] **DNS-регрессия 1.0.161 (YouTube на VK-обходе):** откат к семантике 1.0.160 — дефолт `Как на сервере` (`wg_dns`, в т.ч. `10.66.66.1`), в меню только сервер + `Свой DNS`, миграция сохранённых публичных пресетов; PC-модалка DNS в стиле «Смены обхода» — 2026-08-15
- [x] **Admin UI style unify + PC DNS dark modal:** единый строгий dark-стиль админки (чёрная база, синий/red/green акцент) + fix белого DNS-окна в тёмной теме PC — 2026-08-15
- [x] **VK-обход: убран лишний olcrtc-prefetch:** `prefetchOlcrtcSlotsOnVkTunnel()` снят с post-sync (как в 1.0.160) — `/olcrtc2-config` делал assign комнат на каждом VK-connect; debug APK пересобран — 2026-08-15
- [x] **Hive: видимый online для olcrtc2 по сотам:** backend считает свежие sticky по `cell_id` + админка показывает `wdtt/olcrtc/итого`, чтобы сессии не «терялись» в UI — 2026-08-15
- [x] **Android WB: анти-зависание через несколько минут:** восстановлен recovery при `peer_closed/media_timeout/stream_dead` (WB форсирует liveness-check + restart, TM поведение сохранено) — 2026-08-15
- [x] **olcrtc2: убрать фантомный online в sessions:** assign config больше не «touch» sticky; `pool_stats` считает только свежие sticky (окно heartbeat), чтобы без звонка не висели `sessions` — 2026-08-15
- [x] **Android WB: decrypt/auth desync recovery:** при повторе `decrypt failed / message authentication failed` запускается WB-recover с reassign комнаты (вместо тихой смерти канала) — 2026-08-15
- [x] **Android WB: убрать 1–2 мин подвис после peer closed:** для WB peer должен вернуться в `connected` в grace-окне, иначе сразу recover (не считаем «SOCKS жив» достаточным) — 2026-08-15
- [x] **Android WB: DNS path fix для olcrtc2:** вместо `activeNetwork DNS / 1.1.1.1` используем provider-aware DNS из меню обхода (WB→fallback first), чтобы убрать подвисы от внешнего резолва — 2026-08-15
- [x] **Android WB: fast recover по heartbeat socks-fail:** для WB после 2 подряд `HB socks CONNECT fail` сразу suspect/recover, чтобы не оставлять «зависший» канал — 2026-08-15
- [x] **Android WB: ultra-fast recover по heartbeat socks-fail:** для WB порог снижён до 1 fail (немедленный recover), чтобы убрать даже краткие зависания — 2026-08-15
- [x] **Выбор сервера 1/2/3 = Улей / Сота 1 / Сота 2:** маппинг по номеру соты (не индекс списка), persist `server1/2/3`, login не затирает слот; Android LTE как 1.0.160 (public API first) — 2026-08-15
- [x] **PC: смена сервера сразу после выкл + Android LTE без overlay-рестарта WG:** лок меню по UI, не по умирающему туннелю; LTE API через proxy — 2026-08-15
- [ ] **Проверить VK-обход на debug APK 12:09:** пропали ли серые экраны / задержка 10–20 с; если нет — снять экран «Лог» и смотреть `AppExclusions` (`БС пуст → ЧС`)
- [ ] **Соты: кеширующий DNS** (unbound/dnsmasq) + `OLCRTC2_DNS=127.0.0.1:53` — весь резолв теперь делает `olcrtc2-srv`
- [ ] **Фаза D — endurance:** 40 мин WB+TM Wi‑Fi/LTE на PC+Android debug (ручной прогон; APK + PC `build-debug-182837`)

### Инфраструктура и репозиторий

- [x] Улей (Hive): автоподключение соты по IP + SSH root (wdtt, DNAT tunnel, cell-agent) — 2026-06-20
- [x] Улей: фоновый провижининг, удаление зависших сот, CPU/RAM (хост + cell-agent), upgrade-agent — 2026-06-20
- [x] **Вариант 2 обхода olcrtc** (debug): backend+админка «Варианты обхода», `deploy_olcrtc.py`, PC/Android UI+движок рядом с WDTT — 2026-07-24. Prod: Jitsi pool + `olcrtc@pc`/`@android`.
- [x] **olcrtc room pool MVP (PC≠Android) + Wi‑Fi OK** — 2026-07-24:
  - Разные комнаты: PC `meet.egovm.ru/SilentVpnOlcrtcHive`, Android `meet.playform.ru/SilentVpnOlcrtcHiveAndroid`
  - Разные `data-pc` / `data-android` (общий `data/` ломал одновременную работу)
  - API `GET /api/vpn/olcrtc-config?device_type=&fingerprint=`
  - PC: dial/warm/fake-ip/DNS HTTPS reject; Android: hev TUN + libolcrtc.so
  - **Проверено:** PC + Android **одновременно по Wi‑Fi** работают
  - **LTE:** Jitsi/`meet.egovm.ru` (и смена host) часто режется DPI оператора — отложено
- [x] **olcrtc WB/Telemost room pool + отдельный room-agent** — 2026-07-25: пул pc/android у всех 3 провайдеров; YAML failover в `olcrtc@pc`/`@android`; агент `ai/olcrtc_room_agent.py` (не VK); host Playwright `olcrtc_room_provision_host.py`. Android WB placeholder → заменить свежим ID.
- [x] **olcrtc LTE / мобильный интернет (сервер готов):** Android Telemost room `10347145470417` + unit `android-telemost` active, max=25; assign OK. Android WB — нет cookies аккаунта (агент не создаст). Физический LTE на телефоне: выбрать Телемост в debug. Wi‑Fi pool уже готов.
- [x] **olcrtc масштаб 1000+ (каркас):** `OlcrtcRoom`+sticky+cap+heartbeat, пул в админке (drain), agent `target_free_ratio`, yaml из БД, cell-agent `/v1/olcrtc/apply` + `deploy_olcrtc_cell.py`, клиенты 503/heartbeat — 2026-07-25. Нагрузочный прогон 1000 online — отдельно.
- [x] **olcrtc 1000+ прогрев пула на проде** — 2026-07-25: `seed_olcrtc_mass_pool.py` → capacity ≥1100 (`max_clients=25`), **47 unit’ов active**, agent `enabled` + `target_capacity=1100`, Jitsi auto без cookies; `pool_denied` только если нет ни одного провайдера.
- [x] **olcrtc 1000+ нагрузочный прогон** — 2026-07-25: `loadtest_olcrtc_1000.py` → **pass** (1000 assign, 500pc+500android, unique 22+22, denied 0, 25.5s). Spill: olcrtc бинарь+template на соты `87.58.213.193` / `78.17.74.27` (`deploy_olcrtc_to_hive_cells.py`).
- [x] Документировать YuMoney webhook flow в APIS.md (`POST /api/payments/yumoney/notify`) — 2026-07-25
- [x] **olcrtc pool redesign** — 2026-08-11: on-demand scale при deny, цикл ~2.5м, idle GC 5м, heal sticky clear, админка Обзор/Комнаты/Агент, Playwright finally, wdtt MemoryHigh/Max; задеплоено
- [x] **olcrtc session-mode («как VK»)** — 2026-08-11: create on demand / max_clients=1 / leave=teardown; агент prune+heal без autoscale; Telemost-only; host-only Playwright; wipe `olcrtc_session_reset.py`; smoke PC+Android PASS; PC/Android clear cache on leave
- [x] **olcrtc полностью снят** — 2026-08-11: прод stop units/host-provision; API always disabled; админка без секции 2; PC/Android force WDTT, меню обхода убрано из release
- [x] **olcrtc 2.0 ПРОДУКТ (session-mode + агент)** — 2026-08-11: server smoke PASS; Playwright на Соте 1; Android `libolcrtc2.so` + menu; PC `build-debug-977561`. Инструкция: `.cursor/OLCRTC2_AGENT.md`. Ручной YouTube-тест. **Не на Улей.**
- [x] **olcrtc WB session-mode** — 2026-08-11: create/delete через WB HTTP API (не Playwright; antibot 498 обход); `ai/olcrtc_wb_api.py`; smoke PC+Android PASS; провайдер включён рядом с Телемост — **отозвано** (см. «olcrtc полностью снят»)
- [x] **olcrtc agent: liveness + prune + create** — 2026-07-27: HTTP probe WB/Telemost, удаление мёртвых комнат, sync `auth.token`, create до target; цикл 15м; задеплоено на прод (9/9 alive)
- [x] **Android: fix регрессии ЧС/БС** — 2026-08-11: возвращён `bootstrap-companion` в `excludeKey` (туннель пересоздавался на каждый TURN-адрес и рвал воркеры), БС не тащит Silent в туннель, резолв правил сайтов ушёл в фон; DoH-эксперимент откатан в stash. Проверено на Wi-Fi и мобильном.
- [x] **DNS: «Как на сервере» + свой DNS в release (Android + PC)** — 2026-08-11: меню DNS открыто в release, дефолт не подменяет `wg_dns` (фильтр угроз жив), свой ввод до 3 адресов с валидацией; PC `normalizeDnsValue` больше не игнорирует серверный DNS. Тесты: `DnsPresetTest` + `pc/test/dns.test.js`
- [ ] PC: собрать debug/installer с новым меню DNS и проверить свой DNS на живом подключении

### Продукт / монетизация

- [x] **Оплата YuMoney (кастомный QuickPay) по плану `.cursor/PLAN_PAYMENTS_YUMONEY.md`** — 2026-07-14: backend (10 кошельков через `.env`, per-wallet секрет, `label` высокой энтропии, `SELECT…FOR UPDATE`, `operation_id` идемпотентность, допуск на комиссию, codepro/unaccepted/currency, promo `use_count` при завершении), `GET /payments/status/{label}`, `GET /payments/success-page`, theme-поля `payment_*` (backend + admin-ui + PC + Android). Юнит-тесты **37/37 OK**; **задеплоено на прод**, 2 реальных кошелька настроены и проверены живыми уведомлениями (signature/commission/sum=1-атака/идемпотентность — все ОК). Push во все три ветки (`main`/`pc`/`android`). **Осталось:** релизы PC/Android с новым UI оплаты (`assembleRelease`/`build-installer` + OTA публикация)
- [x] **Баг-фикс: YuMoney `sign` вместо устаревшего `sha1_hash`** — 2026-07-14: реальный тестовый платёж пользователя (15₽) зависал на «ждём подтверждения» — ЮMoney с 18.05.2026 перестали слать `sha1_hash`, шлют только `sign` (HMAC-SHA256 по отсортированным URL-encoded параметрам). Код проверял только старый `sha1_hash` → все реальные уведомления получали 400. Добавлена проверка `sign` (fallback на `sha1_hash`), +6 юнит-тестов (**43/43 OK**), задеплоено на прод и живьём подтверждено на обоих кошельках (`status: completed`). Push `main` + bump Android `1.0.156` + push `android`.
- [x] Тестирование оплаты пользователем завершено (15/20/25₽, все 3 плана, PC + Android) — цены на проде **возвращены** на 199/499/1499 (`.env` → recreate `api` → `deploy_stable.py`), проверено `/api/payments/plans`. Push не требовался (цены — только в `.env` на VPS, не в git)

- [x] Реферальные ссылки + раздел «Бонусы» (backend + PC + Android): промо/реф на регистрации, +30 дней обоим после первой оплаты invitee — 2026-07-09
- [x] Реф-политика growth: лимит 10 наград/30д на inviter + текст «условия могут измениться» — 2026-07-09
- [x] Админка «Бонусы» (бывш. Промокоды) + статистика рефералов/промо; cleanup тестовых ref.* — 2026-07-09
- [x] Тексты «Бонусы»: одно общее описание (intro), без дубля внизу — 2026-07-09
- [ ] После ~1000 пользователей: пересмотреть реф-условия (+15/+15 или бонус только inviter / только quarterly+)

### iOS-клиент

- [ ] Доработать iOS до паритета с Android/PC (bootstrap, tunnel API, ConfigSync, OTA) — на `origin/ios` только `e701e3f`
- [ ] Подключить server-driven UI (`ThemeData`) на iOS
- [ ] Рефералка / «Бонусы» на iOS (паритет с PC/Android)

### QA / ручное тестирование

- [x] Android: прогнать OTA + ConfigSync на мобильной сети vs Wi-Fi (instrumented на устройстве: Wi‑Fi/LTE/LTE+VPN, `OK (17 tests)`) — 2026-07-08
- [ ] PC: прогнать полный цикл bootstrap → login → connect → OTA через tunnel → disconnect
- [x] PC throughput baseline: ~75–78 Мбит @108, connect ≤5с (`26431a9` на `pc`) — 2026-07-09; дальше улучшать от этого профиля

### Следующие релизы

- [x] Android: bump version → `1.0.154` → push `origin/android` (Telegram parity PC) — 2026-07-11
- [x] Android: bump version → `1.0.155` → push `origin/android` (VK Calls Wi‑Fi DPI) — 2026-07-12
- [x] Android: bump version → `1.0.156` → push `origin/android` (YuMoney payment flow) — 2026-07-14
- [x] Android: bump version → `1.0.159` → push `origin/android` (theme bg + Ugoos/TOX после 158) — 2026-07-22
- [ ] Android: `assembleRelease` → `python scripts/deploy_release.py ...` (OTA 1.0.159)
- [x] PC: bump version → `1.0.154` → push `origin/pc` (Telegram latency + exclusions) — 2026-07-11
- [x] PC: bump version → `1.0.155` → push `origin/pc` (WG 1.1 + Wi‑Fi VK Calls) — 2026-07-12
- [x] PC: bump version → `1.0.156` → push `origin/pc` (installer WG repair) — 2026-07-13
- [x] PC: bump version → `1.0.159` → push `origin/pc` (theme/admin/Win10 wg-turn после 158) — 2026-07-22
- [ ] PC: `build-installer.bat` → `python scripts/deploy_release.py ...` (OTA 1.0.159)

---

## Выполнено (по коммитам)

### Memory Bank / документация

- [x] Обновить Memory Bank (MEMORY_BANK.md, APIS.md, TASKS.md) — 2026-06-20
- [x] Документировать деплой по веткам (`backend/scripts/`, `pc/scripts/`, `android/scripts/`) — 2026-06-18
- [x] SSH-секреты в `.env.deploy` через `_deploy_common.py` — 2026-06-18
- [x] Убрать старые deploy/diag-скрипты из корня и `android/scripts/inspect_*.py` — 2026-06-18

### Backend (`origin/main`)

- [x] Улей / Соты (Hive): модель HiveCell, балансировка VPN, admin «Улей», cell-agent, proc_stats, deploy_hive — 2026-06-20
- [x] `GET /api/vpn/sync-state` для ConfigSync — `d46bce3`, `de4e241`
- [x] Profile sync revision без heartbeat `last_connected` — `de4e241`
- [x] VK Calls silent_token auth для AI-агента (app 7793118) — `8ce55f1`, `cc5e1d2`, `fe61a68`
- [x] VK agent: payload auth, hash heal, flood reset — `fe61a68`
- [x] VK agent мониторит всех пользователей, heal пустых/сломанных слотов — `d71c2ee`
- [x] Ротация VK agent token без рестарта (`POST /api/admin/vk/agent/sync-env`) — `bfc7d88`
- [x] Multi-device sessions, disconnect latch, dedupe — `2562487`, `2fafa5a`, `908fc9d`, `bf693f9`
- [x] S2S keepalive `/api/vpn/internal/online` — `7cf4c8e`
- [x] Client hash failure reporting — `9e98ddf`
- [x] OTA updates API + admin page + deploy script — `bb80eb2`, `55ac8ac`
- [x] Build Agent: ночная OTA-сборка PC/Android (00:00 МСК, новый bootstrap-хеш, version без bump), `build-agent/`, кнопки в админке — 2026-06-19
- [x] Registration test mode toggle — `f687065`, `809d8e8`
- [x] Trial subscription 3 дня после верификации — `d2c5b07`
- [x] Per-user hashes, device rename API — `bfc7d88`
- [x] Password reset только через web form — `e31b843`
- [x] Two-step login theme + reset-password page — `c559b5c`, `8322114`
- [x] Theme: update bar colors/labels — `76b0df7`
- [x] Theme app_name Silent VPN — `552da54`
- [x] Email в BackgroundTasks (register/forgot) — `02bf8c5`
- [x] SMTP_SSL port 465 / STARTTLS 587 — `44d7284`
- [x] Verify-email HTML page — `1daec45`, `5d81d2c`
- [x] wdtt-server systemd + master password — `94709e5`
- [x] Manual hash management (без VK API auth) — `17e6e44`
- [x] Admin dashboard CPU freq — `e3fd34d`, `320406c`, `5fc0a76`
- [x] Admin: verify/delete user — `ebb278a`
- [x] Admin: grant subscription, 3-day/unlimited plans — `90cbda1`, `01be25e`
- [x] YuMoney payments init + notify endpoint — `payments.py` на main (`/init`, `/yumoney/notify`, `/promo/check`)

### Admin UI (`origin/main`)

- [x] Страница «Улей» — соты, SSH auto-connect, CPU/RAM, вывод/удаление, upgrade-agent — 2026-06-20
- [x] ClientPreview: все экраны меню — `c5c5d61`
- [x] ThemePage: настройки по экрану предпросмотра — `01291ba`
- [x] Updates page: кнопка скачивания билдов — `3e8c082`, `39a291b`
- [x] Updates page: «Собрать релиз в update» (PC/Android) + статус build-agent — 2026-06-19
- [x] VK Calls auth через browser callback — `7dfe326`
- [x] Mobile responsive (drawer nav, grids) — `383db65`
- [x] VK hashes grouped by user — `49abeca`, `1a2c796`
- [x] Logs UI + фильтр по уровню + поиск — `94709e5`

### PC (`origin/pc`, v1.0.142)

- [x] Релиз v1.0.142 запушен — `8847047`
- [x] ConfigSync + OTA через tunnel при VPN — `032c2cf`, `8847047`
- [x] In-app password reset удалён, web-only — `b5aa9d8`
- [x] Report broken VK hashes через tunnel — `b910eeb`
- [x] Bootstrap login flow как Android (tunnel API) — `49ff5d0`…`2603cea`
- [x] Полный туннель 0.0.0.0/0, bootstrap subnet — `bf2a7ea`
- [x] Android parity routing/DNS/AllowedIPs — `bcec5f7`, `ce91b15`
- [x] Two-step login, remember me — `3327e5d`
- [x] Update bar из server theme — `a910fcb`
- [x] In-app OTA bar (check, download, NSIS install) — `edc1173`, `89267e7`
- [x] Test subscription mode в UI — `5fdbad0`

### Android (`origin/android`, v1.0.130)

- [x] VPN recovery: Wi‑Fi↔LTE, звонок, обрыв/3G — pause + force restartTransport — 2026-06-18
- [x] Bootstrap VPN на мобильном: tunnel API для входа/регистрации/forgot (регрессия `8cbace5`) — 2026-06-18
- [x] Релиз v1.0.130 запушен — `8cbace5`
- [x] Wi-Fi ConfigSync, mobile sync off — `8cbace5`
- [x] OTA через tunnel при VPN — `2e83da5`, `7726aef`, `8cbace5`
- [x] Preserve config/hashes после OTA — `2f79f52`, `a73d0f3`
- [x] In-app password reset удалён, web-only — `29e10ac`, `4990a85`
- [x] Report broken VK hashes — `87ded2e`
- [x] Bootstrap VPN для mail/browser — `4990a85`
- [x] VPN notification fix API 12+/16 — `79052eb`, `386cea3`
- [x] Session on login + public connect/disconnect — `52a3098`
- [x] Hash failure reporting — `9576c8d`
- [x] Two-step login UI — `8112e68`

### iOS (`origin/ios`)

- [x] Начальный каркас клиента — `e701e3f` (Swift + SwiftUI + NetworkExtension)
