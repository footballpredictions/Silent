# MEMORY BANK — Silent VPN Project

## О проекте

**Silent VPN** — коммерческий VPN-сервис на базе WireGuard-туннелирования через VK TURN/DTLS серверы.
Технология маскирует трафик под зашифрованный медиатрафик WebRTC-звонков ВКонтакте.

**GitHub:** https://github.com/footballpredictions/Silent.git — **один remote**, **четыре ветки**.

| Локальная папка | Ветка GitHub | Версия |
|-----------------|--------------|--------|
| `Silent-Project/backend/` | `main` | — |
| `Silent-Project/pc/` | `pc` | **1.0.154** |
| `Silent-Project/android/` | `android` | **1.0.154** |
| `Silent-Project/ios/` | `ios` | начальная |

**Рабочая папка в Cursor:** `C:\Users\silent27\AndroidStudioProjects\Silent-Project`  
Папка `Silent-Project/` **не является** git-репозиторием — это контейнер. Внутри каждая подпапка — **свой git** (worktree / clone) и **свой `.gitignore`**.

> Устаревшая папка `AndroidStudioProjects\Silent` (корневые `deploy_*.py`, `check_*.py`) — **не использовать**. Деплой только через `scripts/` внутри каждой ветки.

## Production-сервер

| Параметр | Значение |
|----------|----------|
| VPS IP | `132.243.234.162` |
| HTTPS API | `https://132-243-234-162.nip.io` |
| WDTT (UDP) | `132.243.234.162:56000` |
| WireGuard (UDP) | `:56001` |
| Tunnel API (через WG) | `http://10.66.66.1:8000` |
| Путь на сервере | `/opt/silent-vpn/backend` (клон ветки `main`) |
| Docker stack | `api`, `db` (PostgreSQL 16), `redis`, `nginx` |
| wdtt-server | **systemd** (`wdtt.service`), не Docker |
| TLS | Let's Encrypt для nip.io + self-signed fallback |
| Credentials | `/opt/silent-vpn/backend/.env`, `/root/silent_credentials.txt` |

## Архитектура

### Стек технологий

| Компонент | Технология |
|-----------|-----------|
| Backend API | Python 3.11 + FastAPI |
| База данных | PostgreSQL 16 + Redis 7 |
| Миграции | Alembic |
| AI-агент VK | Python asyncio (`ai/vk_manager.py`) |
| Admin UI | React 18 + TypeScript + Vite + Tailwind |
| PC-клиент | Electron 32 + React + Vite + Go wdtt-client |
| Android | Kotlin + Jetpack Compose + WireGuard GoBackend |
| iOS | Swift + SwiftUI + NetworkExtension |
| VPN Core | wdtt-server (WireGuard over VK TURN/DTLS) |
| Деплой | Docker Compose + Python SSH-скрипты с Windows |
| Почта | SMTP (smtplib) с HTML-шаблонами |
| Платежи | YuMoney (2 кошелька, случайный выбор) |

### Принцип работы VPN

```
Клиент → WireGuard → Go WDTT-клиент → VK TURN/DTLS → wdtt-server на VPS → Интернет
```

- Трафик маскируется под WebRTC audio (RTP / ChaCha20-Poly1305 AEAD)
- VK-хеши: bootstrap (зашит в сборку клиента) + до 4 серверных слотов
- AI-агент следит за хешами и восстанавливает пустые/сломанные слоты
- Режим ручных хешей в админке (автопересоздание через VK API отключено)

### VPN Flow для пользователя

**Вход (Android + PC):**

1. Старт приложения → сразу экран **вход / регистрация** + автоматический bootstrap VPN (2 мин).
2. VK bootstrap-хеш **зашит в сборку** — пользователь не вводит.
3. register/login через tunnel → JWT-тokens
4. `POST /api/vpn/device/register` (с bootstrap_hash) → WireGuard-ключи + device_id
5. Подтверждение email → trial-подписка (3 дня)
6. Тумблер → полный VPN `0.0.0.0/0`
7. Максимум **3 одновременных** VPN-подключения на аккаунт

**После истечения 2 мин bootstrap:** «Закройте приложение и запустите снова».

**При включённом VPN:** все API-запросы (ConfigSync, OTA, disconnect) идут через tunnel `10.66.66.1`, не через публичный nip.io.

### Bootstrap VK-хеш (сборка Android + PC) — Agent ОБЯЗАН помнить

**Текущий хеш (debug и release по умолчанию):**

- Ссылка: https://vk.com/call/join/6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY
- Значение: `6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY`

| Тип сборки | Правило для Agent |
|------------|-------------------|
| **Debug / dev** | **Всегда** этот хеш — зашит в `android/app/build.gradle.kts` и `pc/vite.config.ts`. Собирать debug **без вопросов**. |
| **Release** | **Перед каждой новой release-сборкой** (Android `assembleRelease`, PC `npm run build`) **спросить у пользователя** актуальную ссылку `vk.com/call/join/…`. Если дали новую — подставить в сборку. Если «оставь как есть» — использовать текущий хеш выше. **Не начинать release-сборку молча.** |

**Команды release с хешем:**

```powershell
# Android
cd android\app
.\gradlew.bat assembleRelease -PbootstrapVkHash=6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY

# PC (PowerShell)
cd pc
$env:BOOTSTRAP_VK_HASH="6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY"
npm run build
```

Файлы в коде: `android/app/build.gradle.kts` (`debugBootstrapVkHash`, `-PbootstrapVkHash`), `pc/vite.config.ts` (`DEBUG_BOOTSTRAP_HASH`, env `BOOTSTRAP_VK_HASH`).

Если хеш перестал работать — пользователь даёт новую ссылку; обновить константу в обоих файлах + эту секцию Memory Bank.

### PC release-сборка (.exe) — Agent ОБЯЗАН помнить

Перед **каждой** PC release (`build-installer.bat` / `npm run build`):

1. **Спросить** актуальный bootstrap VK-хеш (см. выше).
2. **Убить процессы:** `Silent VPN.exe`, `wdtt-client.exe`, `makensis.exe`, `electron-builder.exe` — делает `pc/build-installer.bat` в начале; Agent при ручной сборке тоже должен завершить их.
3. **После успешной сборки** — удалить **старые** папки `pc/build-release-*`, оставить только новую (скрипт делает это в конце).

Команда:

```powershell
cd pc
$env:BOOTSTRAP_VK_HASH="<хеш>"
cmd /c build-installer.bat
```

Готовый installer: `pc/build-release-v141-XXXXX/Silent VPN Setup X.X.X.exe` + копия в `pc/releases/`.

**UI:** кнопка закрытия на главном экране PC (`quitApp`) — полный выход из приложения и трея.

### Диагностика VK Smart Captcha (`pc/debug_captcha.py`)

**Назначение:** локальный Python-скрипт, который **имитирует цепочку подключения wdtt-client к VK** без Electron/WebView — от `get_anonym_token` до `captchaNotRobot.check`. Показывает **точные JSON-ответы** на каждом шаге, чтобы понять, почему капча возвращает `BOT`, `error_limit`, `rate limit` и т.д.

**Когда использовать:**

- Отладка AUTO / Go v2 / WBV Auto на PC и Android (сравнить ответ API с тем, что шлёт Go)
- Проверка PoW, `debug_info`, behavioral-полей (`cursor`, `connectionRtt`) после правок в `wdtt-go/captcha_v2*.go`
- Диагностика «сгоревшего» `session_token` (Go v2 до WebView)

**Запуск (Windows, из папки `pc/`):**

```powershell
cd pc
pip install curl_cffi
python debug_captcha.py
```

**Настройка:** в начале файла — `VK_HASH` (bootstrap-хеш для `calls.getAnonymousToken`). Секреты `CLIENT_ID` / `CLIENT_SECRET` — те же, что в Go-клиенте.

**Важно (вывод диагностики):**

- В `captchaNotRobot.*` поле `access_token` должно быть **пустым** — anonymous token туда не передавать (`invalid token type`)
- Go v2 **до** WBV Auto сжигает `session_token` — в режиме AUTO сначала только WebView
- Ответ `status: "BOT"` — поведенческие сигналы; нужны `sensors_delay`, cursor/metrics, актуальная версия captcha-скрипта

**Файл в git:** ветка `pc`, корень репозитория (`pc/debug_captcha.py`). Не путать с deploy-скриптами — это **только dev/diag**, на прод не деплоится.

### Tunnel API

- WireGuard gateway: `10.66.66.1`
- iptables DNAT: `10.66.66.1:8000` → Docker API (`backend-api-1:8000`)
- Клиенты переключают base URL через `tunnelApi.ts` / Android-аналог
- Bootstrap VPN использует split routes (subnet), полный VPN — `0.0.0.0/0`

## Ключевые решения

### wdtt-server (systemd)

- Один экземпляр wdtt-server на VPS как systemd-сервис
- Единый `WDTT_MASTER_PASSWORD` для всех устройств
- Backend генерирует per-device пароли в БД
- Keepalive: wdtt-server → `POST /api/vpn/internal/online` (S2S, `X-Internal-Secret`)

### Устройства и сессии

- Модель: `user_id + device_fingerprint + device_type` (android / ios / pc)
- Лимит: **3 одновременных** VPN-подключения (`MAX_DEVICES_PER_USER`)
- Dedupe same-type devices, disconnect latch (`mark_client_disconnect_latch`)
- Переименование / удаление сессий через `/api/users/devices/{id}`
- Профиль `/api/users/me` — подписка, устройства, лимиты, test mode

### ConfigSync (клиенты)

- Endpoint: `GET /api/vpn/sync-state?hashes_since=&theme_since=&profile_since=`
- Polling каждые 60 с (ConfigSync channel)
- Ревизии: theme, profile, hashes — клиент подтягивает только изменившееся
- Profile revision **без** heartbeat `last_connected`

### Server-driven UI (оформление)

- **Все** цвета, шрифты и настраиваемые тексты UI задаются на сервере
- Публичный endpoint: `GET /api/vpn/theme` → `ThemeResponse`
- Админка: раздел «Оформление» → `POST/GET /api/admin/theme`
- Клиенты только рендерят данные (PC: `ClientTheme`, Android: `ThemeData`, iOS: аналог)
- **Запрещено** хардкодить hex-цвета и фиксированные UI-строки в клиентах

**Чеклист новой UI-фичи:**

1. `app/schemas/vpn.py` — поля в `ThemeResponse`
2. `admin-ui/src/pages/ThemePage.tsx` — поля в форме
3. `admin-ui/src/components/ClientPreview.tsx` — превью
4. PC (`Silent-Project/pc/`) — `src/renderer/clientTheme.ts`
5. Android (`Silent-Project/android/`) — `ThemeData`
6. iOS (`Silent-Project/ios/`) — по тому же принципу
7. Push: ветка `main` + **все** клиентские ветки; деплой backend

### Улей / Соты (Hive)

Масштабирование VPN: **Улей** (главный VPS) + **соты** (дополнительные VPS). Новые устройства по умолчанию на Улье; при перегрузке CPU/RAM (пороги в `.env`) — на соту с минимумом онлайн VPN. **Сборка build-agent в 00:00 МСК не считается перегрузкой.**

| Компонент | Путь / порт |
|-----------|-------------|
| Модель | `app/models/hive_cell.py`, `device.cell_id` |
| Сервисы | `hive_service.py`, `hive_load.py`, `hive_provision_service.py`, `proc_stats.py` |
| Admin API | `/api/admin/hive/*` |
| Admin UI | `admin-ui/src/pages/HivePage.tsx`, маршрут `/hive` |
| cell-agent на соте | systemd `silent-cell-agent`, порт **9100**, `cell-agent/main.py` |
| Деплой | `python scripts/deploy_hive.py` (после `npm run build` в admin-ui) |

**Подключение соты:** IP + SSH root → фоновый provisoning (wdtt, iptables DNAT `10.66.66.1:8000` → Улей, cell-agent). SSH-пароль **не хранится**.

**Метрики:** Улей — `proc_stats` (хост VPS через docker.sock или `/host/proc`); соты — `GET cell-agent /v1/status`. UI обновляет каждые 10 с.

**Вывод (draining):** сота не принимает новых клиентов; текущие VPN дорабатывают до отключения → затем удаление.

**Env:** `HIVE_CPU_PERCENT_THRESHOLD`, `HIVE_MEM_PERCENT_THRESHOLD`, `HIVE_CELL_AGENT_PORT`, `HIVE_PROVISION_SSH_USER`, `WDTT_MASTER_PASSWORD`, `VPN_SERVER_IP`.

**Деплой Hive:** только `docker cp` + `docker compose restart api nginx` — см. раздел **«Docker: код в контейнере»** ниже.

### Docker: код в контейнере (Agent ОБЯЗАН помнить)

Образ `backend-api` на VPS **устаревает**. Актуальный Python попадает в контейнер через **`docker cp`** (скрипты `deploy_*.py`), а не через пересборку image при каждом деплое.

| Действие | Можно? | Почему |
|----------|--------|--------|
| `python scripts/deploy_stable.py` / `deploy_hive.py` / … | ✅ | `docker cp` всех `.py` + `restart api` |
| `docker compose restart api` | ✅ | Перезапуск без смены файлов в контейнере |
| `docker compose up -d` (без recreate) | ⚠️ | Только если менялся **только** `docker-compose.yml` (порты/volumes) — **сразу после** синхронизировать код (см. ниже) |
| `docker compose up -d api --force-recreate` | ❌ | Сбрасывает контейнер к **старому image** → пропадают Улей (`/api/admin/hive/*` → 404), новый код, иногда `httpx` |
| Менять `ports:` в compose без `docker cp` | ❌ | То же: новый контейнер = старый image |

**После любого `docker compose up` / recreate / смены `ports:` на VPS:**

```powershell
cd backend
python scripts/restore_api_container.py
# или полный: python scripts/deploy_stable.py
```

`restore_api_container.py`: заливает `app/` + `ai/` с рабочей копии → `docker cp` → `pip install httpx paramiko` → `restart api` → `fix_tunnel_dnat`.

**Инцидент 2026-07-02:** `apply_security_phase1.py` сделал `--force-recreate` → админка: Улей 404, пользователи без устройств. Исправлено `restore_api_container.py`. В `apply_security_phase1.py` recreate убран.

### Безопасность VPS (production)

| Параметр | Значение на проде (2026-07-02) |
|----------|--------------------------------|
| API снаружи | Только **HTTPS :443** (nginx) |
| API :8000 | Только **127.0.0.1** (`docker-compose.yml`) |
| Tunnel | `10.66.66.1:8000` → DNAT на контейнер (клиенты через VPN) |
| UFW | 22, 80, 443/tcp; 56000, 56001/udp |
| fail2ban | sshd (5 попыток / 1 ч бан) |

Скрипты: `scripts/apply_security_phase1.py` (UFW + compose ports), `scripts/restore_api_container.py` (восстановление кода после compose).

**Не отключать SSH по паролю** без настройки ключей — иначе сломается деплой с Windows (`DEPLOY_PASS`).


- Авторизация: VK Calls `silent_token` (app `7793118`)
- Payload auth, hash heal, flood reset
- Мониторит всех пользователей, восстанавливает пустые/сломанные слоты
- Админка: VK Calls auth через browser callback
- Клиенты сообщают о сбоях: `POST /api/vpn/hashes/report-failure`

### OTA-обновления

- `GET /api/updates/check?platform=pc|android&version=`
- Файлы: `/opt/silent-vpn/backend/update/{platform}/`
- PC: NSIS installer, запуск после скачивания (VPN-процессы останавливаются)
- Android: OTA через tunnel при VPN, на Wi-Fi для ConfigSync
- Update bar — цвета и тексты из темы сервера

### Build Agent — ночная OTA-сборка (AI-агент)

**00:00 МСК** (если AI-агент VK подключён): новый bootstrap-хеш → release-сборка PC + Android **без смены версии** → замена файлов в `update/pc/` и `update/android/`.

| Компонент | Путь |
|-----------|------|
| Скрипты | `backend/build-agent/` (`sync_repo.sh`, `build_android.sh`, `build_pc.sh`) |
| Сервис | `app/services/build_agent_service.py` |
| Планировщик | `ai/release_build_scheduler.py` |
| Админка | Обновления → «Собрать релиз в update» (PC / Android) |
| API | `POST /api/admin/updates/build/{platform}`, `GET …/build-status` |

**Git:** перед сборкой клон/обновление в `build-agent/workspace/{pc,android}` — `git fetch`; `reset --hard` только если на remote есть новые коммиты.

**Секреты:** `android/keystore/` → `python scripts/pack_build_secrets.py` → `deploy_build_agent.py` на VPS. Не в git.

После успешной публикации в `update/` сервис удаляет `node_modules`, `dist`, `build-release-agent`, Gradle `build/`, `jniLibs` и прочие артефакты (`git clean -fdx` в workspace).

### Подписки и оплата

- Trial: 3 дня после верификации email
- Test mode: безлимитный доступ для новых регистраций (toggle в админке)
- YuMoney: 2 кошелька, случайный выбор; тарифы в `.env`
- Промокоды: CRUD в админке (`/api/admin/promo`)

### Сброс пароля

- Только через **веб-форму** на backend (`/api/auth/reset-password-page`)
- In-app password reset **удалён** из PC-клиента (v1.0.141+)
- Deep link: `/api/auth/app-reset?token=` → редирект на web form

## Структура файлов

```
Silent-Project/                 ← рабочая папка (НЕ git), открывать в Cursor
├── .cursor/                    ← junction → backend/.cursor
├── .env.deploy                 ← SSH-секреты (локально, НЕ в git)
├── backend/                    ← git, ветка main
│   ├── .cursor/                ← Memory Bank (единственный источник)
│   ├── app/, ai/, admin-ui/
│   ├── build-agent/            ← OTA-сборка на VPS (workspace/, secrets/)
│   ├── scripts/                ← ВСЕ deploy-скрипты backend (см. раздел «Деплой»)
│   ├── DEPLOY.md
│   └── docker-compose.yml
├── pc/                         ← git, ветка pc
│   ├── debug_captcha.py        ← диагностика VK captcha (см. «Диагностика VK Smart Captcha»)
│   ├── scripts/                deploy_release.py — OTA .exe
│   └── build-installer.bat
├── android/                    ← git, ветка android
│   ├── app/                    Android Studio: открывать android/app
│   ├── scripts/                deploy_release.py — OTA .apk
│   └── keystore/               локально, не в git
└── ios/                        ← git, ветка ios
    └── Silent/
```

### Memory Bank — одна папка, не две

| Путь | Роль |
|------|------|
| `backend/.cursor/` | **Единственный источник.** Коммитится в ветку `main`. Agent **редактирует только здесь**. |
| `Silent-Project/.cursor/` | **Junction** на `backend/.cursor/`. Чтобы Cursor в корне видел те же rules и Memory Bank. |

**Не копировать вручную** — после настройки worktrees создать junction:

```powershell
# из корня Silent-Project (один раз)
cmd /c mklink /J .cursor backend\.cursor
```

Правило для Agent: правки `MEMORY_BANK.md`, `TASKS.md`, `APIS.md` → только `backend/.cursor/` → `git push origin main`.

### Первичная настройка локально

```powershell
# Каждая подпапка — clone своей ветки
git clone -b main  https://github.com/footballpredictions/Silent.git backend
git clone -b pc    https://github.com/footballpredictions/Silent.git pc
git clone -b android https://github.com/footballpredictions/Silent.git android
git clone -b ios   https://github.com/footballpredictions/Silent.git ios
# Симлинк Memory Bank (не копия!)
cmd /c mklink /J .cursor backend\.cursor
```

## Git workflow

### Ветки и remotes

```
origin → github.com/footballpredictions/Silent.git
main     → папка Silent-Project/backend/
pc       → папка Silent-Project/pc/
android  → папка Silent-Project/android/
ios      → папка Silent-Project/ios/
```

Каждый push делается **из своей папки** в свою ветку:

```powershell
cd backend;  git push origin main
cd pc;       git push origin pc
cd android;  git push origin android
cd ios;      git push origin ios
```

### Формат коммитов

```
feat(backend): GET /api/vpn/sync-state for client ConfigSync channel
fix(pc): faster connect, less ConfigSync/OTA spam, bump 1.0.142
```

Формат: **`type(scope): краткое описание`**, где type = feat / fix / chore / perf / refactor.

### Куда коммитить

| Изменения | Папка | Ветка |
|-----------|-------|-------|
| Backend, admin-ui, AI | `backend/` | `main` |
| PC-клиент | `pc/` | `pc` |
| Android | `android/` | `android` |
| iOS | `ios/` | `ios` |
| Theme / UI (server-driven) | `backend/` + все клиенты | `main` + `pc` + `android` + `ios` |
| Memory Bank | `backend/.cursor/` (+ junction `Silent-Project/.cursor`) | `main` |

### Триггеры Agent

| Фраза пользователя | Действие |
|--------------------|----------|
| «пуш» | commit + push из нужной папки в нужную ветку |
| «релиз» | **Сначала спросить** актуальный bootstrap VK-хеш (см. «Bootstrap VK-хеш»). Затем `assembleRelease -PbootstrapVkHash=…` |
| «новая задача — …» | добавить в `TASKS.md` |

## Деплой

### Шпаргалки по репозиториям (Agent: открывать первым делом)

| Репозиторий | Ветка | Файл шпаргалки | Папка deploy-скриптов |
|-------------|-------|----------------|----------------------|
| `backend/` | `main` | **`backend/DEPLOY.md`** | `backend/scripts/` (13+ файлов) |
| `pc/` | `pc` | **`pc/DEPLOY.md`** | `pc/scripts/` (2 deploy + 1 утилита) |
| `android/` | `android` | **`android/DEPLOY.md`** | `android/scripts/` (2 файла) |
| `ios/` | `ios` | *(нет OTA-деплоя)* | — |

В каждом `DEPLOY.md` — **полный список** deploy-файлов репозитория и таблица «скрипт → какие исходники на VPS».

### Правила для Agent (обязательно)

1. **Не создавать** новые `deploy_*.py`, `check_*.py`, `fix_*.py` в корне проекта или рядом с кодом.
2. **Использовать только** канонические скрипты из таблиц ниже (`backend/scripts/`, `pc/scripts/`, `android/scripts/`).
3. Если нужен новый сценарий деплоя — **расширить существующий скрипт** или добавить файл **только** в `backend/scripts/` (и закоммитить в `main`), не в корень `Silent-Project/`.
4. Секреты SSH — **только** в `.env.deploy` (см. `backend/scripts/.env.deploy.example`). Не хардкодить пароли в скрипты.
5. Запускать скрипты **из папки своего репозитория** (`cd backend`, `cd pc`, `cd android`).
6. Перед деплоем admin-ui: `cd backend\admin-ui; npm run build`.
7. Зависимость: `pip install paramiko` (один раз на машине).

### Секреты и пути

Файл `.env.deploy` (не в git) — один из:

- `Silent-Project/.env.deploy` (рекомендуется, общий для всех веток)
- `backend/.env.deploy`
- `%USERPROFILE%\.silent-vpn-deploy.env`

Переменные: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PASS`, `DEPLOY_REMOTE`, `DEPLOY_CONTAINER`.

На VPS: `/opt/silent-vpn/backend`, контейнер `backend-api-1`, OTA: `update/pc/`, `update/android/`.

### Backend (`main` → `backend/scripts/`)

Запуск из `Silent-Project/backend/`:

```powershell
pip install paramiko
cd backend
```

| Задача | Команда | Когда использовать |
|--------|---------|-------------------|
| Диагностика VPS | `python scripts/deploy_helper.py check` | Проверить доступ, Docker, диск |
| Статус сервисов | `python scripts/deploy_helper.py status` | `docker compose ps`, логи api |
| Credentials после install | `python scripts/deploy_helper.py creds` | Показать admin-пароль с VPS |
| **Первичная установка VPS** | `python scripts/deploy_helper.py install` | Новый сервер: clone main, .env, docker |
| **Полный деплой backend** | `python scripts/deploy_stable.py` | Все `app/*.py` + `ai/*.py` + admin-ui/dist |
| Точечный API-деплой | `python scripts/deploy_api.py` | auth, vpn, users, admin, vk_auth + dist |
| VK Calls / агент | `python scripts/deploy_vk_calls.py` | VK auth, vk_manager, admin-ui |
| ConfigSync | `python scripts/deploy_config_sync.py` | `sync-state` и связанные файлы |
| OTA API на backend | `python scripts/deploy_update_backend.py` | Endpoint `/api/updates` (без .exe/.apk) |
| wdtt-server systemd | `python scripts/deploy_wdtt_systemd.py` | Установка/обновление wdtt.service |
| **Улей (Hive)** | `python scripts/deploy_hive.py` | Hive API, cell-agent, admin-ui «Улей» |
| cell-agent на соту | `python scripts/deploy_cell_agent.py <ip>` | Ручная установка agent на VPS-соту |
| **Восстановить код в контейнере** | `python scripts/restore_api_container.py` | После `compose up`/recreate или 404 на `/api/admin/hive/*` |
| **Hardening VPS (UFW, :8000 localhost)** | `python scripts/apply_security_phase1.py` | Без `--force-recreate`; после — проверить Улей в админке |

**Детали и списки файлов каждого скрипта:** `backend/DEPLOY.md` (не дублировать здесь).

**Типовой цикл после правок backend:**

```powershell
cd backend\admin-ui; npm run build; cd ..
python scripts/deploy_stable.py
```

Точечно (быстрее): `python scripts/deploy_api.py` или тематический скрипт из таблицы.

### PC OTA (`pc` → `pc/scripts/`)

См. **`pc/DEPLOY.md`**: `deploy_release.py`, `_deploy_common.py`.

### Android OTA (`android` → `android/scripts/`)

См. **`android/DEPLOY.md`**: `deploy_release.py`, `_deploy_common.py`.

### Сборка без деплоя

```powershell
# Android debug — хеш зашит, спрашивать не нужно
cd android\app; .\gradlew.bat assembleDebug

# Android release — СНАЧАЛА спросить хеш у пользователя
cd android\app; .\gradlew.bat assembleRelease -PbootstrapVkHash=6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY

# PC dev — хеш зашит
cd pc; npm install; npm run dev

# PC release — СНАЧАЛА спросить хеш; затем:
# cd pc
# $env:BOOTSTRAP_VK_HASH="…"
# cmd /c build-installer.bat
# (убивает процессы, после сборки удаляет старые build-release-*)
```

### Чего НЕ делать

| Устаревшее (Silent/) | Замена |
|---------------------|--------|
| `deploy_full_api.py` в корне | `backend/scripts/deploy_api.py` |
| `deploy_update.py` | `pc/scripts/deploy_release.py` или `android/scripts/deploy_release.py` |
| `deploy_all.py`, `check_*.py`, `fix_*.py` | `deploy_stable.py` / `deploy_helper.py check` |
| `pull_backend_files.py` | `git pull` на VPS или правки локально + deploy |

## Последние изменения

### 2026-07-12 — Telegram MTProto proxy (ускорение поверх VPN)

- VPS: `silent-tg-proxy` (mtg) на `:8443`, `python scripts/deploy_telegram_proxy.py`
- Theme: `telegram_proxy_url`, `telegram_proxy_menu_label`
- Меню «Ускорить Telegram» — **только debug** (Android/PC/iOS); в release скрыто
- Не исключение приложения: VPN обязателен; proxy — режим Telegram через наш exit
- Ссылка: `/root/silent_tg_proxy.txt` на VPS + админка «Оформление»

### 2026-07-12 — Persistent login (до явного «Выйти»)

- Android/PC: 401 / refresh fail / session missing / startNewSession fail — **не** clearTokens, экран MAIN
- Session missing → re-register device, токены не трогаем
- Backend: `REFRESH_TOKEN_EXPIRE_DAYS` **3650** (~10 лет); ротация на каждом `/auth/refresh`
- Logout только: кнопка «Выйти» или удаление **своей** сессии в меню

### 2026-07-12 — Android: Telegram Boost без двух APK

- Revoke: полный teardown FGS+libclient (нет зомби debug↔release)
- Меню при VPN ON: «Обновить канал Telegram» → `refreshTelegramPath` (новые TURN + warmup)
- Без sticky / Direct Exit

### 2026-07-11 — Android 1.0.154: Telegram parity PC + hi-res S (push)

- Version **1.0.154** → `origin/android`
- Telegram: MTU 1200, anti-stall dispatcher, buffers, `TelegramPathWarmup`
- TV/иконки: hi-res S assets (ранее debug)

### 2026-07-11 — Android: Telegram parity с PC 1.0.154

- wdtt-go: chunk=8, uploadRetry 50ms, retry **все** воркеры, SendCh 2048, socketBuf 8MB (arm32 TV без изменений)
- writeLoops 8 / returnCh 8192 (phone); MTU **1200**
- `TelegramPathWarmup` при full VPN ready (+4с/+12с)
- Debug APK: `android/app/build/outputs/apk/debug/` (version пока 1.0.153)

### 2026-07-11 — PC 1.0.154: Telegram latency + exclusions (push)

- Version **1.0.154** → `origin/pc`
- Telegram: MTU 1200, anti-stall dispatcher (retry all workers, chunk=8, SendCh 2048), warmup DC/CDN/5222
- Исключения: Start Menu icons, session plan, unit tests (`npm test`) — уже в `39dcaae`
- Installer/OTA deploy — отдельно (нужен bootstrap hash + `build-installer.bat`)

### 2026-07-11 — PC debug: Telegram preview vs player

- Поле: превью крутится, по тапу видео ок; файлы ок; скачивание видео иногда виснет; зависит от канала
- Прогрев: больше DC + порт 5222 + cdn*.telegram.org; повтор через 4с/12с (main) и 5с (renderer)
- Anti-stall dispatcher (chunk8 / retry all workers) без изменений
- Debug: `pc/build-debug-668774/win-unpacked/Silent VPN.exe`

### 2026-07-11 — PC debug: anti-stall Telegram (пауза mid-flow)

- Симптом: старт загрузки → пауза → снова ок (видео и файлы)
- Причина: при полном SendCh retry шёл **только в один** воркер → drop → TCP RTO
- Фикс: retry сканирует **все** воркеры; chunk **8**; uploadRetry **50ms**; SendCh **2048**
- Debug: `pc/build-debug-672144/win-unpacked/Silent VPN.exe`

### 2026-07-11 — PC debug: Telegram TTFB (старт видео)

- Поле: MTU1200/chunk4 лучше, но «крутится» перед первым кадром; дальше прелоад быстрее
- След. эксперимент: **chunk=2**, uploadRetry 15ms; **warmup TCP** к DC Telegram + HTTPS после VPN ready
- Debug: `pc/build-debug-691277/win-unpacked/Silent VPN.exe`

### 2026-07-11 — PC debug: Telegram latency (MTU/chunk/buf)

- Без exclusions/локации (Telegram заблокирован без VPN)
- Эксперимент: **MTU 1200**, **chunk=4**, **socketBuf 8MB**, writers=8
- Лог: `[ДИСП] profile: chunk=4…` / `[WG] MTU = 1200`
- Debug: `pc/build-debug-533280/win-unpacked/Silent VPN.exe` (не пушили)

### 2026-07-11 — PC: исключения — тесты + план сессии VPN + push

- Юнит/автотесты `npm test` (10): policy, state, session plan, Start Menu+icons, wiring в main
- Renderer → IPC `save-app-exclusions` → `%userData%/app-exclusions.json`; full VPN грузит план в сессию
- WireGuard Windows без process-split (нужен WFP) — план exe фиксируется и проверяется тестами

### 2026-07-11 — PC: иконки исключений через ExtractAssociatedIcon

- Electron `getFileIcon(.lnk)` давал «белый лист» — заменено на PowerShell `System.Drawing.Icon.ExtractAssociatedIcon` → PNG base64
- Приоритет: IconLocation → TargetPath → .lnk; shell32/imageres пропускаются
- Debug: `pc/build-debug-802012/win-unpacked/Silent VPN.exe`

### 2026-07-11 — PC: исключения — ярлыки Пуск, сброс галочек

- Список из Start Menu `.lnk` (иконка как на ярлыке), не ARP/uninstall
- Сброс старых отметок (БС / все галочки); убран «Показать системные»
- Debug: `pc/build-debug-602759/win-unpacked/Silent VPN.exe`

### 2026-07-11 — PC: исключения приложений (список + UI как Android)

- Список программ: PowerShell через temp `.ps1` + UTF-8 JSON (не `-Command`) — список больше не пустой
- Иконки: `app.getFileIcon` для `.exe`/`.dll` (раньше `createFromPath` часто пустой)
- UI как Android: без ЧС/БС, текст «Отмеченные приложения идут мимо VPN-туннеля»; миграция старого whitelist
- Debug: `pc/build-debug-603167/win-unpacked/Silent VPN.exe`

### 2026-07-10 — Landing: блок Telegram

- Карточка «Наш канал в Telegram» + иконка → https://t.me/silentvpn3
- Ссылка в футере; стиль как у download-карточек (монохром)

### 2026-07-10 — Android: S на TV без пикселей

- Перегенерированы `ic_brand_s` / `ic_stat_silent` / `ic_tile_silent` (до 384–512px + nodpi 512)
- `BrandMarkIcons` рендерит ≥512px; notification/tile берут hi-res drawable
- `SilentLogo` / `BrandHeader` на TV крупнее (88dp / 36sp)

### 2026-07-10 — PC: OTA «100% / файл повреждён» (баг 1.0.152)

- Причина: `resolveUpdateDownloadUrl` резал GitHub URL до pathname и клеил на `10.66.66.1` → 404 HTML вместо .exe
- Фикс: при VPN → `/api/updates/download/pc`; без VPN → прямой GitHub; проверка MZ + размер перед install

### 2026-07-10 — PC + Android: bump 1.0.153 — call-unavailable без капчи

- Upstream `d95b65b`: `CallUnavailableError` (951/954/9xxx) — без legacy/капчи
- VK Calls: ретраи только сеть/decode; captcha-gate на free-path тоже без legacy
- Version **1.0.153** (PC + Android versionCode 153)

### 2026-07-10 — Android: 3 попытки VK Calls до legacy/капчи

- Как на PC: `fetchVkCreds` при `vkcalls` — 3 ретрая с паузой, потом legacy
- Пересобран `libclient.so` + debug APK

### 2026-07-10 — PC: снова мгновенный тумблер + VK Calls без ранней капчи

- Тумблер ON сразу (не ждать `fetchProfile` / prepare) — убирает ~5–8с «Подключение…»
- Go: при `vkcalls` 3 попытки VK Calls до legacy (раньше 1 сбой → сразу медленная капча)
- OTA при VPN через tunnel
- Push `origin/pc` `8467551`

### 2026-07-10 — PC: OTA не приходило при включённом VPN

- Причина: UI пропускал check при `connected`; main ходил на public IP (hairpin через full tunnel)
- Фикс: check/download через `10.66.66.1:8000` при VPN; проверка сразу после connect + по таймеру

### 2026-07-10 — Android: иконки status bar / QS tile (S)

- S рисуется **тем же системным Bold**, что SilentLogo (`BrandMarkIcons`), не чужим vector-path
- Плитка: крупный glyph (`tileIcon`, scale 0.92); уведомления — 0.70
- Push `origin/android` `4a7b841`

### 2026-07-10 — PC: bump 1.0.152 (без фикса Telegram)

- Version **1.0.152**; Telegram media @63 — без фикса (нужен light path / wdtt-server src)
- В коммите: мгновенный тумблер (змейка слева → потом ON), убран Google Fonts (белый экран), ready-to-show
- Push `origin/pc`

### 2026-07-10 — PC: змейка 1.5 круга + фикс белого экрана

- VpnToggle: при мгновенном ON змейка крутит **~1.5 оборота** (3300 мс), бегунок уже справа
- Белый экран 20–60с: убран `<link>` на **fonts.googleapis.com** (блокировка без VPN); `show:false` + `ready-to-show`
- DNS пункт меню — сразу после «Исключения» (как Android)

### 2026-07-10 — PC: default workers 63 + debug DNS menu

- Дефолт воркеров **63** (как Android); убран debug-force 108; one-shot migration rev=2 → `eaa8480`
- Меню **DNS** только debug (пресеты как Android); `dns_override` в WG; release без меню → `062fa63`
- Debug build: `build-debug.bat`

### 2026-07-10 — Android: bump 1.0.152 + откат reorder

- Download reorder buffer: разницы нет / хуже → **откат** (не коммитился)
- Sticky earlier тоже откат; Telegram@63 без фикса в диспетчере
- Version **1.0.152** (versionCode 152) → push `origin/android`

### 2026-07-10 — Android: download reorder — ОТКАТ (хуже / без разницы)

- Пробовали reorder по WG counter на download; поле: без улучшения, местами хуже
- Откат до chunk RR; файл `reorder.go` удалён, не пушился

### 2026-07-10 — Android: sticky-until-busy — ОТКАТ (регрессия)

- Поле: на **9** воркерах Telegram ок (~1с), на **63** — тупит; резать n нельзя
- Пробовали sticky-until-busy (`len(SendCh)<64` → spill least-loaded): speedtest @63 → **2–3 МБ/с** down/up — как chunk=256, липнет к узкому TURN
- **Откат** к chunk RR `chunkSize=16`; libclient + debug APK пересобраны
- Telegram vs 63: другой путь (не sticky dispatcher)

### 2026-07-10 — Telegram media slow vs other VPN (анализ)

- Silent: speedtest выше, Telegram видео тупит; другой VPN 15–20 Мбит — Telegram моментально
- DNS перебор не помог → не резолв
- Вероятная причина: путь **WG→VK TURN→VPS** (RTT/reorder/пиринг до Telegram DC), не «мало Мбит»
- YouTube ок: многопоточный CDN; Telegram media — чувствителен к latency/MTProto к DC
- След. проверка: исключить `org.telegram.messenger` из VPN — если летает, корень в туннеле Silent

### 2026-07-10 — Android: переключатель DNS (тест Telegram)

- Меню → **DNS** (**только debug**): Яндекс, Cloudflare, Google, Quad9, OpenDNS, AdGuard, CleanBrowsing, Comodo, Verisign, Level3, UncensoredDNS, Alternate
- Release: без меню/override, DNS только с сервера (`wg_dns` Яндекс)
- В логе debug: `DNS: …`; commit `a6fdfa1` на `origin/android`
- Debug APK: `app/build/outputs/apk/debug/SilentVPN-debug.apk`

### 2026-07-10 — Android LTE field notes (две комнаты, 63 воркера OK)

- Воркеры после отката LTE-тюнинга снова стабильно до 63
- Комната A: full bars 4G, down ≤35, up 2–3 — плохой сектор/вышка, не «палки»
- Комната B: down 40–99; корреляция: down≈40–45 → up≈то же; down 65–80 → up 40–50; down 85–99 → up 5–10
- Гипотеза юзера: стык двух вышек/бендов — правдоподобно
- Инверсия high-down→low-up: типично LTE (узкий uplink + ACK/scheduling при жирном downlink), не баг набора воркеров

### 2026-07-10 — Android: откат LTE upload-cap/keepalive (регрессия)

- После cap=36 + keepalive 30s: воркеры нестабильны (63→61, 50→43), download 50–60 (было 60–100), upload пик→просадка
- Причина: keepalive 30s → TURN allocation timeout; upload-cap режет агрегат
- **Откат** всего LTE-тюнинга к `811990b` + дефолт воркеров **63**; пересобран libclient/debug APK
- Дальше: сначала стабильность набора воркеров, не эксперименты с uplink

### 2026-07-10 — Android LTE: upload-cap 36 + keepalive 30s

- **Откачено** (см. выше) — ухудшило скорость и стабильность воркеров

- После cap=54 асимметрия осталась (download ≫ upload на LTE; Wi‑Fi ровный)
- Усиление: **upload-cap 36**, chunk upload **32**, **keepalive 30s** на cellular
- Download по-прежнему со всех n (63); в логе: `LTE: n=… upload-cap=36 keepalive=30s`
- Debug APK пересобран

### 2026-07-10 — Android LTE: upload-cap 54 при n>54

- Наблюдение: Wi‑Fi up/down растут вместе; LTE до ~36–54 ровно, дальше download↑ upload↓
- Причина: upload RR по всем TURN делит узкий uplink; download агрегируется со всех сессий
- Первая попытка cap=54 — мало эффекта → см. усиление выше
- Пересобран `libclient.so` (все ABI)

### 2026-07-10 — Android TV: синий focus ring у переключателя темы

- `ThemeModeToggle` использовал обычный `clickable` → на Smart TV фокус был, обводки нет
- Подключён `tvClickable` + hit-area 44dp на TV (как `TvIconButton`)
- Commit: `811990b` на `origin/android`

### 2026-07-10 — Android: дефолт воркеров 63

- `HashChannelHelper.DEFAULT_TOTAL_WORKERS = 63` (7×9)
- Release + first-install: `Repository.getTotalWorkers` / `SilentVpnService.repoResolveTotalWorkers` → 63 (было 36)
- При 2 хешах normalize клампит до max 54
- Commit: `b30896e` на `origin/android`

### 2026-07-09 — PC throughput: волны по хешам вместо каскада (debug)

- MTU 1380 / chunk=8 **не дали** прироста → откат MTU **1280**, chunk **16**
- Каскад 1→2→… держит single-flow на 1 хеше; boot был `-n 9`
- **Boot волны:** параллельно `hashCount` групп (при 4 хешах → `-n 36`), GetCreds throttle **per-hash** (не глобальный mutex)
- Диспетчер: stride `seq*11 % nw` между chunk'ами (разнообразие TURN)
- Рамп 36→108 как раньше (3s/2s)
- Commit: `f69f04f` на `origin/pc`; debug: `pc/build-debug-245536`

### 2026-07-09 — PC throughput →100: MTU 1380 + chunk=8 (debug)

- Connect OK (~5с, syncconf, 108); потолок ~75–78 — single-flow + MTU 1280
- Эксперимент: MTU **1380** (перезапись в conf), chunk **8** (чаще ротация TURN)
- **Итог: без прироста** — откат (см. выше)
- Debug: `pc/build-debug-698205`

### 2026-07-09 — PC: откат «ускорения» → baseline + debug force 108

- После `711353`: localStorage=36 → `n=9→36`, полный install (не syncconf), 0 МБ / Network Error
- Откат polish/DNS-async и handshakeSem 24; debug снова форсит max workers (108)
- Debug: `pc/build-debug-395813` — вернуть ≤5с @108 как `26431a9`

### 2026-07-09 — PC baseline: ~75–78 Мбит @108, connect ≤5с (проверено)

**Рабочий профиль (не ломать без теста):**

| Параметр | Значение |
|----------|----------|
| AllowedIPs | `0.0.0.0/1, 128.0.0.0/1` (не голый `/0`, не CIDR-split ~32) |
| Bypass | API peer + `resolveVkExcludeIps` (host `/32`) |
| WDTT | TURN UDP + VK Calls на LAN-bind (`getLanIPv4`) |
| WG | только GETCONF `wdtt-file`; reconnect → `syncconf` (не uninstall) |
| Boot | `-n 9 -target-n 108` ramp 3s/2s |
| UI ready | WG + ≥1 worker |
| Запрещено | `api-early` full до GETCONF (мёртвый `10.66.66.1`, syncconf не меняет PrivateKey) |

- Замер: Wi‑Fi, n=108, ~75–78 Мбит/с, «Подключено» ≤5 с, трафик сотни МБ
- Commit: ветка `pc` (см. git log)

### 2026-07-09 — PC: откат api-early (мёртвый VPN)

- 5–6с «Подключено» но ETIMEDOUT 10.66.66.1 / 0.15 МБ: api-early ключи ≠ GETCONF; syncconf на Windows не меняет PrivateKey
- Main: только `wdtt-file` (GETCONF); UI ready = WG + ≥1 worker; poll 150мс + watch
- Boot 9→108, syncconf на reconnect, /1+/1 + LAN-bind — без early
- Debug: после сборки — **не коммитили**

### 2026-07-09 — PC: connect ~3с (баг api-early ждал GETCONF)

- 11с: `waitForWdttProxy(confPath)` для api-early ждал файл GETCONF ~30с
- Early: только UDP :9000 (bind-probe); conf пишем сразу; UI ready = WG up
- Boot 9→108; лог `UDP listen OK` сразу после bind
- Debug: `pc/build-debug-93593` — **не коммитили**

### 2026-07-09 — PC: early full + LAN VKCalls + syncconf keep

- ~78 Мбит @108 OK; старт ~10с — ещё uninstall перед connect
- Не forceStop WG перед connect; syncconf если служба жива
- `api-early` full снова: VK Calls + TURN на LAN-bind (без EACCES)
- Boot 18→108; unbuffered Go logs; GETCONF → syncconf без uninstall
- Debug: после сборки — **не коммитили**

### 2026-07-09 — PC: WG сразу по файлу conf (не ждать stdout)

- Conf на диске ~20:20:23, WG только ~20:21:05 — stdout Go буферизовался; poll 400мс + forceStop
- `fs.watch` + poll 200мс; `Stdout.Sync` после GETCONF; syncconf если служба жива (без uninstall)
- Debug: после сборки — **не коммитили**

### 2026-07-09 — PC: один WG full + boot 36→108 ramp

- Долгий старт: 2× install (subnet+full) + 12× VK Auth (~37с до Success)
- Main: один full после GETCONF (без api-subnet-early / upgrade)
- `-n 36 -target-n 108 -ramp-first 5s -ramp-next 3s` — ready после ~4 групп, 108 в фоне
- Скорость ~70 сохраняем (/1+/1 + LAN-bind)
- Debug: после сборки — **не коммитили**

### 2026-07-09 — PC: откат api-early full → subnet-early + full@9

- `api-early` full до VK Auth → EACCES login.vk.ru, 0 Мбит, HashFail
- Main: `api-subnet-early` (только 10.66.66.0/24) → full `/1+/1` после ≥9 воркеров
- handshakeSem 16; VK throttle 1–1.8с; cascade 200мс
- Debug: после сборки — **не коммитили**

### 2026-07-09 — PC: connect ~5с + throughput tweak (debug)

- 73–74 Мбит @108 OK (близко к Android ~85); старт 13–14с — WG ждал GETCONF
- Main: WG сразу из API (`api-early`), DNS bypass в фоне + warm при старте
- UAC install sleep 2с→400мс; handshakeSem 32; writers 8 / uploadRetry 30мс
- Debug: после сборки — **не коммитили**

### 2026-07-09 — PC: скорость ~50 Мбит OK; быстрый connect + слайдер

- Routing `/1+/1` + LAN-bind TURN: ~50 Мбит при n=36 (подтверждено)
- Долгое вкл: убран subnet→full reinstall — main VPN сразу full
- Слайдер «сила каналов»: снова читает/пишет localStorage (не форс 36)
- DNS VK exclude — параллельный resolve
- Debug: после сборки `pc/build-debug-*/win-unpacked` — **не коммитили**

### 2026-07-09 — PC throughput: /1+/1 + LAN-bind TURN (debug)

- Причина 1–2 Мбит: CIDR-split ~32 маршрутов; голый `0.0.0.0/0` — WFP kill-switch (EACCES VK)
- Full: `AllowedIPs = 0.0.0.0/1, 128.0.0.0/1` (без kill-switch) + bypass API/VK
- WDTT: TURN UDP `dialTurnUDP` с LocalAddr = Wi‑Fi (как excludeApplications на Android)
- `handshakeSem` 8→24; workers debug=36; `resolveVkExcludeIps` + `api.vk.me`
- Debug: `pc/build-debug-914676/win-unpacked/Silent VPN.exe` — **не коммитили**

### 2026-07-09 — Throughput: Android OK (108→85), PC — split AllowedIPs

- Android Wi‑Fi: 36→50–55, 108→80–85 Мбит — n работает; LTE 20–25 — лимит сети/TURN
- Push `d1255a6` скорость не ломал (только reuseRuntime + комментарии)
- PC на том же Wi‑Fi: в логе был split `0.0.0.0/1, 128…` вместо `0.0.0.0/0` — типичный Windows bottleneck
- Фикс PC: full = `0.0.0.0/0` + bypass /32 на API (без CIDR-split); debug default workers = max
- **Не коммитили** — тест debug

### 2026-07-09 — Throughput: откат chunk=256 (ухудшило)

- chunk=256 + большие буферы: PC 2–5 Мбит, Android Wi‑Fi/LTE 5–6 (было ~50 на 36)
- Откат к рабочему: `chunkSize=16`, PC returnCh=16k/writers=6, Android returnCh=4k/writers=4
- Вывод: узкое место не chunk; n=108 не помогает single-flow; PC отдельно хуже Android
- Следующее: смотреть Windows WG path / какой TURN реально несёт поток / серверный wdtt
- **Не коммитили** — debug тест

### 2026-07-09 — PC: subnet→full connect (проверено ~5с ready)

- Откат эксперимента full+defer (ломал DNS/`api.vk.me`)
- Рабочий путь: subnet `10.66.66.0/24` → full после ≥27 воркеров (reinstall)
- `reuseRuntime: true` на первом install; UI ready после WG+воркеров
- Push: `origin/pc`

### 2026-07-09 — PC debug: откат full+defer → subnet→full reinstall

- Эксперимент «full AllowedIPs + снятие/metric defaults» ломал DNS (`api.vk.me` timeout) и набор воркеров
- Вернули рабочий путь: subnet `10.66.66.0/24` → после ≥27 воркеров full через **reinstall** службы
- UI «Подключено» по-прежнему после WG + 1 воркер
- **Не коммитили** — debug для теста

### 2026-07-09 — Bump 1.0.151 (PC + Android), пасхалка убрана

- Пасхалка (собака на VPN-тумблере) удалена локально, в remote не попадала
- Android: `44ec6cd` → `origin/android` (`versionCode`/`versionName` 1.0.151)
- PC: bump `package.json` → 1.0.151 → `origin/pc`

### 2026-07-09 — Nightly Android OTA: публиковался unsigned APK

- Причина: `build_android.sh` брал `find … | head -1` → `SilentVPN-release-unsigned.apk` раньше подписанного (ASCII `-` < `.`)
- Лог 00:00 МСК 2026-07-09: `OK … SilentVPN-release-unsigned-1.0.150.apk`; ручная кнопка 11:14 → подписанный
- Доп.: планировщик стартовал nightly дважды (дата писалась после сборки)
- Фикс: исключить `*unsigned*`, `apksigner verify`, fail без keystore; `_verify_android_apk` перед publish; nightly date до старта
- Деплой: `deploy_build_agent.py` + `deploy_update_backend.py` OK (2026-07-09)

### 2026-07-09 — Проверка: рефералы уже в main; одноразовые скрипты удалены

- Рефералы/Bonuses: уже в `3ad7624` на `origin/main` (не «забытый» unstaged)
- Удалены одноразовые: `cleanup_test_referral_users.py`, `remote_referral_db_test.py` + локальные `delete_*` GitHub tags/releases runners
- Оставлены переиспользуемые: `smoke_referral.py`, `test_referral_unit.py`
- Push cleanup: `8529952` → `origin/main`; working tree backend чистый

### 2026-07-09 — Push android + backend dark theme; deploy

- Android: `5c66ff0` → `origin/android` (dark toggle, themed inputs, gray system bars)
- Backend: `5962244` → `origin/main` (`dark_*` ThemeResponse + ThemePage/ClientPreview)
- Deploy: `python scripts/deploy_stable.py` (после `npm run build` admin-ui)

### 2026-07-09 — Android: серые полосы status/nav в dark; PC push dark theme

- Android dark: status bar + nav bar = `#2A2A32` (серые полоски), контент на `bg`; layout: strip → safeDrawing → bg
- PC push: `110aa09` → `origin/pc` (тёмная тема, поля бонусов/исключений)
- Android: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`

### 2026-07-09 — PC + Android: поля ввода / чекбоксы в dark + sync с логином

- PC: бонусы, исключения, rename — `fieldBg`/`fieldText`/`borderStrong`; чекбоксы исключений (тёмная: чёрный фон, белая галочка, белая рамка)
- Android: то же для бонусов/поиска исключений; `themeTextFieldColors`; чекбоксы ThemeCheckbox
- Android: appearance поднят в `MainActivityRoot` — логин и главная делят один режим (SilentTheme тоже)
- PC: `pc/build-debug-216239/win-unpacked/Silent VPN.exe`
- Android: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`

### 2026-07-09 — PC + Android: тёмная тема (sun/moon)

- PC: rAF-морфинг иконки (плавнее CSS); заголовок снова по центру (равные боковые слоты 76px)
- Android: серп луны через Path.Difference; nav/status bar = цвет темы (не белая полоса); drawer surface + видимая обводка/разделитель на dark
- PC: `pc/build-debug-732915/win-unpacked/Silent VPN.exe`
- Android: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`

### 2026-07-09 — PC: отключение тумблера без змейки + сразу можно включить

- При выкл: без `pendingToggle`/змейки, сразу положение «выкл», lock не держим — можно сразу включить
- Stop WG / notifyDisconnect в фоне (`waitWgStopIdle` на следующем connect)
- Push: `24af756` → `origin/pc`
- Debug: `pc/build-debug-117668/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: убрать «Не отвечает» на тумблере / логе / воркерах

- Причина: лавина IPC `wdtt-log` (DTLS×36) + sync `notify()` на каждый апдейт + `net session` на install
- Фикс: батч `wdtt-log-batch` 120мс; throttle notify логов 150мс; скрыть DTLS/READY flood; кэш `isProcessElevated` 60с; панель лога подписывается только когда открыта
- Debug: `pc/build-debug-418357/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: async WG + быстрый UI (без wireguard-go)

- Freeze: `execSync` в install/stop WG → async `wireguard.js` (из `29f6de7`)
- UI «Подключено» после WG + 1 воркер; full tunnel ≥27 воркеров через **reinstall** (не syncconf — AllowedIPs на Windows не меняется)
- Disconnect: UI сразу, stop в фоне; WRAP_AUTH_TIMEOUT скрыт в логе
- Полный переход на wireguard-go (как Android GoBackend) — отдельная большая задача, пока не делаем
- Debug: `pc/build-debug-992933/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: тумблер VPN как 6 июля (`d642b7d`)

По просьбе: откат включения главного тумблера к последнему коммиту 6 июля.
- `wireguard.js`, `VpnToggle.tsx` — точно из `d642b7d`
- `main.js`: ready после 9 воркеров, subnet→full после 27, connect/disconnect/upgrade как тогда
- `MainScreen` disconnect снова await (как 6 июля)
- Сохранены сегодняшние login/bonuses/tunnel-api (не трогали)
- Debug: `pc/build-debug-690967/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: откат «сразу full» — YouTube + реальные ConfigSync/Update

Пользователь прав: Network Error в ConfigSync/Update — не «спам», а реальные проверки; глушить нельзя.
«Мелкое разрешение» — full tunnel при ~9 воркерах (мало WDTT-полосы).
- Вернули origin: subnet → full после ≥27 воркеров (reinstall в фоне).
- ConfigSync/Update/seed снова сразу (без 20с задержки и без suppress).
- Дольше ждём фоновый disconnect перед connect (до 8с), чтобы не было лишнего forceStop.
- Debug: `pc/build-debug-828037/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: убрать ghost forceStop + тихий ConfigSync/Update

По логу 12:39–12:40: `Остановка туннеля` перед первым install (~12с) + Network Error.
- Не `forceStop` по ghost-адаптеру (`isTunnelUp`); только если `sc` Running.
- `reuseRuntime: true`; stop без PowerShell CIM; install без лишнего uninstall.
- `finalizeTunnelUp`/bypass в фоне → `vpn-ready` раньше.
- ConfigSync/Update/seed: settle 60с с клика, первый tick через 20с; не логировать transient Network Error.
- Debug: `pc/build-debug-518408/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: один WG install (full сразу) + тихий ConfigSync

- ~10с: второй install после 27 воркеров (subnet→full). Main VPN теперь сразу split AllowedIPs — один install, VPN не ломается.
- ConfigSync/Update Network Error при settle — `markVpnApiSettling` + не логировать transient.
- WRAP_AUTH_TIMEOUT в логе: не пускать скрытые `[ВОРКЕР #]` в raw-fallback.
- Debug: `pc/build-debug-444526/win-unpacked/Silent VPN.exe` (ещё не push)

### 2026-07-09 — PC: VPN «on» без интернета после syncconf

- Симптом: `syncconf OK`, трафик ~0, ConfigSync/Update Network Error.
- Причина: на Windows `wg syncconf` **не применяет** смену AllowedIPs (остаётся `10.66.66.0/24`), а DNS уже на адаптере → DNS/интернет ломаются.
- Фикс: full-tunnel снова через **reinstall** службы (`skipForceStop: false`); UI «Подключено» по-прежнему после 1 воркера (reinstall в фоне).
- **Push:** `origin/pc` `064eaf0`
- Debug: `pc/build-debug-276283/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: connect ~5–8с как origin/pc (не 14с)

Сверка с [origin/pc](https://github.com/footballpredictions/Silent/commits/pc/) (`d642b7d`):
- Лишний `forceStop` + `waitForTunnelDown(8s)` на **каждый** connect (служба уже снята после disconnect) — убран; stop только если `sc` ещё Running.
- `waitWgStopIdle` capped 2.5с (не ждать полный uninstall).
- UI «Подключено» после WG + **1** воркер (как e8c39e2), не ждать 9/26.
- Hot path: `sc query` вместо PowerShell Get-NetAdapter; gateway capture в фоне.
- Сохранены: быстрый login/logout, stable FP, syncconf strip Address, выкл без змейки.
- **Push:** `origin/pc` `29f6de7` — fix(pc): fast login/connect/disconnect, bonuses UI, stable device FP
- Debug: `pc/build-debug-500227/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: syncconf Address= + выкл без змейки

- Долгое вкл: `wg syncconf` падал на `Address=` (wg-quick ключи) → fallback uninstall/reinstall. Фикс: strip Address/DNS/MTU в `wg-turn.sync.conf`.
- Выкл: тумблер сразу OFF без змейки (`pendingToggle` только на connect).
- Debug: `pc/build-debug-155464/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: быстрый connect/disconnect (тумблер не «мертвый»)

- Долгое вкл: full-tunnel делал uninstall+reinstall WG (~10–20с). Теперь `skipForceStop` + `syncconf` AllowedIPs/DNS.
- Долгое выкл / тумблер неактивен: UI ждал `notifyDisconnect` + `forceStopWireGuard`. Теперь UI сразу; stop в фоне; mutex `waitWgStopIdle` перед новым connect.
- Debug: `pc/build-debug-853919/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: freeze при connect / лого / копировать + ECONNRESET

- Причина: sync PowerShell/`sc`/`netstat`/`wg syncconf` на hot path connect + full-tunnel upgrade блокировали Electron main → «Не отвечает» при клике лого/копировать лог.
- `ECONNRESET` на `10.66.66.1` — нормальный миг при переключении bootstrap→full tunnel (маршруты мигают).
- `WRAP_AUTH_TIMEOUT` у части воркеров — шум при наборе 30/36; если туннель ready и трафик идёт — не критично.
- Фикс: весь WG hot path async (`isTunnelUpAsync`, `trySyncConf`, `finalizeTunnelUp` await, `netstat` async); tunnel API — retry при upgrade + мягкий fallback на HTTPS.
- Debug: `pc/build-debug-429094/win-unpacked/Silent VPN.exe`

### 2026-07-09 — PC: UI не «Не отвечает» при ожидании канала

- Причина: `execSync` в install/stop WireGuard блокировал Electron main.
- Фикс: `runCmdAsync` / async `forceStopWireGuard` / `runWgInstall`; bootstrap стартует через 120ms после paint.

### 2026-07-09 — PC: лимит после выхода + quit + Войти до bootstrap

1. Stable device fingerprint (`silent_stable_device_fp`) — как Android; logout больше не плодит новый слот.
2. «Закрыть приложение» при истечении bootstrap — сразу `quitApp` / `app.exit`, без ожидания WG.
3. «Войти» / «Регистрация» disabled, пока нет «Канал готов. Осталось…».

### 2026-07-09 — PC: быстрый выход

- Было: `Выйти` ждал notifyDisconnect + vpnDisconnect + /logout → UI «мёртвый», жмут несколько раз.
- Стало: сразу clearTokens + экран логина; сеть/WG в фоне (cap 4с), кнопка с guard `logoutBusyRef`.

### 2026-07-09 — PC: быстрый вход (не ждать WG uninstall)

- Было: `disconnectBootstrapVpn` → потом prefetch через public → timeout 15s + «Остановка службы».
- Стало: prefetch/theme через tunnel **до** disconnect; `onLogin` сразу; bootstrap гасится в фоне.

### 2026-07-09 — PC/Android: logout если сессию удалили

- При sync `/users/me`: если `sessionDeviceId` нет в `devices` — принудительный выход (токены, VPN, экран логина).
- Сценарий: удалили PC-сессию с другого устройства → PC не должен висеть с пустым профилем и тумблером.

### 2026-07-09 — PC login: HTTP 400 через tunnel не терять

- Симптом: `tunnel 10.66.66.1 fail: HTTP 400 → HTTPS` — 4xx считался сбоем туннеля, тело ответа терялось.
- Фикс: main `backendHttpRequest` resolve’ит любой статус; 4xx возвращается в renderer; JSON body + Content-Length явно.

### 2026-07-09 — PC login: auth через bootstrap tunnel (как Android)

- Симптом: bootstrap ready, но `Login: timeout 15000` + `Update: Network Error` — renderer xhr на public HTTPS при bootstrap не проходит.
- Фикс: при bootstrap `setBootstrapApiRouting(true)` → axios через main IPC; main при `wgApplied` сначала `10.66.66.1`, иначе public HTTPS.

### 2026-07-09 — PC: timeout 15s на логине

- Причина: при bootstrap `enableTunnelApi()` ставил baseURL `http://10.66.66.1:8000` в renderer — Electron туда не ходит → timeout.
- Фикс: без main VPN всегда `getPublicApiBaseUrl()`; login/register/forgot только public HTTPS.

### 2026-07-09 — PC: реф-ссылка с VPN и без

- `tunnel-api-request`: убрана блокировка `API unavailable` без WG — всегда сначала public HTTPS.
- `loadReferral`: 3 пути (api → IPC public → forcePublic); JWT всегда в headers.
- Ссылка должна грузиться и при включённом, и при выключенном VPN.

### 2026-07-09 — PC: реф-ссылка «…» при VPN

- Причина: `tunnelApiClient` не передавал `Authorization` в IPC (AxiosHeaders + `Object.entries`).
- Фикс: `flattenAxiosHeaders` + fallback из `localStorage`; загрузка referral через `useEffect` + «Повторить».

### 2026-07-09 — Бонусы: только «Копировать ссылку»

- PC/Android: убрана кнопка «Копировать код» (путать с промокодом) — как в admin ClientPreview.
- Остаётся одна кнопка «Копировать ссылку» на всю ширину.

### 2026-07-09 — Тексты «Бонусы»: одно общее описание

- Поле theme `bonuses_intro_text` — единый текст про реф + промо сверху экрана.
- Подписи блоков короткие (`Скопируйте…` / `Проверить скидку…`); `bonuses_rules_text` обычно пустой (без дубля внизу).
- Автомиграция старых theme-строк в `theme_settings.normalize_theme_data` при `GET /api/vpn/theme`.
- Клиенты PC/Android + админка Оформление / preview обновлены.

### 2026-07-09 — Реферальные ссылки и раздел «Бонусы»

- **Backend (`main`):** `User.referral_code` / `referred_by_user_id` / `pending_promo_code`; таблица `referral_rewards`; `POST /auth/register` принимает `referral_or_promo` (реф **или** промо); `GET /users/me/referral`; после первой YuMoney-оплаты invitee — **+30 дней** обоим; theme-поля `menu_bonuses_*` / `bonuses_*` / `register_referral_or_promo_*`; админ preview «Бонусы».
- **PC / Android:** меню «Бонусы» (реф-ссылка + промо), поле на регистрации, deep link `silentvpn://ref?code=…`.
- **iOS:** вне scope (отдельная задача в TASKS).
- **Деплой + QA (2026-07-09):** `deploy_stable.py` OK (health/admin 200, DNAT OK). Smoke `scripts/smoke_referral.py` (theme/register/invalid code). DB-симуляция награды в контейнере `remote_referral_db_test.py` → `REFERRAL_DB_OK`. Android unit: MockWebServer register/referral/theme + deep link; PC debug: `build-debug-918485`. Push ещё не делали.

### Реферальная политика (growth, до ~1000 пользователей)

| Параметр | Значение |
|----------|----------|
| Награда | +30 дней invitee + +30 дней inviter после **первой** оплаты любой подписки invitee |
| Лимит | 1 бонус на invitee; **не более 10** наград inviter за скользящие 30 дней (`REFERRAL_MONTHLY_REWARD_LIMIT`) — при лимите invitee всё равно получает +30 |
| UX-текст | `bonuses_intro_text`: как работают реф и промо + лимит + «условия могут измениться» |
| Когда ужесточать | После ~1000 пользователей **или** если много monthly-only рефералов без повторных оплат → варианты: +15/+15, бонус только inviter, бонус только после quarterly/yearly |

Осознанно щедрый оффер ради привлечения; юнит-экономика первой оплаты (особенно monthly 199₽) убыточна — это маркетинг, не ошибка.

**Админка:** пункт меню «Бонусы» (`/bonuses`, бывш. «Промокоды») — вкладка промокодов + вкладка «Рефералы и статистика» (`GET /api/admin/bonuses/stats`). В списке пользователей бейджи «Реф» / «Промо».

### 2026-07-08 — Android instrumented-тесты на устройстве (Wi‑Fi/LTE/VPN)

- В ветке `android` добавлены и стабилизированы `androidTest`: routing/promo/config-sync/network-recovery + LTE+VPN класс `LteWithVpnInstrumentedTest`.
- Исправлен device-тест promo: cleartext для MockWebServer через `127.0.0.1` (`localhost` policy issue).
- Для тестового раннера включено сохранение данных: `testInstrumentationRunnerArguments["clearPackageData"] = "false"`.
- Добавлен запускной скрипт: `android/app/run_device_tests.bat`.
- Финальный прогон на телефоне: `OK (17 tests)`.

**Команды запуска (терминал, без Android Studio Run):**

```powershell
cd android\app
.\gradlew.bat installDebug installDebugAndroidTest

$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb devices

# Все instrumented-тесты
& $adb shell am instrument -w com.silent.vpn.debug.test/com.silent.vpn.HiltTestRunner

# Только LTE+VPN routing
& $adb shell am instrument -w -e class com.silent.vpn.data.LteWithVpnInstrumentedTest com.silent.vpn.debug.test/com.silent.vpn.HiltTestRunner
```

**Важно:** запускать через `adb shell am instrument ...`; `connectedDebugAndroidTest`/Run all в Studio может переустанавливать APK и мешать сохранённой сессии.

### 2026-06-30 — VK Smart Captcha: WBV Auto (PC + Android v1.0.146)

- **PC (`pc`, v1.0.146):** AUTO → только WBV Auto (без Go v2 первым); невидимое окно Electron `opacity=0`; trusted clicks; очередь капчи. Диагностика: `pc/debug_captcha.py`.
- **Android (`android`, v1.0.146):** `AutoCaptchaActivity` — WebView в иерархии окна (аналог PC); Go creds + captcha_v2 как на PC; одна попытка auto, manual — отдельным запросом от Go.

### 2026-06-18 — Build Agent: ночная OTA-сборка + кнопки в админке

- **00:00 МСК:** AI-агент создаёт bootstrap VK-хеш, пересобирает PC + Android release (versionName/package.json **не меняются**), публикует в `update/`.
- **`backend/build-agent/`:** git sync, скрипты сборки, `secrets/` (keystore с локальной машины).
- **Админка → Обновления:** «Собрать релиз в update» для проверки.
- **Deploy:** `pack_build_secrets.py`, `deploy_build_agent.py`; docker-compose volumes `build-agent`, `update`, docker.sock.

### 2026-06-18 — Вход без шага 1 + bootstrap-хеш в сборке (Android + PC)

- **Android (v1.0.135):** VK bootstrap-хеш зашит в `BuildConfig` (debug — фиксированный; release — `-PbootstrapVkHash`). Старт → сразу экран входа/регистрации + автоподключение bootstrap VPN (2 мин). Убран шаг 1 (ввод хеша). После истечения 2 мин — «Закройте приложение и запустите снова».
- **PC (v1.0.143):** тот же flow — хеш в `__BOOTSTRAP_VK_HASH__` (`vite.config.ts`, env `BOOTSTRAP_VK_HASH` для release). `WindowControls` + `quitApp` — полное закрытие (окно + трей) на главном экране и на экране входа. `build-installer.bat`: kill процессов перед сборкой, удаление старых `build-release-*` после успеха.
- **Memory Bank:** секции «Bootstrap VK-хеш» и «PC release-сборка» — debug-хеш, перед release спрашивать новую ссылку у пользователя.

### 2026-06-18 — Android: QS-плитка OFF→ON + OTA runtime (v1.0.131)

- **Симптом:** после OFF→ON с плитки вылет; чистая установка OK, OTA поверх — нет.
- **Причина:** гонка disconnect/connect; FGS на DISCONNECT без startForeground; залипшие vpn_session_active / WG после OTA.
- **Исправление:** `prepareForTileReconnect`, join disconnectJob, `EXTRA_FROM_TILE`, DISCONNECT через startService; `resetRuntimeFlags` в AppStateMigration (без токенов/конфига).

### 2026-06-18 — Android: быстрый OFF→ON QS-плитки

- **Симптом:** VPN OFF → сразу ON с плитки — приложение падает/сворачивается, VPN не поднимается; повтор через время работает.
- **Причина:** CONNECT отклонялся при `WdttTunnelManager.running`, пока async DISCONNECT ещё не завершился.
- **Исправление (ветка `android`):** `disconnectEpoch` + отмена teardown при CONNECT; CONNECT не блокируется по `running` при `isRunning=false`; DISCONNECT с плитки через `startForegroundService`.

### 2026-06-18 — Android: шум цепочки капчи в логе (AUTO/v2/WBV)

- **Симптом:** `rate limit reached`, `ERROR_LIMIT`, `WBV timeout`, `не решил за 2 попытки` при работающем ramp-up.
- **Исправление (ветка `android`):** скрыты промежуточные шаги AUTO; остаются «решил капчу» / «Решена ✓»; таймаут 90с скрыт при живых воркерах/WG.

### 2026-06-18 — Android: шум VK Auth / DTLS EOF в логе при ramp-up

- **Симптом:** `[VK Auth] Failed … connection abort`, `[ВОРКЕР #N] Ошибка Reader: EOF` при работающем VPN.
- **Исправление (ветка `android`):** скрытие сетевых ретраев при `воркеры≥1` или WG UP; фатальные VK-ошибки и старт с 0 воркеров — по-прежнему в логе; `vk_auth_failed` на сервер не шлётся для обрывов TCP.

### 2026-06-20 — Улей (Hive): соты, балансировка, мониторинг

- Модель `HiveCell`, `device.cell_id`, admin «Улей», cell-agent на сотах (порт 9100)
- Автоподключение соты: SSH root → wdtt + DNAT tunnel + cell-agent; провижининг **в фоне**
- Балансировка: CPU/RAM Улья (пороги 85/88%), sticky assignment, build-agent ночью не перегружает
- Метрики: `proc_stats.py` — нагрузка **хоста** VPS (не Docker API); соты через cell-agent `/v1/status`
- Admin UI: автообновление метрик 10 с, «Вывод», удаление зависших сот, `POST …/upgrade-agent` (SSH)
- Деплой: `scripts/deploy_hive.py` — `docker cp` + restart (не `compose up -d api`)

### 2026-06-18 — Android: WRAP_AUTH_TIMEOUT в логе при ramp-up

- **Симптом:** VPN работает (GETCONF, трафик), но в логе `[ВОРКЕР #N] WRAP_AUTH_TIMEOUT` как красная ошибка при наборе 27/36 воркеров и капче.
- **Причина:** ретраи DTLS handshake при очереди воркеров; на PC скрыты (`libclientLogParser`), на Android попадали в `isError`.
- **Исправление (ветка `android`, `eb2597b`):** фильтр `[ВОРКЕР #]` ретраев как на PC; в wdtt-go — быстрый повтор WRAP timeout, stagger 100 мс, handshakeSem 40. **libclient.so** — пересборка `app/build_android_go.bat` (NDK).

### 2026-06-18 — Android: 0 трафик при подключении (GETCONF vs кеш WG)

- **Симптом:** воркеры набираются (36), `WireGuard UP`, трафик ≈ 0; помогало 4–5 переключений. В логе: `WireGuard из кеша (GETCONF timeout)` + `[ВОРКЕР #1] Ошибка конфига: dtls timeout`.
- **Причина:** fallback API-кеша через 10 с раньше таймаута GETCONF (15 с в libclient); после `tunnelReady` свежий GETCONF не перезаписывал WG.
- **Исправление (ветка `android`, `c47ef2a`):** приоритет `GETCONF` > `API_CACHE`; fallback кеша 22–28 с и только при ≥1 воркере; поллер `wg-turn.conf` после кеш-WG; watchdog 0 трафика → GETCONF или перезапуск; 0 воркеров при старте — перезапуск через 60 с.

### 2026-06-18 — Android: восстановление VPN при смене сети / звонке / плохой связи

- **Регрессия:** после `100d728`/`8cbace5` убран pause при обрыве; `mobileApiRouteEnabled=false`; `restartTransport` с 30с grace не срабатывал при Wi‑Fi↔LTE; fingerprint без VALIDATED не ловил 3G/2G.
- **Исправление (ветка `android`):** pause libclient при полной потере сети; `restartTransportAfterNetwork` без grace; `reapplyWireGuardForNetworkChange` + `mobileApiRoute` на mobile; recovery по VALIDATED; перезапуск TunnelApiProxy после смены сети.

### 2026-06-18 — Android: bootstrap VPN на мобильном (вход / регистрация / сброс пароля)

- **Регрессия:** в `8cbace5` (ConfigSync, mobile sync off) `Repository.setTunnelApiFromWgAddress` перестал переключать API на tunnel `http://10.66.66.1:8000` — на мобильном интернете ломались вход, регистрация, forgot-password и открытие ссылок verify/reset из браузера/почты при временном VPN (шаг 1).
- **Исправление (ветка `android`, до bump):** восстановлен tunnel API для bootstrap (`ensureBootstrapTunnelApi`, `setTunnelApiFromWgAddress`), `withBootstrapBackendApi` / `withRoutineBackendApi` на mobile при активном bootstrap, `ensureBootstrapForAuthFlow` на экране входа.
- **Фича (как было с `4990a85`):** временный VPN 2 мин — только Silent + браузеры + почта (`includeApplications`), AllowedIPs → API + HTTPS бекенда; после login — disconnect bootstrap, главный VPN на главном экране.

### 2026-06-18 — Шпаргалки DEPLOY.md по веткам

- `backend/DEPLOY.md`, `pc/DEPLOY.md`, `android/DEPLOY.md` — полные списки deploy-файлов в каждом репозитории
- MEMORY_BANK: индекс «какой репозиторий → какой DEPLOY.md»

### 2026-06-18 — Деплой-скрипты и Silent-Project

- Рабочая папка: `Silent-Project/` (не старый `Silent/` с корневыми `deploy_*.py`)
- Backend deploy: только `backend/scripts/` (8 скриптов + `_deploy_common.py`)
- PC/Android OTA: `pc/scripts/deploy_release.py`, `android/scripts/deploy_release.py`
- SSH-секреты: `.env.deploy` (шаблон `backend/scripts/.env.deploy.example`)
- Agent: **не создавать** новые deploy-файлы вне `scripts/`

### 2026-06-18 — Структура репозитория

- Откат monorepo на `main` — клиенты снова только в своих ветках
- Плоская структура внутри каждой ветки (`app/` в корне android, `src/` в корне pc)
- Локально: `Silent-Project/{backend,pc,android,ios}` — четыре git-папки, один GitHub remote
- Keystore Android убран из git (`keystore.properties` локально)

### 2026-06-16 — Backend + Admin

- `GET /api/vpn/sync-state` — ConfigSync channel для клиентов
- Profile sync revision без heartbeat `last_connected`
- VK Calls agent: payload auth, hash heal, flood reset, silent_token (app 7793118)
- ThemePage: настройки по выбранному экрану предпросмотра
- VK Calls auth через browser callback (не vkcau paste)

### 2026-06-14 — Auth

- Сброс пароля только через web form; app-reset → редирект

### 2026-06-12 — Backend + Admin

- Multi-device sessions (до 3 online), device dedupe, disconnect latch
- OTA updates page: кнопка скачивания загруженных билдов
- VK agent: мониторинг всех пользователей, heal пустых/сломанных слотов

### 2026-06-08..10 — Backend

- S2S endpoint `/api/vpn/internal/online`
- Client hash failure reporting
- Registration test mode toggle
- Two-step login theme, reset-password page

### 2026-06 — PC v1.0.130..142

- Tunnel API: OTA, ConfigSync, disconnect через `10.66.66.1` при VPN
- Android parity: routing, dispatcher, DNS, AllowedIPs, fast connect
- Удалён in-app password reset (web-only)
- Report broken VK hashes через tunnel API
- Меньше spam в ConfigSync/OTA logs

### 2026-06 — Android v1.0.121..130

- OTA через tunnel при VPN, Wi-Fi ConfigSync
- VPN notification fix (API 12+, 16)
- Bootstrap UI, NPE ViewModel fix

### Ранее (2026-05)

- Bootstrap VPN flow, per-user VK hashes
- wdtt-server systemd + master password
- Server-driven UI (theme), update bar
- OTA API + admin page
- Trial subscription, YuMoney payments
