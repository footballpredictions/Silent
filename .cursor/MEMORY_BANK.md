# MEMORY BANK — Silent VPN Project

## О проекте

**Silent VPN** — коммерческий VPN-сервис на базе WireGuard-туннелирования через VK TURN/DTLS серверы.
Технология маскирует трафик под зашифрованный медиатрафик WebRTC-звонков ВКонтакте.

**GitHub:** https://github.com/footballpredictions/Silent.git — **один remote**, **четыре ветки**.

| Локальная папка | Ветка GitHub | Версия |
|-----------------|--------------|--------|
| `Silent-Project/backend/` | `main` | — |
| `Silent-Project/pc/` | `pc` | **1.0.142** |
| `Silent-Project/android/` | `android` | **1.0.130** |
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
- VK-хеши: bootstrap (от пользователя) + до 4 серверных слотов
- AI-агент следит за хешами и восстанавливает пустые/сломанные слоты
- Режим ручных хешей в админке (автопересоздание через VK API отключено)

### VPN Flow для пользователя

**Двухшаговый вход (как Android):**

1. **Шаг 1 — Bootstrap:** пользователь вводит VK-хеш → локальный VPN (2 мин) → доступ к tunnel API `10.66.66.1`
2. **Шаг 2 — Авторизация:** register/login через tunnel → JWT-токены
3. `POST /api/vpn/device/register` (с bootstrap_hash) → WireGuard-ключи + device_id
4. Подтверждение email → trial-подписка (3 дня) + post-verification benefits
5. Нажимает тумблер → полный VPN-туннель `0.0.0.0/0`
6. Максимум **3 одновременных** VPN-подключения на аккаунт

**При включённом VPN:** все API-запросы (ConfigSync, OTA, disconnect) идут через tunnel `10.66.66.1`, не через публичный nip.io.

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
│   ├── scripts/                ← ВСЕ deploy-скрипты backend (см. раздел «Деплой»)
│   ├── DEPLOY.md
│   └── docker-compose.yml
├── pc/                         ← git, ветка pc
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
| «релиз» | `cd android\app; .\gradlew.bat assembleRelease` |
| «новая задача — …» | добавить в `TASKS.md` |

## Деплой

### Шпаргалки по репозиториям (Agent: открывать первым делом)

| Репозиторий | Ветка | Файл шпаргалки | Папка deploy-скриптов |
|-------------|-------|----------------|----------------------|
| `backend/` | `main` | **`backend/DEPLOY.md`** | `backend/scripts/` (11 файлов) |
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
# Android release (триггер «релиз»)
cd android\app; .\gradlew.bat assembleRelease

# PC dev
cd pc; npm install; npm run dev
```

### Чего НЕ делать

| Устаревшее (Silent/) | Замена |
|---------------------|--------|
| `deploy_full_api.py` в корне | `backend/scripts/deploy_api.py` |
| `deploy_update.py` | `pc/scripts/deploy_release.py` или `android/scripts/deploy_release.py` |
| `deploy_all.py`, `check_*.py`, `fix_*.py` | `deploy_stable.py` / `deploy_helper.py check` |
| `pull_backend_files.py` | `git pull` на VPS или правки локально + deploy |

## Последние изменения

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
