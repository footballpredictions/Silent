# MEMORY BANK — Silent VPN Project

## О проекте

**Silent VPN** — коммерческий VPN-сервис на базе WireGuard-туннелирования через VK TURN/DTLS серверы.
Технология маскирует трафик под зашифрованный медиатрафик WebRTC-звонков ВКонтакте.

**Репозиторий:** https://github.com/footballpredictions/Silent.git

| Ветка | Содержимое | Текущая версия клиента |
|-------|------------|------------------------|
| `main` | Backend (FastAPI), AI VK-агент, Admin UI (React) | — |
| `pc` | PC-клиент (Electron 32 + React + Vite) | **1.0.142** |
| `android` | Android (Kotlin + Jetpack Compose + WireGuard GoBackend) | **1.0.130** |
| `ios` | iOS (Swift + SwiftUI + NetworkExtension) | начальная версия |

## Production-сервер

| Параметр | Значение |
|----------|----------|
| VPS IP | `132.243.234.162` |
| HTTPS API | `https://132-243-234-162.nip.io` |
| WDTT (UDP) | `132.243.234.162:56000` |
| WireGuard (UDP) | `:56001` |
| Tunnel API (через WG) | `http://10.66.66.1:8000` |
| Путь на сервере | `/opt/silent-vpn` |
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

1. `backend/app/schemas/vpn.py` — поля в `ThemeResponse`
2. `backend/admin-ui/src/pages/ThemePage.tsx` — поля в форме
3. `backend/admin-ui/src/components/ClientPreview.tsx` — превью
4. PC (`pc/`) — `clientTheme.ts`
5. Android (`android/`) — `ThemeData`
6. iOS (`ios/`) — по тому же принципу
7. Push: `main` + ветки клиентов; деплой backend

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
Silent/
├── .cursor/
│   ├── MEMORY_BANK.md      ← этот файл
│   ├── TASKS.md            ← задачи
│   ├── APIS.md             ← API и внешние сервисы
│   └── rules/              ← AGENTS, memory-bank, server-driven-ui
├── backend/                ← ветка main (локально может быть частичный checkout)
│   ├── app/
│   │   ├── api/            auth.py, vpn.py, users.py, admin.py, vk_auth.py, updates.py, payments.py
│   │   ├── models/         user, device, subscription, payment, vk_hash, ...
│   │   ├── schemas/        vpn.py (ThemeResponse), auth, user
│   │   ├── services/       vpn_service, subscription_service, email_service, theme_settings, ...
│   │   └── core/           security, deps
│   ├── ai/                 vk_manager.py
│   ├── admin-ui/           React-дашборд
│   ├── docker-compose.yml
│   ├── nginx.conf
│   ├── ssl/
│   ├── wdtt/               wdtt-server binary
│   └── update/             pc/, android/ — OTA installers
├── pc/                     ← ветка pc
│   ├── src/main/           Electron main (VPN, WireGuard, wdtt)
│   ├── src/renderer/       React UI
│   ├── wdtt-go/            Go libclient
│   └── build-installer.bat
├── android/                ← ветка android
├── ios/                    ← ветка ios
└── deploy_*.py / check_*.py  ← SSH-деплой с Windows на VPS
```

**Важно:** локальный workspace может содержать неполный checkout (`backend/` — часть файлов, android/ios — без исходников). Полный backend на VPS и в GitHub-ветках.

## Git workflow

### Ветки и remotes

```
origin → github.com/footballpredictions/Silent.git
main     → backend + AI + admin-ui
pc       → PC-клиент
android  → Android-клиент
ios      → iOS-клиент
```

### Формат коммитов

```
feat(backend): GET /api/vpn/sync-state for client ConfigSync channel
fix(pc): faster connect, less ConfigSync/OTA spam, bump 1.0.142
```

Формат: **`type(scope): краткое описание`**, где type = feat / fix / chore / perf / refactor.

### Куда коммитить

| Изменения | Ветка |
|-----------|-------|
| Backend, admin-ui, AI | `main` |
| PC-клиент | `pc` |
| Android | `android` |
| iOS | `ios` |
| Theme / UI (server-driven) | `main` + **все** клиентские ветки |

### Триггеры Agent

| Фраза пользователя | Действие |
|--------------------|----------|
| «пуш» | commit + push в нужную ветку |
| «релиз» | `.\gradlew.bat assembleRelease` (Android) |
| «новая задача — …» | добавить в `TASKS.md` |

## Деплой

### Первичная установка VPS

```powershell
python deploy_helper.py install
```

Клонирует repo, генерирует `.env`, SSL, скачивает wdtt-server, `docker compose up -d --build`.

### Типовой деплoy backend (с Windows)

```powershell
python deploy_stable.py          # sync app/ + ai/ + admin-ui dist
python deploy_full_api.py        # auth, vpn, users, admin, vk_auth
python deploy_helper.py check    # диагностика VPS
python deploy_helper.py status   # docker compose ps
python pull_backend_files.py     # скачать файлы с VPS → локальный backend/
```

### PC release

```powershell
cd pc
.\build-installer.bat
python deploy_update.py --file "pc\build-release-v141-XXXX\Silent VPN Setup 1.0.142.exe" --platform pc --version 1.0.142
```

### Admin UI build

```powershell
cd backend\admin-ui
npm install
npm run build
# docker cp dist/. backend-api-1:/app/admin-ui/dist/
```

### Go wdtt-client (пересборка)

```powershell
cd pc\wdtt-go
go build -ldflags="-s -w -checklinkname=0" -trimpath -o ..\resources\wdtt-client.exe .
```

### Android release

```powershell
cd android
.\gradlew.bat assembleRelease
```

### PC dev

```powershell
cd pc
npm install
npm run dev    # Vite :3001 + Electron
```

## Последние изменения

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
