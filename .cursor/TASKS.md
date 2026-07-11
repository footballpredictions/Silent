# TASKS — Silent VPN

Формат: `[ ]` — не выполнено, `[x]` — выполнено.  
Agent приступает к **первой невыполненной** задаче.  
Статус сверен с коммитами `origin/main`, `origin/pc`, `origin/android` (2026-06-20).

---

## Открытые задачи

### Инфраструктура и репозиторий

- [x] Улей (Hive): автоподключение соты по IP + SSH root (wdtt, DNAT tunnel, cell-agent) — 2026-06-20
- [x] Улей: фоновый провижининг, удаление зависших сот, CPU/RAM (хост + cell-agent), upgrade-agent — 2026-06-20
- [ ] Документировать YuMoney webhook flow в APIS.md (`POST /api/payments/yumoney/notify` — в коде есть, описание flow — нет)

### Продукт / монетизация

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
- [ ] Android: `assembleRelease` → `python scripts/deploy_release.py ...` (OTA 1.0.154)
- [x] PC: bump version → `1.0.154` → push `origin/pc` (Telegram latency + exclusions) — 2026-07-11
- [ ] PC: `build-installer.bat` → `python scripts/deploy_release.py ...` (OTA 1.0.154)

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
