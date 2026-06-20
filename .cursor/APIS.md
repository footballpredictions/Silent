# APIS — Silent VPN

Все endpoint'ы, внешние сервисы и переменные окружения проекта.
**Секреты не хранятся в этом файле** — только имена переменных и расположение.

---

## Production URLs

| Сервис | URL |
|--------|-----|
| HTTPS API | `https://132-243-234-162.nip.io` |
| VPS IP | `132.243.234.162` |
| WDTT (UDP) | `132.243.234.162:56000` |
| WireGuard (UDP) | `132.243.234.162:56001` |
| Tunnel API (через WG) | `http://10.66.66.1:8000` |
| wdtt-server binary | `https://github.com/amurcanov/proxy-turn-vk-android/releases/latest/download/wdtt-server-linux-amd64` |
| GitHub repo | `https://github.com/footballpredictions/Silent.git` |

---

## Backend API

**Базовый префикс:** `/api`  
**Health:** `/health`, `/api/health`  
**Авторизация пользователя:** `Authorization: Bearer <access_token>`  
**Админка:** `Authorization: Bearer <admin_token>` (от `POST /api/auth/admin/login`)  
**S2S (wdtt-server):** `X-Internal-Secret: <INTERNAL_API_SECRET>`

### Auth — `/api/auth`

| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| POST | `/register` | — | Регистрация, письмо верификации |
| GET | `/verify-email?token=` | — | HTML-подтверждение email |
| POST | `/login` | — | JWT access + refresh; опционально `device` → ensure_device_session |
| POST | `/refresh` | — | Обновление токенов |
| POST | `/forgot-password` | — | Письмо сброса пароля |
| POST | `/reset-password` | — | Смена пароля по токену |
| GET | `/app-reset?token=` | — | Редирект на web form сброса пароля |
| GET | `/reset-password-page?token=` | — | HTML-форма смены пароля |
| POST | `/admin/login` | — | JWT для админки |
| POST | `/resend-verification` | — | Повторная отправка письма верификации |

### VK Auth — `/api/auth/vk` (на сервере)

| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| POST | `/link/attach` | User | Привязка VK к аккаунту |
| POST | `/guest/link/start` | — | Гостевая привязка VK |
| GET | `/callback?code&state` | — | OAuth callback |
| GET | `/status` | User | Статус VK-привязки |

### Users — `/api/users`

| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| GET | `/me` | User | Профиль, подписка, устройства, лимиты |
| POST | `/logout` | User | Выход: end_device_session по fingerprint |
| POST | `/change-password` | User | Смена пароля (авторизован) |
| PATCH | `/devices/{device_id}` | User | Переименование устройства |
| DELETE | `/devices/{device_id}` | User | Удаление сессии устройства |

### VPN — `/api/vpn`

| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| POST | `/bootstrap-config` | — | Pre-login VPN (bootstrap hash) |
| POST | `/device/register` | User | Регистрация устройства + WG-конфиг |
| GET | `/config?fingerprint=` | User | Свежий конфиг для устройства |
| GET | `/hashes` | User | VK-хеши (bootstrap + server slots) |
| POST | `/hashes/request-refresh` | User | Запрос серверных хешов |
| POST | `/hashes/report-failure` | User | Отчёт о сбое hash/tunnel |
| POST | `/connect` | User | VPN on, лимит одновременных подключений |
| POST | `/disconnect` | User | VPN off (сессия остаётся) |
| POST | `/internal/online` | S2S | Keepalive от wdtt-server |
| POST | `/exclusions` | User | Исключения приложений (Android) |
| GET | `/exclusions/{device_id}` | User | Получить исключения |
| GET | `/theme` | — | **Публичная** тема UI (`ThemeResponse`) |
| GET | `/sync-state` | User | ConfigSync: ревизии theme/profile/hashes |

**sync-state query params:**

```
GET /api/vpn/sync-state?hashes_since=0&theme_since=0&profile_since=0
```

### Payments — `/api/payments` (на сервере)

| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| POST | `/init` | User | `{ plan_type }` → URL YuMoney |
| POST | `/promo/check` | User | Проверка промокода |
| POST | `/webhook` | Secret | YuMoney notification webhook |

### Updates — `/api/updates`

| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| GET | `/check?platform=pc\|android&version=` | — | OTA: доступность обновления |

### Admin — `/api/admin`

| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| GET | `/stats` | Admin | CPU/RAM/disk, users, VK hashes |
| GET | `/users` | Admin | Список пользователей |
| POST | `/users/{id}/grant-subscription` | Admin | Выдача подписки |
| POST | `/users/{id}/revoke-subscription` | Admin | Отзыв подписки |
| POST | `/users/{id}/ban` | Admin | Ban/unban |
| POST | `/users/{id}/verify` | Admin | Ручная верификация email |
| DELETE | `/users/{id}` | Admin | Удаление пользователя + каскад |
| GET | `/vk/status` | Admin | Статус VK-агента |
| POST | `/vk/bot-auth/start` | Admin | OAuth для AI-агента |
| POST | `/vk/bot-auth/paste` | Admin | Вставка OAuth URL |
| POST | `/vk/oauth/finish` | Admin | Android token → сервер |
| GET | `/vk/oauth/callback` | — | Code exchange fallback |
| POST | `/vk/bot-auth/password` | Admin | Password grant |
| GET | `/vk/bot-auth/status?state=` | Admin | Poll OAuth сессии |
| POST | `/vk/agent/connect` | Admin | Запуск VkManager, heal hashes |
| POST | `/vk/agent/sync-env` | Admin | Перечитать VK_AGENT_ACCESS_TOKEN |
| POST | `/vk/agent/disconnect` | Admin | Отключить AI-агент |
| GET | `/vk/hashes` | Admin | Список хешов |
| POST | `/vk/hashes/manual` | Admin | Ручное добавление хеша |
| DELETE | `/vk/hashes/{slot}` | Admin | Удаление слота |
| POST | `/vk/publish-configs` | Admin | Push конфигов в VK |
| POST | `/maintenance/cleanup-bootstrap` | Admin | Удалить bootstrap user |
| GET | `/theme` | Admin | Чтение темы |
| POST | `/theme` | Admin | Запись темы |
| POST | `/promo` | Admin | Создание промокода |
| GET | `/promo` | Admin | Список промокодов |
| GET | `/logs` | Admin | Буфер логов |

### Admin Hive — `/api/admin/hive`

| Метод | Путь | Auth | Описание |
|-------|------|------|----------|
| GET | `/cells` | Admin | Список сот + онлайн VPN, CPU/RAM |
| GET | `/summary` | Admin | Сводка: нагрузка Улья, пороги, режим балансировки |
| POST | `/cells/auto` | Admin | Подключить соту (IP + SSH root) — provisoning в фоне |
| POST | `/cells/manual` | Admin | Ручное добавление (без SSH) |
| POST | `/cells/connect` | Admin | Подключить через cell-agent URL + пароль |
| POST | `/cells/{id}/probe` | Admin | Проверка cell-agent |
| POST | `/cells/{id}/upgrade-agent` | Admin | Обновить cell-agent на соте (body: SSH password) |
| PATCH | `/cells/{id}` | Admin | Имя, priority, status (`active` / `draining` / `offline`) |
| DELETE | `/cells/{id}` | Admin | Удалить соту (`?force=true` для provisioning/error) |

**cell-agent на соте** (порт 9100, заголовок `X-Cell-Agent-Secret`):

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Health |
| POST | `/v1/handshake` | Параметры VPN для Улья |
| GET | `/v1/status` | CPU/RAM, wdtt_active |

**Env Hive:** `HIVE_CPU_PERCENT_THRESHOLD`, `HIVE_MEM_PERCENT_THRESHOLD`, `HIVE_CELL_AGENT_PORT`, `HIVE_PROVISION_SSH_USER`, `HIVE_PROVISION_STALE_MINUTES`, `HOST_PROC_ROOT` (опц. `/host/proc`).

### Статические маршруты

| Путь | Описание |
|------|----------|
| `/dashboard` | Admin UI (React SPA) |
| `/subscriptions` | Страница подписок (admin-ui) |
| `/update/pc/{filename}` | OTA PC installer |
| `/update/android/{filename}` | OTA Android APK |
| `/static/vk-agent-oauth.html` | OAuth helper page |

---

## ThemeResponse — поля server-driven UI

Endpoint: `GET /api/vpn/theme` (публичный, без auth).

| Поле | Назначение |
|------|------------|
| `background_color` | Фон |
| **text_color** | Текст |
| `toggle_on_color` / `toggle_off_color` | Тумблер VPN |
| `font_family` | Шрифт |
| `app_name` | Название приложения |
| `update_bar_background_color` | OTA bar — фон |
| `update_bar_text_color` | OTA bar — текст |
| `update_bar_progress_color` | OTA bar — progress |
| `update_bar_label_available` | «Доступно обновление» |
| `update_bar_label_downloading` | «Скачивание…» |
| `login_step1_title` | Заголовок шага 1 (bootstrap hash) |
| `login_step1_instruction` | Инструкция шага 1 |
| `login_hash_placeholder` | Placeholder хеша |
| `login_hash_button_text` | Кнопка «Подключить» |
| `login_vk_mobile_url` / `login_vk_mobile_link_text` | Ссылка VK (mobile) |
| `login_vk_pc_url` / `login_vk_pc_link_text` | Ссылка VK (PC) |
| `login_link_color` | Цвет ссылок |
| `login_step2_title` | Заголовок шага 2 (login) |
| `login_remember_me_label` | «Запомнить меня» |
| `login_forgot_password_label` | «Забыли пароль?» |
| `login_forgot_title` / `login_forgot_instruction` | Forgot password |
| `login_reset_title` / `login_reset_button_text` | Reset password |

---

## Внешние сервисы

### VK API

| Параметр | Значение |
|----------|----------|
| API base | `https://api.vk.com/method/*` v5.199 |
| OAuth redirect | `https://oauth.vk.com/blank.html` |
| Android client_id | `6287487` (PC OAuth) |
| Calls app (AI agent) | `7793118` (silent_token auth) |

**Env-переменные** (файл `/opt/silent-vpn/backend/.env`):

```
VK_ID_APP_ID
VK_ID_CLIENT_SECRET
VK_GROUP_ID
VK_COMMUNITY_TOKEN
VK_AGENT_ACCESS_TOKEN
VK_BOT_WRITE_URL
VK_LOGIN
VK_PASSWORD
```

### SMTP (email)

```
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASS
EMAIL_FROM
EMAIL_FROM_NAME
FRONTEND_URL
```

Реализация: `backend/app/services/email_service.py` (465=SSL, 587=STARTTLS).  
Шаблоны: verification, password reset, subscription activated.

### YuMoney

```
YUMONEY_WALLET_1
YUMONEY_WALLET_2
YUMONEY_SECRET
PRICE_MONTHLY=199
PRICE_QUARTERLY=499
PRICE_YEARLY=1499
```

Логика: `app/services/payment_service.py`. Два кошелька — случайный выбор.

### Прочие secrets (`.env` на VPS)

```
SECRET_KEY
JWT_SECRET
POSTGRES_PASSWORD
REDIS_PASSWORD
ADMIN_LOGIN
ADMIN_PASSWORD
VPN_SERVER_IP
VPN_SERVER_PORT
WDTT_MASTER_PASSWORD
WDTT_PORT
WDTT_WG_PORT
INTERNAL_API_SECRET
MAX_DEVICES_PER_USER=3
```

Сгенерированные пароли при install: `/root/silent_credentials.txt`

---

## GitHub

| Параметр | Значение |
|----------|----------|
| Repo | `footballpredictions/Silent` |
| Ветки | `main`, `pc`, `android`, `ios` |
| Deploy token | PAT только в `.env.deploy` / локальном git config — **не коммитить** |

---

## Deploy-скрипты (Windows → VPS)

**Каноническое расположение** — только `scripts/` внутри каждой ветки.  
**Agent: не создавать** новые `deploy_*.py` / `check_*.py` в корне проекта.

SSH-секреты: `Silent-Project/.env.deploy` или `backend/.env.deploy` (шаблон `backend/scripts/.env.deploy.example`).

| Переменная | По умолчанию |
|------------|--------------|
| `DEPLOY_HOST` | `132.243.234.162` |
| `DEPLOY_USER` | `root` |
| `DEPLOY_PASS` | *(обязательно)* |
| `DEPLOY_REMOTE` | `/opt/silent-vpn/backend` |
| `DEPLOY_CONTAINER` | `backend-api-1` |

### Backend — `backend/scripts/` (ветка `main`)

Запуск: `cd backend` → `python scripts/<скрипт>.py`

| Скрипт | Назначение |
|--------|------------|
| `deploy_helper.py check` | Диагностика VPS |
| `deploy_helper.py install` | Первичная установка VPS (clone main, docker) |
| `deploy_helper.py status` | `docker compose ps` + логи |
| `deploy_helper.py creds` | Admin credentials с сервера |
| `deploy_stable.py` | Полный деплой: все `app/` + `ai/` + admin-ui/dist |
| `deploy_api.py` | Точечно: auth, vpn, users, admin, vk_auth + dist |
| `deploy_vk_calls.py` | VK Calls auth + vk_manager + admin-ui |
| `deploy_config_sync.py` | ConfigSync / sync-state |
| `deploy_update_backend.py` | OTA API (без загрузки бинарников) |
| `deploy_wdtt_systemd.py` | wdtt-server как systemd service |

Общий модуль: `_deploy_common.py` (SSH, upload, `load_env()`).

**Полные списки файлов по каждому скрипту:** `backend/DEPLOY.md`, `pc/DEPLOY.md`, `android/DEPLOY.md`.

### PC OTA — `pc/scripts/` (ветка `pc`)

См. `pc/DEPLOY.md`.

```powershell
python scripts/deploy_release.py "<path-to-setup.exe>" <version>
```

### Android OTA — `android/scripts/` (ветка `android`)

См. `android/DEPLOY.md`.

```powershell
python scripts/deploy_release.py "<path-to.apk>" <version>
```

---

## Клиентские fallback URL (hardcoded)

PC-клиент (`pc/src/renderer/`):

| Константа | Значение |
|-----------|----------|
| `SERVER_URL` / `FALLBACK_PUBLIC` | `https://132-243-234-162.nip.io` |
| `SERVER_HOST` | `132.243.234.162` |
| `SERVER_PORT` (WDTT) | `56000` |
| `WG_TUNNEL_GATEWAY` | `10.66.66.1` |

Эти значения — fallback до загрузки конфига с сервера; не дублировать theme/UI-строки.
