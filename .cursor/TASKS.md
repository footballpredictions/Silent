# TASKS — Silent VPN

Формат: `[ ]` — не выполнено, `[x]` — выполнено.  
Agent приступает к **первой невыполненной** задаче.  
Статус сверен с коммитами `origin/main`, `origin/pc`, `origin/android` (2026-06-20).

---

## Открытые задачи

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
- [ ] **olcrtc 2.0** — WDTT-совместимый headless движок Телемост/WB на отдельной соте (план `.cursor/PLAN_OLCRTC2.md`, каркас `backend/olcrtc2/`). **Не деплоить на Улей рядом с wdtt.**
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
