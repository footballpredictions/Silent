# MEMORY BANK — Silent VPN Project

## О проекте

**Silent VPN** — коммерческий VPN-сервис на базе WireGuard-туннелирования через VK TURN/DTLS серверы.
Технология маскирует трафик под зашифрованный медиатрафик WebRTC-звонков ВКонтакте.

**GitHub:** https://github.com/footballpredictions/Silent.git — **один remote**, **четыре ветки**.

| Локальная папка | Ветка GitHub | Версия |
|-----------------|--------------|--------|
| `Silent-Project/backend/` | `main` | — |
| `Silent-Project/pc/` | `pc` | **1.0.147** |
| `Silent-Project/android/` | `android` | **1.0.147** |
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

**Деплой Hive:** только `docker cp` + `docker compose restart api nginx` — **не** `docker compose up -d api` (сбрасывает код в контейнере).

### AI-агент VK (Zvonki / Calls)

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
