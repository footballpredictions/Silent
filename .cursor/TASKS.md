# TASKS — Silent VPN

Формат: `[ ]` — не выполнено, `[x]` — выполнено.  
Agent приступает к **первой невыполненной** задаче.  
Статус сверен с коммитами `origin/main`, `origin/pc`, `origin/android` (2026-06-18).

---

## Открытые задачи

### Инфраструктура и репозиторий

- [ ] Синхронизировать локальный `backend/` checkout с `origin/main` (локально ~7 файлов, на main — полный `backend/app/`)
- [ ] Checkout веток `android` / `ios` для полной локальной разработки клиентов
- [ ] Вынести SSH-пароль и GitHub PAT из `deploy_*.py` в локальный `.env.local` (секреты всё ещё в скриптах)
- [ ] Документировать YuMoney webhook flow в APIS.md (`POST /api/payments/yumoney/notify` — в коде есть, описание flow — нет)

### iOS-клиент

- [ ] Доработать iOS до паритета с Android/PC (bootstrap, tunnel API, ConfigSync, OTA) — на `origin/ios` только `e701e3f`
- [ ] Подключить server-driven UI (`ThemeData`) на iOS

### QA / ручное тестирование

- [ ] Android: прогнать OTA + ConfigSync на мобильной сети vs Wi-Fi (код готов в `8cbace5`, ручной прогон — нет)
- [ ] PC: прогнать полный цикл bootstrap → login → connect → OTA через tunnel → disconnect

### Следующие релизы

- [ ] Android: bump version → `assembleRelease` → push `origin/android` → `deploy_update.py`
- [ ] PC: bump version → `build-installer.bat` → push `origin/pc` → `deploy_update.py`

---

## Выполнено (по коммитам)

### Memory Bank / документация

- [x] Обновить Memory Bank (MEMORY_BANK.md, APIS.md, TASKS.md) — 2026-06-18

### Backend (`origin/main`)

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

- [x] ClientPreview: все экраны меню — `c5c5d61`
- [x] ThemePage: настройки по экрану предпросмотра — `01291ba`
- [x] Updates page: кнопка скачивания билдов — `3e8c082`, `39a291b`
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
