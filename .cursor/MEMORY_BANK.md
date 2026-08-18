# MEMORY BANK — Silent VPN Project

## О проекте

**Silent VPN** — коммерческий VPN-сервис на базе WireGuard-туннелирования через VK TURN/DTLS серверы.
Технология маскирует трафик под зашифрованный медиатрафик WebRTC-звонков ВКонтакте.

**GitHub:** https://github.com/footballpredictions/Silent.git — **один remote**, **четыре ветки**.

| Локальная папка | Ветка GitHub | Версия |
|-----------------|--------------|--------|
| `Silent-Project/backend/` | `main` | — |
| `Silent-Project/pc/` | `pc` | **1.0.161** (olcrtc снят из UI; WDTT only) |
| `Silent-Project/android/` | `android` | **1.0.161** (olcrtc снят из UI; WDTT only) |
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
| Платежи | YuMoney QuickPay (кастом, без API), до 10 кошельков, случайный выбор |

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

### Инвариант: не ломать старых клиентов, не ронять сервер и VPN (жёстко)

Новые фичи (Hive, standby, GC, kick, failover, theme, API) **обязаны** быть обратно совместимы и fail-safe. Инцидент 2026-08-18: один фейл `/health` Улья переключал DNAT `10.66.66.1:8000` на localhost — VPN на сотах падал и «сам оживал».

**Запрещено без явной просьбы пользователя и без debounce/теста:**

- Рестарт `wdtt.service` на Улье или соте (уронит всех в туннеле)
- Переключать iptables/DNAT туннеля (`10.66.66.1:8000`) по **одному** таймауту health/API
- Снимать живые WG peer’ы «наугад» (GETCONF extras с свежим handshake; инцидент 2026-08-16)
- Ломать API/поля, на которые ещё ходят клиенты 1.0.160 / 1.0.161 (не удалять роуты, не менять смысл `ThemeResponse`/login/config)
- Рестарт `api`+`nginx` ради правки **только** cell-agent: старые агенты на сотах успевают увидеть «Улей мёртв» и снова дёрнуть DNAT

**Как делать новые реализации:**

- Старые клиенты продолжают работать без обновления (новые поля опциональны, дефолты как раньше)
- Failover/standby — только после нескольких подтверждённых фейлов (~45 с), health сначала на IP Улья, не на одном nip.io
- GC/kick трогает только мёртвые extras; ключи `devices` и live handshake не трогать
- Деплой cell-agent: залить `/opt/silent-vpn/backend/cell-agent/` (volume `:ro`), **не** рестартить api; соты подтянут файл автоапгрейдом, пока Улей жив
- После деплоя проверить: `wdtt` active, DNAT сот → `132.243.234.162:8000`, health API 200

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

### Варианты обхода (WDTT + olcrtc)

Два **независимых** пути (меню «Варианты обхода» в release + debug):

| | Вариант 1 | Вариант 2 |
|---|-----------|-----------|
| Стек | WireGuard → WDTT → VK TURN | TUN→SOCKS → olcrtc cnc → Jitsi/WB/Telemost → olcrtc srv |
| Админка | `/bypass` секция 1 (бывш. VK / Тоннели) | `/bypass` секция 2 |
| API | без изменений | `GET /api/vpn/olcrtc-config`, admin `/api/admin/bypass/olcrtc*` |
| Клиенты | `bypass_family=wdtt` + `vk_cred_strategy` | `bypass_family=olcrtc` + `olcrtc_provider` |
| Сервер | `wdtt.service` | `olcrtc@pc` / `olcrtc@android` (`/opt/silent-vpn/olcrtc/`), `python scripts/deploy_olcrtc.py` |
| Доки | — | `backend/docs/olcrtc.md` |

Источник olcrtc: https://github.com/openlibrecommunity/olcrtc

**Актуальный план стабильности (2026-08-14, код влит):** `.cursor/PLAN_OLCRTC_STABILITY.md`  
Occupancy **1 клиент = 1 комната** (TM+WB `max_clients=1`, прод heal). Конфиг на БС/LTE **только** через `10.66.66.1` / SOCKS. PC меню обхода — кнопка «Применить» внизу как 1.0.160. Endurance 40 мин — ручной прогон.

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
| `python scripts/deploy_stable.py` | ✅ | `docker cp` **всех** `app/**/*.py` + `ai/**/*.py` + restart. Единственный безопасный деплой backend на прод. |
| `python scripts/deploy_hive.py` / тематические | ⚠️ | Только если скрипт явно копирует все затронутые файлы, включая `models/` |
| `python scripts/deploy_api.py` | ✅ алиас | С 18.08.2026 вызывает `deploy_stable.py`. Старый FILES-список удалён. |
| `docker compose restart api` | ✅ | Перезапуск без смены файлов в контейнере |
| `docker compose up -d` (без recreate) | ⚠️ | Только если менялся **только** `docker-compose.yml` (порты/volumes) — **сразу после** синхронизировать код (см. ниже) |
| `docker compose up -d api --force-recreate` | ❌ | Сбрасывает контейнер к **старому image** → пропадают Улей (`/api/admin/hive/*` → 404), новый код, иногда `httpx` |
| Менять `ports:` в compose без `docker cp` | ❌ | То же: новый контейнер = старый image |

**Правило Agent (жёстко):** после любых правок backend на прод — `python scripts/deploy_stable.py` (нужен `admin-ui/dist`). `deploy_api.py` — алиас того же полного копирования. Не делать ручной `docker cp` выбранных файлов.

**После любого `docker compose up` / recreate / смены `ports:` на VPS:**

```powershell
cd backend
python scripts/restore_api_container.py
# или полный: python scripts/deploy_stable.py
```

`restore_api_container.py`: заливает `app/` + `ai/` с рабочей копии → `docker cp` → `pip install httpx paramiko` → `restart api` → `fix_tunnel_dnat`.

**Инцидент 2026-07-02:** `apply_security_phase1.py` сделал `--force-recreate` → админка: Улей 404, пользователи без устройств. Исправлено `restore_api_container.py`. В `apply_security_phase1.py` recreate убран.

### Безопасность VPS (production)

| Параметр | Значение на проде (2026-07-26) |
|----------|--------------------------------|
| API снаружи | Только **HTTPS :443** (nginx) |
| API :8000 | Только **127.0.0.1** (`docker-compose.yml`) |
| Tunnel | `10.66.66.1:8000` → DNAT на контейнер (клиенты через VPN) |
| UFW | 22, 80, 443/tcp; 56000, 56001/udp; 8443/tcp (MTProto); 443/udp; 9101 только `172.16.0.0/12` |
| CONNECT 8080/18443 | Только **127.0.0.1** (публичный UFW снят — был open proxy abuse) |
| host-provision :9101 | UFW docker-only + **X-Internal-Secret** (`INTERNAL_API_SECRET`) |
| olcrtc SOCKS | Локально `127.0.0.1:8808` + **per-session user/pass** (RFC1929) на PC/Android |
| fail2ban | sshd (5 попыток / 1 ч бан) |

Скрипты: `scripts/apply_security_phase1.py` (UFW + compose ports), `scripts/restore_api_container.py` (восстановление кода после compose), `scripts/deploy_olcrtc_host_provision.py`.

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
- **YuMoney QuickPay (кастом, без API YuMoney)** — реализовано 2026-07-14 по плану `.cursor/PLAN_PAYMENTS_YUMONEY.md`:
  - До **10 кошельков** через `.env` (`YUMONEY_WALLET_1..10` + `YUMONEY_SECRET_1..10`, свой секрет на кошелёк); случайный выбор на каждый `/payments/init`; расширение = только новые env-переменные
  - Атрибуция платежа — уникальный `label` (`silent_<32 hex>`, `secrets.token_hex(16)`) на каждый intent, возвращается в webhook; `SELECT … FOR UPDATE` + unique `operation_id` — двое одновременно платящих не путаются, повторные нотификации не дублируют активацию
  - Webhook-чеклист: подпись SHA1 секретом **именно того кошелька**, `codepro=false`, `unaccepted=false`, `currency=643`, сумма (`withdraw_amount`/`amount`) ≥ `YUMONEY_AMOUNT_TOLERANCE` (0.93) от ожидаемой — гасит и комиссию YuMoney, и атаки типа `sum=1`
  - Невалидная подпись → HTTP 400 (не подтверждаем); всё остальное понятое (дубликат/ignored/mismatch) → HTTP 200, чтобы YuMoney не заретраил бесконечно
  - **Единый флоу всех клиентов:** `/init` → открыть `url` (прямая ссылка `yoomoney.ru/quickpay/confirm.xml`, urlencoded) в **системном браузере** (PC: `openExternal`, Android: `ACTION_VIEW`) — не встраивается в приложение и не проксируется через бекенд; клиент poll'ит `GET /payments/status/{label}` каждые ~4с до `completed`/`failed`/`expired`, таймаут 10 мин. `successURL` = наш `GET /payments/success-page` (публичная HTML — YuMoney обязан туда вернуть браузер), но это не источник правды для клиента
  - Promo `use_count` инкрементится и `pending_promo_code` очищается **только** при успешном завершении оплаты, не на `/init` (иначе неудачные платежи жгли бы промокод)
  - Theme-поля `payment_waiting_*` / `payment_success_*` / `payment_failed_*` / `payment_timeout_*` / `payment_retry_button_text` — backend (`ThemeResponse`) + admin-ui (`ThemePage`/`ClientPreview`, экран «Подписка») + PC (`clientTheme.ts`, `MainScreen.tsx`) + Android (`ThemeData`, `MainViewModel.PaymentUiState`, `MenuSubscription`)
  - **Тесты (обязательное условие плана — выполнено):** `backend/scripts/test_payment_unit.py` — 37 unit-тестов (кошельки/подпись/весь чеклист notify включая обходы sum=1, foreign-label race, idempotency, TTL) — **37/37 OK**; плюс живой прогон на проде реальными кошельками (см. запись 2026-07-14 в «Последние изменения» ниже) — signature/commission/sum=1/idempotency подтверждены на реальных `YUMONEY_WALLET_1/2`
  - **Задеплоено на прод 2026-07-14**, оба реальных кошелька настроены и работают. **Осталось:** релизы PC/Android с новым UI оплаты (код в ветках, сборка/OTA не выполнялись)
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
8. **Не ронять VPN:** правка только `cell-agent/` → залить файлы на хост VPS, **без** `docker compose restart api nginx`. Полный `deploy_stable.py` рестартит API — старые агенты сот могут снова переключить DNAT (инцидент 2026-08-18).

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
| **Деплой backend на прод (всегда)** | `python scripts/deploy_stable.py` | Все `app/**/*.py` + `ai/**/*.py` + admin-ui/dist. Не пропускать «ради скорости». |
| `deploy_api.py` | `python scripts/deploy_api.py` | **Алиас** `deploy_stable.py` (старый FILES-список снят) |
| VK Calls / агент | `python scripts/deploy_vk_calls.py` | VK auth, vk_manager, admin-ui |
| ConfigSync | `python scripts/deploy_config_sync.py` | `sync-state` и связанные файлы |
| OTA API на backend | `python scripts/deploy_update_backend.py` | Endpoint `/api/updates` (без .exe/.apk) |
| wdtt-server systemd | `python scripts/deploy_wdtt_systemd.py` | Установка/обновление wdtt.service |
| **Улей (Hive)** | `python scripts/deploy_hive.py` | Hive API, cell-agent, admin-ui «Улей» |
| cell-agent на соту | `python scripts/deploy_cell_agent.py <ip>` | Ручная установка agent на VPS-соту |
| **Восстановить код в контейнере** | `python scripts/restore_api_container.py` | После `compose up`/recreate или 404 на `/api/admin/hive/*` |
| **Hardening VPS (UFW, :8000 localhost)** | `python scripts/apply_security_phase1.py` | Без `--force-recreate`; после — проверить Улей в админке |

**Детали и списки файлов каждого скрипта:** `backend/DEPLOY.md` (не дублировать здесь).

**Типовой цикл после правок backend (единственный для Agent):**

```powershell
cd backend\admin-ui; npm run build; cd ..
python scripts/deploy_stable.py
```

`deploy_api.py` — алиас `deploy_stable.py`. Тематические `deploy_vk_calls.py` / `deploy_hive.py` по-прежнему со своими FILES — для прода-фиксов не использовать. Инцидент 2026-08-16 — сломанный вход из‑за неполного FILES.

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

### 2026-07-25 — Автоочистка Улья (Доп. настройки)

- Тумблер **«Автоочистка Улья (диск)»** + интервал (дней) + лимит journal (МБ) + «Очистить сейчас».
- Хост: `deploy_vps_cleanup.py` → timer каждые 15 мин опрашивает `GET /api/vpn/internal/vps-cleanup`; чистит journal/apt/tmp/unused Docker images+build cache (не volumes/OTA).
- API: `GET/POST /api/admin/settings/vps-cleanup`, S2S meta. Сервис: `vps_cleanup_settings.py`.

### 2026-07-25 — Админка: фильтр угроз (DNS) + отключение регистрации

- **«Доп. настройки»** (`/extra-settings`): тумблер регистрации + тумблер **«Фильтр угроз (DNS)»**.
- Фильтр: на Улье `dnsmasq` + автообновление **HaGeZi TIF** (malware/phishing/scam) каждые 6ч (`deploy_threat_dns.py`). При вкл. `wg_dns=10.66.66.1` + DNAT `:53` с `10.66.0.0/16`. Выкл. → снова Яндекс DNS (нужен reconnect).
- API: `GET/POST /api/admin/settings/threat-filter`, S2S `GET/POST /api/vpn/internal/threat-filter*`. Сервис: `threat_filter_settings.py`.
- MVP только Улей (соты без dnsmasq пока не фильтруют). Регистрация: `registration_disabled` → **503** на `/auth/register`.
- Задеплоено: admin-ui + API + `deploy_threat_dns.py` (dnsmasq на `10.66.66.1:53`, HaGeZi TIF ~2.08M доменов, timers 6h/1min). Тумблеры как в Подписках (`h-5 w-9`, `bg-purple-500`). Push `main`.

### 2026-07-25 — Админка: «Доп. настройки» — отключение регистрации

- Новое меню **«Доп. настройки»** (`/extra-settings`): тумблер «Отключить регистрацию».
- `app_settings.registration_disabled` → `POST /api/auth/register` отвечает **503** с текстом «Ведутся технические работы. Регистрация временно недоступна.»
- Вход для уже зарегистрированных не затрагивается. Клиенты (PC/Android) показывают `detail` из ответа API без отдельной сборки.
- API: `GET/POST /api/admin/settings/registration`. Сервис: `app/services/registration_settings.py`.
- Задеплоено на прод (`deploy_api.py`, в список файлов добавлен `registration_settings.py`). Push `main`.

### 2026-08-14 — Первая загрузка: DNS больше не ходит через несущую (fake-ip)

- **Почему 1.0.160 грузился быстрее (не «один сервер»):** там Android поднимал hev с `mapdns` (fake-ip), PC — sing-box `fake-ip`. Клиент **не делал DNS вообще**: домен уходил в SOCKS CONNECT, резолвил `olcrtc-srv`. Плюс комнаты были Jitsi → транспорт `datachannel` (быстрее `vp8channel`; в Телемосте DataChannel вырезан).
- **Что было сломано:** в olcrtc2 fake-ip убрали «для паритета» → каждый холодный домен = TCP-стрим через VP8-несущую до `77.88.8.8`. Первая загрузка = десятки таких RTT, дальше DNS-кеш → «всё летает».
- **Фикс PC** (`src/main/vpn/olcrtc2Session.js`): `dns.fakeip` 198.18.0.0/15, отдельный `carrier-dns` (`detour: direct`) для ICE/TURN/сигналинг-доменов, `cache_file.store_fakeip` (маппинг живёт между сессиями). Проверено `sing-box check` на telemost и wbstream, `npm test` 41/41. sing-box **1.11.15** — `optimistic`/`store_dns` там ещё нет (1.14+), не использовать.
- **Фикс Android** (`OlcrtcTunnelManager.kt`): `mapdns` вернут, VPN DNS = `198.18.0.2`. Пул fake IP — **198.19.0.0/16**, а не дефолт hev `100.64.0.0/10`: на LTE это CGNAT оператора (вероятная причина прошлого отката mapdns; в 1.0.160 `network` вообще не задавался → фейковые `0.0.x.x`).
- Откат одной строкой: `OLCRTC2_MAPDNS = false` в `OlcrtcTunnelManager`.
- Сборки: APK `android/SilentVPN-debug.apk`; PC `pc/build-debug-182837/win-unpacked/SilentVPN-Admin.bat`.
- **Следующий шаг (не сделано):** кеширующий resolver на соте + `OLCRTC2_DNS=127.0.0.1:53` — теперь весь резолв делает srv.

### 2026-08-14 — Кеш сессий olcrtc2: без раннего wipe + lock меню при VPN ON

- **Android/PC bypass menu:** переключение варианта обхода теперь недоступно при активном VPN (ON/CONNECTING). Раньше на PC меню само гасило VPN и переключало канал; теперь только после ручного OFF.
- **Android `Repository.reportOlcrtcRoomFailure`:** убран ранний `clearOlcrtcCacheForProvider()` — слот Telemost/WB не затирается на первом фейле. Старую room блокируем через `lastFailedOlcrtcRoom`, но cache держим как `last-known-good`.
- **Android anti-loop:** debounce room-failure 8с на provider, чтобы ViewModel/Service не стреляли повторный failure каскадом.
- **Android LTE/белые списки:** для `olcrtc2-room-failure` убран public fallback на mobile data (если нет tunnel-path), чтобы не ломать assign вне VPN.
- **PC `bypassStore.reportOlcrtcRoomFailure`:** убран wipe localStorage слота; добавлен debounce 8с по той же room.
- **Backend `olcrtc2_assign.report_room_failure`:** first-hit soft (`suspect_failure`, sticky clear only), второй fail в окне 25с — hard teardown. Это снижает лишние teardown/пересоздания на кратких сетевых сбоях.

### 2026-08-14 — PC Telemost: handshake timeout на prefetch → локальный retry без CONN_FILE

- Симптом в логах PC: `handshake client: read welcome ... timeout` и `olcrtc2: SOCKS не поднялся`, затем только второй connect с новым room успешен.
- Корень: иногда prefetched `telemost-conn.json` протухает прямо перед стартом cnc; первый запуск падает ещё до `SOCKS5 server listening`.
- Фикс в `pc/src/main/vpn/olcrtc2Session.js`: если first attempt упал на handshake-timeout и использовался `OLCRTC_TELEMOST_CONN_FILE`, делаем **авторетрай в том же connect** без CONN_FILE (та же room), без `room-failure`/teardown.
- Эффект: меньше ложных `room-failure`, меньше churn sticky/warm, быстрее восстановление без смены комнаты.
- Сборка: `pc/build-debug-8567/win-unpacked/SilentVPN-Admin.bat`.

### 2026-08-14 — Улей: отдельный журнал инцидентов в админке (ошибки/падения)

- Добавлен backend-буфер `app/services/hive_incidents.py` (кольцевой, dedup 45с): пишет только проблемные события `hive.provision`, `hive.probe`, `cell-agent.status`.
- В `hive_service.fetch_worker_cell_load` теперь логируются провалы `/v1/status` (HTTP>=400 и network/timeout ошибки), чтобы видеть деградацию сот до ручного падения.
- В `app/api/hive.py` добавлены endpoints:
  - `GET /api/admin/hive/incidents?limit=...`
  - `POST /api/admin/hive/incidents/clear`
- В `admin-ui/src/pages/HivePage.tsx` добавлен блок **«Инциденты Улья»**: только ошибки/падения с авто-подсказкой причины (auth, timeout/DPI, DNS, порт/IP, ресурсы) и checklist для быстрой диагностики.
- Цель: зафиксировать момент, когда «Улей через ~час перестаёт работать», и отделить сетевые блокировки (DPI/домен/порт/IP) от проблем ресурсов/процессов.

### 2026-08-14 — Улей: security-инциденты (возможное вмешательство/брутфорс)

- Инцидент-буфер расширен: помимо падений/таймаутов, пишет события безопасности (`security.*`), чтобы видеть не только «сломалось», но и «похоже ломают».
- Источники:
  - `security.admin-host-guard` — заблокированные попытки зайти на admin-поверхность с чужого Host/IP.
  - `security.admin-login-bad-credentials` и `security.admin-login-rate-limit` — подбор пароля/шум на админ-логине.
  - `security.admin-mfa-verify-failed`, `security.admin-mfa-verify-rate-limit`, `security.admin-mfa-resend-*` — злоупотребление MFA.
  - `security.register-rate-limit` — аномальный burst регистраций по IP.
- Классификация в `hive_incidents.py` дополнена security-категориями (`security-auth-abuse`, `security-probing`) с чеклистом: проверка повторяющихся IP/UA, host/path, решение через nginx/фаервол/rate-limit.
- Деплой: `deploy_api.py` обновлён (добавлены `hive_incidents.py`, `admin_host_guard.py`, дополнительные `hive_*` сервисы), прод health после деплоя `200`.

### 2026-08-14 — Авто-сброс «залипшего online» устройств

- Симптом: в Улье и в онлайн-метриках могли висеть «хвосты» (`is_connected=true`), если клиент пропал без `disconnect`/heartbeat.
- Фикс: в `app/services/hive_cell_maintenance_loop.py` добавлен периодический вызов `clear_stale_online_status()` на каждом цикле обслуживания сот.
- Правило offline: устройство переводится в offline, если `last_connected` старше `SESSION_ONLINE_TIMEOUT_MINUTES` (по умолчанию 10 минут).
- Эффект: онлайн по сотам и общий online в админке сходится с фактом даже после сетевых отвалов/крашей клиента.
- Деплой: выполнен через `backend/scripts/deploy_api.py`, API после рестарта отвечает `{"status":"ok","version":"1.0.0"}`.

### 2026-08-14 — Улей: heartbeat звонка не должен «возвращать» device на Соту 1/2

- Наблюдение: при активном VK/olcrtc звонке устройство уходило в online на Соте 1/2, хотя WDTT spill на эти соты выключен.
- Корень: `olcrtc2` heartbeat в `_touch_devices_online()` принудительно перезаписывал `Device.cell_id = room.cell_id`.
- Фикс: в `app/services/olcrtc2_assign.py` смена `cell_id` теперь только если у устройства `cell_id` ещё пустой (`None`), существующая WDTT-привязка (queen/worker) не перетирается.
- Эффект: факт звонка остаётся online, но это больше не выглядит как обратный WDTT-баланс на 1/2.
- Деплой: `backend/scripts/deploy_api.py`, health после рестарта `200/ok`.

### 2026-08-15 — Burst warm при массовом входе (anti "нет свободной комнаты")

- Проблема: при `warm=0/низком warm` и одновременных коннектах assign мог временно отдавать `Нет свободных комнат`, пока агент не успевал пополнить пул.
- Фикс в `app/services/olcrtc2_assign.py`:
  - добавлен трекинг `pool-denied` в коротком окне (`25с`);
  - если накопилось `>=2` deny по провайдеру, включается burst-режим warm на `180с`;
  - burst даёт `+1` к warm-цели (авто-откат после hold), чтобы сгладить входной шторм без постоянного большого idle.
- Дополнительно: `TELEMOST_WARM_PER_DT_CAP` поднят до `2` (базовый warm остаётся 1/dt, но появляется запас для burst).
- Ожидаемый эффект: меньше отказов в пике, при этом idle CPU не держится постоянно на повышенном уровне.
- Деплой: `backend/scripts/deploy_api.py`, API health после рестарта `ok`.

### 2026-08-15 — Smart Apply Refresh (Android + PC) без блокировки меню

- Добавлен фоновой refresh слота после `Apply` при переключении Telemost/WB (или stale/dirty cache), вместо блокирующего fetch в диалоге.
- Android:
  - `Repository`: кеш слота обёрнут метаданными (`at` + `cfg`), добавлены `getOlcrtcCacheAgeMs()` и `shouldRefreshOlcrtcSlot()`.
  - `MenuBypassScreen`: после Apply запускается background `onEnsureOlcrtcApi(...)` с тайм-бюджетом 22с, с подсказкой статуса в UI.
- PC:
  - `bypassStore`: добавлены `getOlcrtcCacheAgeMs()`, `shouldRefreshOlcrtcSlot()`, `refreshOlcrtcSlotFast(timeout)`.
  - `MenuBypassPanel`: после Apply запускается неблокирующий refresh слота с обновлением подсказки.
- Эффект: переключение остаётся мгновенным (как cache-only), но слот подтягивается/освежается автоматически и быстрее готов к следующему connect.

### 2026-08-15 — Exclusions UX + DNS + dark splash

- Android/PC исключения:
  - убран авто-выбор всех приложений при переключении в БС (теперь старт с пустого списка);
  - добавлено действие `Выделить все`, чтобы быстро отметить список и потом снимать по одному.
- PC: тот же сценарий внедрён в `AppExclusionsPanel` (без блока `Показать системные`).
- DNS меню Android/PC:
  - оставлен один серверный пресет `Яндекс (как на сервере)`;
  - старые публичные пресеты убраны из выбора, но `Свой DNS` оставлен.
- Android splash:
  - добавлен тёмный вариант boot-экрана при тёмной теме (по сохранённому режиму `appearance_mode`, fallback на системную тему).

### 2026-08-15 — DNS-меню 1.0.161: возврат к семантике 1.0.160 (НЕ причина тормозов VK)

- **Симптом:** Android, обход VK — контент грузится 10–20 с, серые плейсхолдеры; на APK 1.0.160 всё работает мгновенно.
- **Что меняли в `5c1eb5e`:** в `DnsPreset.kt` дефолт переехал `SERVER → YANDEX`, а `override(SERVER)` стал возвращать `YANDEX.servers` — клиент принудительно ставил публичный `77.88.8.8`.
- **ВАЖНО — это оказалось не корнем.** Проверка прода (`app_settings`): `threat_filter_enabled = false` → `resolve_wg_dns()` отдаёт `DEFAULT_WG_DNS = "77.88.8.8,77.88.8.1"`, т.е. **ровно те же адреса**, что форсил «сломанный» пресет. Коммит был функционально no-op для DNS. `10.66.66.1` уезжает клиенту только при включённом фильтре угроз.
- Откат всё равно оставлен: управление DNS должно принадлежать серверу (важно при включении фильтра угроз).
- **Исправление (Android + PC):**
  - вернули семантику 1.0.160: дефолт `Как на сервере`, `override = null` → DNS берётся из `wg_dns`;
  - в меню остались только `Как на сервере` + `Свой DNS`;
  - `fromId()` мигрирует сохранённые из 1.0.161 id (`yandex`, `cloudflare`, …) обратно в `server` — фикс применяется без сброса данных приложения;
  - `DnsPresetTest` дополнен кейсом миграции публичных пресетов.
- PC: `getDnsOverrideServers()` снова возвращает пустую строку для серверного пресета; `normalizeDnsValue` (уже) отдаёт серверный `wg_dns` при пустом override.
- PC UI: модалка DNS приведена к шаблону окна `Применить?` из «Смены обхода» (заголовок, переход `X → Y`, кнопки).

### 2026-08-15 — Разбор «сломали VK-звонок»: сегодняшние коммиты ни при чём

Ревизия по просьбе пользователя. Сегодня в ветке `android` два коммита, **оба вне VK/WDTT-пути**:

- `3dc4e3c` — только olcrtc: `OlcrtcCacheEnvelope` (поле `at`, чтение обратно совместимо) + фон-обновление слота в меню обхода, которое сразу выходит при `getBypassFamily() != BYPASS_FAMILY_OLCRTC2`.
- `5c1eb5e` — `MainActivity`/`LaunchSplash`/`values-night` (тема запуска), `MenuDnsScreen` (текст), `AppExclusionsScreen` (чекбокс «Выделить все»), `DnsPreset` (см. запись выше — no-op).

`SilentVpnService.kt`, `WdttTunnelManager.kt`, `WireGuardHelper.kt` сегодня **не трогали** (последнее изменение — `0eaf4b0`).

**Реальная дельта 1.0.160 → текущий debug — 7 коммитов (08-11…08-15, ~3.7k строк).** Кандидаты в VK-пути:

1. **`MainViewModel.prefetchOlcrtcSlotsOnVkTunnel()`** — в 1.0.160 отсутствует полностью. Теперь на **каждом** подключении в режиме VK, после sync, клиент тянет конфиги `telemost` + `wbstream`. На бэкенде `/olcrtc2-config` — не чтение, а assign: сервер занимает/поднимает комнаты. Это же объясняет фантомный «1 онлайн на WB» без релиза olcrtc.
2. **`AppExclusionPackages.resolveAppTunnelPolicy`** (`28997f1`) — в БС появились `included.removeAll(VK_TUNNEL_PACKAGES)` и `if (includeAppInTunnel)` вместо безусловного добавления себя; пустой БС молча падает в ЧС (`«БС пуст → ЧС»`). Сегодняшний `5c1eb5e` убрал авто-выбор всех приложений в БС — пустой БС стал реальным сценарием.

Логи с устройства недоступны: Vivo режет `logcat` для приложений — снимать через экран **«Лог»** в самом приложении.

**Сделано:** `prefetchOlcrtcSlotsOnVkTunnel()` удалён из `watchTunnelDataSyncFromCache()` — как в 1.0.160, VK-сессия olcrtc-слоты не трогает. Слоты дотягиваются в Apply «Вариантов обхода» (Smart Apply Refresh) и перед olcrtc-connect. Debug APK пересобран и установлен (`SilentVPN-debug.apk`, 12:09).

### 2026-08-15 — Admin UI: единый строгий dark-стиль + DNS modal fix (PC)

- `backend/admin-ui`: добавлен общий контейнер `admin-theme` и единые style-токены в `src/index.css`:
  - чёрный базовый фон, унифицированные панели/бордеры/типографика;
  - смягчены «разношёрстные» оттенки через глобальные CSS-оверрайды;
  - яркие белые CTA приведены к синему акценту.
- `Layout`: активный пункт меню переведён с white-pill на синий акцент (в общей стилистике панели).
- Цветовая нормализация акцентов: purple-тон глобально смещён к синему (допустимые акценты: синий/красный/зелёный).
- `pc/src/renderer/components/MenuDnsPanel.tsx`: в тёмной теме модальное окно DNS больше не белое (явный dark background + border), `MainScreen` передаёт флаг `dark`.
- Логика API/экранов не менялась — только визуальная часть.

### 2026-08-15 — Hive: показать olcrtc-online по сотам (чтобы не «терялись» сессии)

- Симптом: в `olcrtc2` видно `sessions/online`, но в карточках «Улья» это не отражалось (там считался только WDTT `Device.is_connected`), из-за чего создавалось впечатление «онлайн нет, а комнаты висят».
- Backend (`app/services/hive_service.py`): добавлен подсчёт свежих `olcrtc2_sticky` (окно 300с) по `Olcrtc2Room.cell_id`; в ответ соты добавлены поля:
  - `olcrtc_online_count`
  - `total_online_count = online_count(wdtt) + olcrtc_online_count`
- Summary (`/api/admin/hive/summary`) теперь отдаёт:
  - `total_online_olcrtc`
  - `total_online_all`
- Schema (`app/schemas/hive.py`) расширена новыми полями, чтобы FastAPI не отбрасывал их из response_model.
- Admin UI (`admin-ui/src/pages/HivePage.tsx`): в шапке и карточке соты показаны `wdtt / olcrtc / итого`, чтобы сразу видеть реальную онлайн-нагрузку и не путать её с warm-комнатами.

### 2026-08-15 — Android WB зависал через несколько минут: восстановлен recovery-path

- Симптом: WB на Android «висит» через несколько минут, на PC при этом работает.
- Корень в клиенте Android: `markPeerLivenessSuspect()` при текущей policy (`shouldForceSocksDialOnLivenessSuspect=false`) делал ранний `return`, из-за чего recovery-грейс не запускался; часть зависаний оставалась без авто-восстановления.
- Фикс в `android/app/src/main/kotlin/com/silent/vpn/vpn/OlcrtcTunnelManager.kt`:
  - `markPeerLivenessSuspect()` теперь **всегда** запускает `schedulePeerClosedGrace(...)`;
  - для `wbstream` включён `forceLivenessCheck` (форс-dial в grace-проверке), чтобы не маскировать half-dead состояние «остаточным трафиком»;
  - добавлен `shouldForceRecoverForWb(reason)` — для WB разрешён auto-recover на `peer_closed/media_timeout/missed_pong/stream_dead/openstream_timeout/socks_*`.
- Для Telemost поведение оставлено прежним (без агрессивного рестарта на transient glitch), чтобы не вернуть долгие перезапуски.
- Проверка: `android/app` → `.\gradlew.bat compileDebugKotlin` — `BUILD SUCCESSFUL`.

### 2026-08-15 — olcrtc2 sessions показывал «фантомный онлайн» без реального звонка

- Симптом: в админке `olcrtc 2.0` мог висеть `Online (sessions)=N`, даже когда на WB/Telemost фактически никого нет.
- Корень: `pool_stats()` считал **все** `olcrtc2_sticky`, а `sticky.updated_at` продлевался даже при обычном `GET /api/vpn/olcrtc2-config` (assign config без media).
- Фикс (`app/services/olcrtc2_assign.py`):
  - `_save_sticky(..., touch=False)` для путей assign (`ensure_session_room`), чтобы запрос конфига не продлевал «online»;
  - heartbeat оставлен `touch=True` (реальный live-сигнал);
  - `pool_stats()` теперь считает только **свежие sticky** (`updated_at >= now - HEARTBEAT_STALE_SEC`), а не весь исторический хвост.
- Эффект: `sessions/online` в блоке olcrtc2 отражает фактическую активность, а не кэш/предзагрузку слота.
- Деплой: `python scripts/deploy_api.py`, health/tunnel-check — OK.

### 2026-08-15 — Android WB: «работает и потом умирает» (decrypt/auth fail)

- Лог с устройства: после `tunnelReady` и `peer connected` периодически появляется
  `muxconn: decrypt failed ... chacha20poly1305: message authentication failed`, после чего WB со временем «умирает».
- До фикса этот паттерн не эскалировался в recovery: мог оставаться «полуживой» канал без быстрой смены комнаты.
- Фикс в `OlcrtcTunnelManager.kt`:
  - добавлен `decryptFailStreak`;
  - при повторе `decrypt failed / message authentication failed` на WB (порог 2) → `markPeerLivenessSuspect("decrypt_fail", ...)`;
  - для WB это доходит до `notifyPeerDead` и авто-recover.
- Фикс в `OlcrtcRecoveryPolicy.kt`:
  - `shouldRefreshConfigOnRecover()` теперь для `decrypt_fail` принудительно берёт **новую комнату** (reassign), а не стартует старый кеш.
- Сборка: `compileDebugKotlin` + `assembleDebug` — `BUILD SUCCESSFUL`.

### 2026-08-15 — Android WB: убран сценарий «подвис 1–2 мин и сам отвис»

- Симптом после предыдущего фикса: на Android WB мог подвисать на несколько минут и потом «сам оживать».
- Причина: при `peer_closed` WB мог оставаться в состоянии «SOCKS жив, но peer не вернулся в connected», и recovery не срабатывал.
- Фикс (`OlcrtcTunnelManager.schedulePeerClosedGrace`):
  - добавлен флаг `requirePeerReconnect` для WB;
  - если для WB в grace-окне peer не вернулся в `connected`, запускаем recovery сразу, даже если SOCKS dial формально проходит.
- Эффект: меньше «серых зависаний», быстрее принудительный reassign при полуживом WB-канале.
- Параллельно по просьбе пользователя откатили admin-ui от синего акцента к чёрно-серой палитре:
  - `backend/admin-ui/src/index.css` (токены/оверрайды CTA/фиолетовых акцентов),
  - `backend/admin-ui/src/components/Layout.tsx` (active nav обратно в серый).
- Деплой: `python scripts/deploy_api.py` — OK; Android debug пересобран (`assembleDebug`).

### 2026-08-15 — Android WB: почему виснет при DNS=1.1.1.1 и почему потом «само отпускает»

- Реальная причина: `olcrtc2` на Android брал DNS через `systemDnsHostPort(activeNetwork)`, а не через provider-aware DNS цепочку обхода. При выпадении в `1.1.1.1` (или сетевой DNS оператора) в WB режиме периодически получался полуживой канал: peer закрыт/десинхрон, но SOCKS ещё «жив».
- Поэтому наблюдался паттерн пользователя: «через пару минут зависает, потом через 1–2 минуты отвисает, потом может снова».
- Фикс в `OlcrtcTunnelManager.kt`:
  - добавлен `olcrtcDnsHostPort(context, provider)` → берёт DNS из `resolveOlcrtcDnsServers` (`DnsSettings.ipv4ServersForOlcrtc`);
  - для WB это fallback-first (стабильный резолв), а не `activeNetwork`/жёсткий `1.1.1.1`;
  - логируется строка `olcrtc2_dns: dns=... provider=...` для быстрой проверки на устройстве.
- Сборка: `compileDebugKotlin` + `assembleDebug` — успешно.

### 2026-08-15 — Android WB: добивка против зависания (heartbeat socks fail)

- По свежему логу: при живой сессии периодически возникают
  `[HB] socks CONNECT fail host=132-243-234-162.nip.io:443`, но трафик ещё идёт.
  Это и создаёт «подвис/потом отпустило» на Android.
- Фикс в `OlcrtcTunnelManager.noteSocksPathFail`:
  - для WB lowered threshold: `suspectStreak=2` (вместо общего 3);
  - для WB всегда эскалация в `markPeerLivenessSuspect("socks_api_fail", ...)` (не зависит от global `shouldForceSocksDialOnLivenessSuspect=false`);
  - grace учитывает `providerGraceMs`.
- Эффект: WB быстрее уходит в controlled recover/reassign до долгого «залипания».
- Сборка debug: `assembleDebug` — `BUILD SUCCESSFUL`.

### 2026-08-15 — Android WB: финальная агрессия против фризов

- По запросу «убрать зависание вообще»: для `wbstream` в `noteSocksPathFail()` порог эскалации снижен с 2 до 1.
- Теперь любой `HB socks CONNECT fail` на WB сразу переводит сессию в recover-путь (без ожидания второй ошибки).
- Цена подхода: возможны более частые быстрые recover при редком ложном fail, но это лучше долгого зависания.
- Сборка: `compileDebugKotlin` и `assembleDebug` — успешно.

### 2026-08-18 — VPN на соте пропал и через время вернулся: ложный standby DNAT

- PC `my@silent27-99.ru` сидел на **Сота 2** (`server3`). wdtt на Улье/сотах **не рестартили**.
- **Сервер:** слой 3 `standby_monitor_loop` при **одном** фейле `/health` Улья сразу делал DNAT `10.66.66.1:8000 → 127.0.0.1:8000`. Деплой `api+nginx` в 19:51 МСК + автоапгрейд cell-agent: Сота 2 в 16:51:58 UTC — «Улей недоступен». Сота 1 так флапала весь день (десятки раз). Туннель API на соте отваливался, клиент терял heartbeat; через время health ок → DNAT обратно на Улей.
- **Локально:** `build-debug.bat` в ~20:00 убил `Silent VPN.exe` / `wdtt-client.exe`. PC `last_connected` 20:21 МСК — после нового debug.
- Отдельно в 17:49 МСК админ `revoke-subscription` снял 2 Android Vivo этого аккаунта (не этот обрыв PC).
- **Фикс на прод (без рестарта api/wdtt):** health сначала на `HIVE_QUEEN_IP:8000`; standby только после **3** фейлов (~45 с); при старте агента DNAT сразу на Улей. Файл залит в host `cell-agent/` (volume), автоапгрейд сот пока Улей жив. Тест: `scripts/test_cell_wg_gc_unit.py`. Правило навсегда: раздел «Инвариант: не ломать старых клиентов…».

### 2026-08-18 — Слой 3 failover + онлайн сот в Улье + нода в дашборде

- Клиент, если public API Улья не открывается, пробует cell-agent соты `http://IP:9100/api/*`. Пока Улей жив с точки зрения соты — запрос проксируется на Улей (вход/оплата работают, даже если клиенту режут IP Улья). Если Улей мёртв — снимок theme/hive-meta; login/оплата 503.
- Theme всегда отдаёт актуальные `hive_standby_api_urls`. Android/PC кешируют URL + запас Сота 1/2. Админка: онлайн соты = max(БД, WG live &lt;3м); дашборд «Онлайн: устройство · Улей/Сота N» зелёным.
- `/hive/cells` больше не вызывает rebalance на каждый poll.
- Пуш / debug-сборки клиентов — по запросу.

### 2026-08-18 — Соты автономны без копии всей БД: локальный WG GC + snapshot слота

- Полный дамп Postgres на каждую соту **не делаем** (рассинхрон login/register, устаревание снимка, секреты × N, не спасает тех, чей endpoint — Улей).
- **Слой 1:** cell-agent сам чистит GETCONF extras на `wdtt0` (те же правила, что на Улье: never-hs после 90 с, handshake >6 ч, ключи из manifest не трогать, wdtt не рестартить). Цикл в `standby_runtime.py`, без alpine с Улья. `agent_build_id` = hash `main.py`+`standby_runtime.py`.
- **Слой 2:** manifest на соту — устройства с `cell_id` этой ноды **или** `preferred_server` = слот (Сота 1 → server2, Сота 2 → server3), плюс `vpn_allowed`. Не 800 строк всей БД. Поле `server_slot` в JSON.
- Админка Улей: `WG peer’ы / never-hs / live` из `/v1/status`.
- Прод: `deploy_stable.py` (api/nginx restart, DNAT tunnel OK, **wdtt не трогали**). Автоапгрейд агента на Соту 1 и 2. После GC: Сота 1 **157→50** (never-hs extras сняты, 33 ключа = snapshot слота), Сота 2 **111→49** (28 ключей слота). Обе `wdtt`+`silent-cell-agent` active. Тесты: `test_cell_wg_gc_unit.py`, `test_hive_slots_unit.py`, `test_vpn_kick_unit.py`.
- Пуш — когда скажешь «пуш».

### 2026-08-18 — Улей: текст балансировки + обрыв ~10 с от alpine GC

- Текст «Перегруз — новые на соты» в админке остался, потому что при слотах Сервер 1/2/3 **не выключали** старый copy и `GET /summary` всё ещё вызывал `rebalance_overloaded_cells` на каждый poll (10 с). Живой VPN слот не перекидывает; клиент сам выбирает ноду.
- Обрыв ~10 с ~14:58 UTC: GC/kick каждый раз делал `docker run alpine` + `apk add` на **docker0** (dmesg veth up/down). Kick 14:49, GC 15:00. Не рестарт wdtt.
- Фикс: постоянный helper `silent-nsenter` (`--network host`), dump/kick/GC через `docker exec`; `/summary` больше не балансирует. HivePage: «Серверы», не «балансировка».

### 2026-08-18 — Обрывы VPN: GC peer’ов + клиенты не рвут туннель при 0 воркерах

- Причина обрывов: таблица `wdtt0` была забита GETCONF-мусором (**2766** peer’ов, живых handshake ~54), плюс Android/PC убивали libclient, если воркеры мигали в 0 при живом WireGuard.
- One-shot на хосте (`wg set … remove`, **без рестарта wdtt**, ключи `devices` не трогали): **2541** снято, **2766 → 225**, live hs&lt;3м **70**, never-hs **0**. Пользователей/подписок не удаляли.
- Фоновый GC в API: `wg_peer_gc.py` из hive maintenance (~90 с). Снимает только extras: never-hs после 90 с grace и handshake &gt;6 ч. `Device.wg_public_key` не удаляет. Kick по-прежнему не угадывает GETCONF extras.
- Android: `isTransportHealthy()` = WG + процесс жив (воркеры не обязательны); `watchdog_zombie` не `killProcess`, если туннель жив.
- PC: то же — `isTransportHealthy()` без требования воркеров; watchdog 90 с не рестартит wdtt, если WG жив.
- Прод API: точечный docker cp четырёх файлов + restart api/nginx, DNAT tunnel OK, health `ok`, wdtt `active`. Версия клиентов **1.0.161**. Debug APK: `android/SilentVPN-debug.apk`.
- Пуш — когда скажешь «пуш» (вместе с vpnbase/compose с прошлого прохода).

### 2026-08-18 — Аудит Улья: vpnbase GitHub снят, 0 воркеров из-за WG peers

- Инциденты `hive.vpnbase` / `hive.maintenance` (422 sha, 503): это **не** архив Postgres и не удаление пользователей. Каждые ~10 с шифрованный hive-manifest уходил в `silentvpn3/vpnbase` (`VPNBASE_GIT_ENABLED=true`). API CPU ~113%. Реализация удалена из кода, флаги вычищены из `.env`. Standby cell-agent на сотах оставлен.
- Обрывы VPN / «на одном телефоне 0 воркеров, на соседнем всё ок»: оператор ни при чём. `wdtt0` **2766** peer’ов при **54** live handshake (<3 мин), 1290 never-hs, 1256 hs>6ч; wdtt RSS **4.4 ГБ** (MemoryHigh 4 ГБ). Новый GETCONF на втором телефоне; живая сессия на первом. wdtt **не** рестартили.
- Деплой backend: один канон `deploy_stable.py`; `deploy_api.py` стал алиасом (больше нет дырявого FILES).
- Мёртвый контейнер `backend-wdtt-1` (Created, never started) снят. Сервис `wdtt` убран из `docker-compose.yml` — живой wdtt только systemd. `docker compose up` больше не поднимет второй wdtt на :56000.
- GC peer’ов сделан 2026-08-18 (см. запись выше).

### 2026-08-17 — LTE: нет «Ошибка синхронизации» в уведомлении

- Лог телефона: GETCONF уже UP, `client_sync` в кеше, а `VpnDataSyncService` всё равно POST `/vpn/connect` через proxy → 502 (`EPERM` bind к VPN Network) и подменяет FG-уведомление VPN (`id=1001`) текстом «Ошибка синхронизации».
- На LTE + excluded HTTP после main VPN не делаем: snapshot уже с `/vpn/config`, online — wdtt `/internal/online` по GETCONF/DTLS.
- `VpnDataSyncScheduler` не стартует второй FGS; ConfigSync не ходит в overlay/HTTP. Отзыв по-прежнему in-band.
- Версия 1.0.161.

### 2026-08-17 — Промокод: короткий bootstrap и возврат main VPN

- Proxy на LTE не доходит (app excluded). Overlay на живом VPN рвёт handshake.
- Проверка при включённом VPN: короткий bootstrap (локальный hash, без public timeout) → API → сразу тот же main WG из кеша. Тумблер сам возвращается во «вкл».
- Overlay на main не используем.

### 2026-08-17 — Промокод не рвёт живой VPN

- Overlay `startTunnel` на main VPN мигал иконку, рвал handshake → «Не удалось обновить данные: failed to connect», после этого интернет мёртв до reconnect.
- Промокод при включённом VPN: только `TunnelApiProxy` (bind к уже живому WG), без overlay. Временный bootstrap — только если VPN выключен (LTE).
- Vivo logcat пуст (режется); на переднем плане был Max.

### 2026-08-17 — Диагностика RAM Улья: не API, а wdtt heap + мёртвые WG peer’ы

- Хост 9.6G: used 5.8G, available 3.8G (кэш). Swap нет.
- **wdtt-server RSS ~4.46G**, почти всё `[anon: Go: heap]` 4.38G. Uptime с 1.08, MemoryHigh=4G уже превышен (peak 4.42G), PSI memory some~34% / full~24% — ядро постоянно сжимает cgroup.
- Живых: **~88–91** (БД `is_connected` и handshake <3 мин). WG peer’ов на `wdtt0`: **2718** (1306 never-hs, 1150 handshake >6ч). UDP :56001 ~5600 сокетов.
- API после деплоя ~253MB — утечки `client_sync` нет. journal на диске 4.0G (не RAM). dnsmasq threat-dns ~145MB.
- wdtt не рестартили. Корневая причина: GETCONF плодит peer’ов, старые не GC.

### 2026-08-17 — client_sync с /vpn/config + promo overlay без DOWN

- Рефералка/профиль/тема едут в `VpnConfigResponse.client_sync` на `/device/register` и `/vpn/config` (рядом с GETCONF/DTLS, без overlay-sync на connect). В GETCONF extras полный snapshot не кладём (буфер wdtt 4 КБ).
- Android/PC применяют snapshot при получении конфига; ссылка в «Бонусах» берётся из кеша сразу.
- Промокод при живом VPN: отдельный overlay — приложение на секунду в туннель, AllowedIPs не сужаем, WG не гасим (hot reload без DOWN). После проверки exclude возвращается.
- Overlay на тумблере Connect не включали. Cache-first skip `/vpn/config` не брали (ломает отзыв).
- Версия 1.0.161.

### 2026-08-17 — Откат к рабочим YuMoney/подписка коммитам

- GitHub + локально: backend `01767ed` (main), Android `505f18d` (android), PC `a939f67` (pc). Force-with-lease на все три ветки.
- Прод: `python scripts/deploy_stable.py` (api+nginx, wdtt не трогали). Health `ok`, tunnel DNAT OK.
- Android debug APK `android/SilentVPN-debug.apk` с `505f18d`.

### 2026-08-17 — Оплата: временный VPN до возврата из браузера (не после SMS)

- Webhook после SMS приходит раньше YuMoney success-page. Клиент больше не гасит bootstrap в фоне — иначе на LTE белый экран вместо «Вернуться в Silent VPN».
- Подписка в UI помечается completed, туннель живёт, пока приложение в фоне; гасится на `onResume` / `silentvpn://payment`.
- Android debug APK; PC — не стопать bootstrap, пока окно скрыто.

### 2026-08-17 — Оплата: подтверждение не крутит спиннер, если подписка уже есть

- Временный VPN оплаты больше не гасится при возврате из браузера «потому что профиль уже загружен» — только после `subscription.is_active`.
- Если на главном подписка уже активна, экран «Подписка» сразу показывает успех, а не вечное ожидание webhook.
- Если туннель упал в фоне — поднимаем его снова, пока подтверждение не завершилось. `runEphemeralApiBootstrap` во время ожидания оплаты не вызываем (он рвал hold в `finally`).
- Android debug APK; PC тот же UX подтверждения.

### 2026-08-17 — Оплата: вернуться в приложение, не на сайт; не выкидывать из аккаунта

- YuMoney «вернуться на сайт» открывает `silentvpn://payment` (страница success с кнопкой и авто-редиректом).
- Android больше не показывает экран входа из‑за временного VPN оплаты — сессия сохраняется, открывается «Подписка».
- Профиль обновляется **пока bootstrap ещё жив**; туннель гасится после `subscription.is_active`.
- Poll label сохраняется, чтобы после возврата из браузера добрать webhook.
- Прод: `python scripts/deploy_stable.py` (только api+nginx, wdtt не трогали). Health 200, success-page с `silentvpn://payment`.

### 2026-08-17 — Отзыв UX + любые серверы + YuMoney bootstrap

- Snackbar «Failed to connect» при отзыве подписки больше не показывается: всегда текст про оформление подписки.
- Слоты серверов универсальные: Улей=`server1`, Сота N=`server{N+1}` (Сота 3 → Сервер 4). Список в меню с `GET /api/vpn/servers`, не хардкод 1/2/3.
- Оплата без интернета: по кнопке тарифа поднимается временный bootstrap VPN (как подтверждение почты) и держится, пока открыт YuMoney / идёт poll.
- Android debug APK; backend слоты — `deploy_stable.py` когда добавите новую соту.

### 2026-08-17 — Android: тумблер на том же сервере не видел отзыв подписки

- Смена сервера + Connect шла в `getConfig` → 402. Тумблер на том же слоте поднимал WG из кеша (`connect cache slot=`) и API не спрашивал.
- Теперь каждый Connect заново fetch’ит конфиг (на LTE через bootstrap). 402 → paywall, кеш WG чистится. Выдача подписки по-прежнему через тот же fetch (200).
- Overlay после main VPN и kick чужих GETCONF-peer’ов не включаем.

### 2026-08-16 — ИНЦИДЕНТ: kick GETCONF extras снимал VPN у всех на соте

- Sweeper каждые ~10 с брал «самый свежий» GETCONF-peer на Соте 2 и удалял его. Это были чужие сессии (`10.66.0.16/19/27/30`).
- Откат: kick только известный `Device.wg_public_key` / IP. Угадывание extras выключено.
- Деплой: `python scripts/deploy_stable.py`. Пользователям на Соте 1/2: переподключить VPN.

### 2026-08-16 — Отзыв на соте: один раз, потом GETCONF поднимает VPN снова

- Лог телефона: Сота 2, живой GETCONF `wg=10.66.0.25`, handshake живой. «Ошибки» — `UAPIOpen permission denied` и `mobile excluded API outside overlay` (ожидаемо, overlay после main VPN нет).
- Первый kick снимал leftover `10.66.0.23` (совпал с `last_connected`), живой peer не трогал. GETCONF сразу выдавал новый ключ. Sweeper ставил `is_connected=false` и больше не бил.
- Фикс `vpn_kick.py`: на соте бить **самый свежий** GETCONF extra; не биндить leftover в `devices`; 25 мин watchlist после revoke; sweeper каждые ~10 с повторяет kick, пока GETCONF не перестанет поднимать peer.
- Деплой: `python scripts/deploy_stable.py`. Overlay после main VPN не включаем.

### 2026-08-16 — Отзыв VPN: kick по SSH на соту

- Первый kick не сработал: клиент на соте, cell-agent ещё без `/v1/wg/kick`, HTTP 404, peer жил.
- Теперь revoke снимает peer по SSH (`wg set wdtt0 peer remove`) — тот же канал, что провижининг. Плюс поиск по `allowed-ips`.
- Стабильный деплой повторно, health OK.



- Залит `python scripts/deploy_stable.py` (не точечный `deploy_api.py`).
- `vpn_kick.py` + revoke снимают живой WG peer; cell-agent `/v1/wg/kick`.
- `docker compose restart` только `api`/`nginx`. wdtt-server не трогали.
- Tunnel health `10.66.66.1:8000` OK. Админку не пересобирали.
- В `deploy_stable.py` убран `docker cp` в `cell-agent` (`:ro` volume обрывал скрипт до restart).

### 2026-08-16 — LTE: отзыв подписки через GETCONF + снятие WG peer

- HTTP overlay после включения на LTE не дотягивается до API (приложение excluded, nip.io в БС). Выдача подписки при connect работала, отзыв — нет.
- Сервер при revoke снимает живой WireGuard peer (`wg set … remove`) на Улье и сотах. Это гасит интернет в туннеле без HTTP от клиента.
- Клиент раз в 30 с повторяет GETCONF по уже живому DTLS. Если сервер ответит `DENIED:` — VPN гаснет и UI снимает подписку.
- Overlay `/users/me` оставлен как запасной путь (таймер 2 мин только после успеха, повтор через 20 с при ошибке).
- Нужен деплой backend (`deploy_stable.py`), иначе на проде peer не снимется. Debug APK с новым libclient.



- После фикса онлайна Улья `deploy_api.py` копировал hive/vpn-код с `device.preferred_server`, но **не** `app/models/device.py`. Образ API был без поля → 500 на login/connect/servers/internal/online.
- Модель залита в контейнер. Правило: на прод backend **только** `deploy_stable.py` (копирует все `.py`), не точечный FILES-список.

### 2026-08-16 — Админка: все пользователи в списках

- «Пользователи» и «Подписки» брали `limit=100/200`, дашборд считал всех — ранние аккаунты не находились поиском.
- `GET /api/admin/users` без лимита отдаёт полный список.

### 2026-08-16 — Временно все тарифы 15 ₽ (тест оплаты)

- На проде `PRICE_MONTHLY/QUARTERLY/YEARLY=15`. Откат: 199 / 499 / 1499.
- YuMoney берёт 15 ₽ с любого тарифа. Кнопки в уже стоящих клиентах 1.0.161 могут ещё показывать старые цифры — сумма в браузере будет 15.

### 2026-08-16 — Улей: онлайн на Сервере 2/3 (Сота 1/2)

- Балансир olcrtc каждые 30 с сбрасывал `cell_id` с Соты 1/2 на Улей (ещё со времён «WDTT не на olcrtc»). Клиенты с `preferred_server=server2/3` числились на Улье, в админке на серверах 2 и 3 их не было видно.
- Сводка «Онлайн VPN» не считала Соту 1/2 (`accepts_wdtt=false`).
- Фикс: онлайн/привязка по выбранному слоту; ручной server1/2/3 не трогает rebalance; `POST /connect` и keepalive восстанавливают `cell_id`; при старте API чинится БД. В карточках сот бейдж «Сервер 1/2/3».

### 2026-08-16 — Улей: инциденты больше не прыгают, пишутся в Postgres

- Прыгали: uvicorn `--workers 2` (у каждого свой RAM) + persist падал (`ts` строкой, asyncpg ждёт datetime).
- Теперь GET читает БД; запись с datetime. Очистка только кнопкой «Очистить».
- Сеть «умерла и ожила» у клиента в РФ может быть ТСПУ/DPI; журнал как раз чтобы копить такие окна, а не терять их.

- Android: 3с при flood + 0 воркеров, иначе таймаут — каскад vkcalls→автокапча→ручная. Не alert «туннель не поднялся».
- PC ждал 90с и писал `connect timeout`, потому что `waitVpnReady` возвращал `false`, а эскалация была только при `ready === 'flood'` и ещё резалась `installing`/`wg`.
- Теперь: flood с 3с; таймаут без воркеров тоже эскалирует; WG из кеша не блокирует.
- Debug: `pc/build-debug-531973/win-unpacked/SilentVPN-Admin.bat`

### 2026-08-16 — PC: flood не уходил в капчу, если WG уже из кеша

- Лог: `kind=flood error_code=9`, `Активных: 0`, при этом `[WG] Bypass …` уже был — ранний туннель из кеша.
- `waitVpnReady` требовал `!wg`, поэтому реальный flood ждал 90с без каскада vkcalls→автокапча.
- Теперь эскалация при 0 воркерах после 15с; не рвём только если служба ещё ставится.
- Debug: `pc/build-debug-430235/win-unpacked/SilentVPN-Admin.bat`

### 2026-08-16 — PC debug: DNS как в 1.0.160

- Сборка: `pc/build-debug-462169/win-unpacked/SilentVPN-Admin.bat` (UAC). В логе при полном туннеле: `DNS на адаптере: 1.1.1.1, 1.0.0.1, 77.88.8.8` (если не «Свой DNS» и не фильтр `10.66.66.1`).

### 2026-08-16 — PC: Telegram сломался в 1.0.161 из‑за DNS (не отдельный код)

- В 1.0.160 адаптер WG всегда ставил `1.1.1.1, 1.0.0.1, 77.88.8.8` (серверный `wg_dns` игнорировался).
- В 1.0.161 меню «Как на сервере» стало прокидывать API `wg_dns` — обычно только Яндекс `77.88.8.8, 77.88.8.1`.
- Telegram Desktop резолвит через системный DNS адаптера; Chrome/YouTube часто идут по DoH — поэтому YT жил, TG нет. На Android VpnService ловит DNS иначе.
- Фикс: снова Cloudflare+Yandex, как в 160. Исключение — фильтр угроз `10.66.66.1`. Свой DNS из меню по-прежнему важнее.
- Отдельный IPv6-disable / lock Telegram.exe не оставляем — в 160 этого не было.

### 2026-08-16 — Android: DNS-текст как на PC + сон в кармане

- Меню DNS: то же описание, что на PC — «Используйте рекомендуемый DNS или укажите свой. Применяется при следующем подключении VPN.» (убраны «Яндекс» и «публичный»).
- Сон/карман: doze снимает VALIDATED на LTE → клиент думал, что сеть пропала, каждые 2 с слал `internet_restored` и рвал туннель; после паузы poll не видел resume. Теперь флаг сети = INTERNET без VALIDATED, пауза только после 8 с дыры, poll/watchdog/SCREEN_ON сами поднимают туннель.
- Нагрев: отдельный wakelock не добавлял; часть жалоб могла быть от этого цикла restart в кармане. Остальной нагрев — OEM/SoC.

### 2026-08-16 — Релизы 1.0.161 (без bump версии)

- Хеш как есть: `6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY`. Версию не поднимали.
- Android: `android/app/build/outputs/apk/release/SilentVPN-release.apk` (~89 МБ), 12:29 — DNS-текст + сон в кармане.
- PC: `pc/build-release-v141-750629/Silent VPN Setup 1.0.161.exe` (~94 МБ), копия в `releases/` — DNS как 1.0.160 + flood/звонок → автокапча как Android.
- OTA на сервер не заливали.

### 2026-08-16 — PC: ложный timeout на VKCalls → невидимая автокапча

- Лог: `timeout escalate → Авто капча` при живом автозвонке. 45с + flood-abort 8с сносили WG (полная переустановка службы) и поднимали legacy/капчу.
- Капча только при реальном flood; VKCalls ждёт 90с; если WG уже ставится/есть воркеры — не эскалируем.
- Шум `[API] tunnel … публичный API` во время капчи/settle приглушён.
- Сота: `ECONNREFUSED 10.66.66.1:8000` больше не орём в лог — сразу public, туннель API не долбим.
- Сборка: `pc/build-debug-510510/win-unpacked/SilentVPN-Admin.bat`.
- Push `pc`: `37807de` `fix(pc): keep VKCalls connect and skip dead tunnel API noise`.

### 2026-08-16 — Android LTE: Silent снова вне туннеля

- Прошлая сборка держала приложение внутри WG на LTE → VK/TURN шли в свой туннель, воркеры замирали на 2–3, VPN не работал.
- Main VPN снова **всегда** excludes Silent (как 1.0.160). Overlay только кратко для `/users/me` и initial sync. `bindProcessToNetwork` снят — он тоже уводил libclient в WG.
- Сборка: `android/SilentVPN-debug.apk`.

### 2026-08-16 — Android LTE: приложение в туннеле, без overlay

- Overlay в 1.0.160 обновлял подписку только в момент включения: выдача с сервера видна, отзыв после включения — нет (приложение снова excluded, до API не достучаться).
- На LTE Silent теперь сразу внутри WG (`0.0.0.0/0` не трогаем). HTTP на `10.66.66.1` весь сеанс. Интернет не мигает, старт не медленнее.
- Опрос `/users/me` каждые 2 мин: и выдача, и отзыв. Если на сервере подписки нет — клиент сам гасит VPN.
- Backend: revoke поднимает `user.updated_at` и сбрасывает online устройств.
- Сборка: `android/SilentVPN-debug.apk`. Backend на прод — когда скажешь «деплой».

### 2026-08-16 — Android LTE: снова overlay как в 1.0.160

- В 1.0.160 приложение excluded из WG. На LTE public nip.io режется, proxy до `10.66.66.1` не доходит. Работал **один overlay при включении**: кратко AllowedIPs = `10.66.66.0/24` + приложение внутри туннеля → HTTP на `10.66.66.1`.
- 1.0.161 сломал это: `082f7fd` убрал overlay, `31fa2ae` пошёл в public, потом proxy-only. Отсюда «Ошибка синхронизации», дёрганье тумблера и «подписка кончилась» при живой подписке.
- Вернул путь 160: initial sync через `withApiOverlayBrief`, user API (промо/подписка/оплата) — overlay brief, TunnelApiProxy только на Wi‑Fi. Версию не поднимали.

### 2026-08-16 — Android LTE: полный VPN + proxy, без дёрганья overlay

- Overlay на тумблере рвал `0.0.0.0/0` → `10.66.66.0/24` (интернет мигал), HTTP за 350 мс не успевал → «Ошибка синхронизации». Потом ConfigSync на LTE ждал overlay вечно, подписку с сервера не брал.
- Теперь полный туннель не трогаем. App excluded ходит в API через TunnelApiProxy (`127.0.0.1` → `10.66.66.1`), не через заблокированный nip.io. Подписка опрашивается и на LTE при живом VPN.

### 2026-08-16 — Android: вернули overlay на тумблере (подписка на LTE)

- Коммиты `082f7fd` (без overlay) и `31fa2ae` (public first) на мобильном интернете при блокировках nip.io не дотягивали `/users/me` → в UI «подписка кончилась», хотя она живая.
- Снова: включение VPN → overlay `10.66.66.0/24` → профиль/хеши через `10.66.66.1`. Подписка/оплата на LTE — `withApiOverlayBrief`, не public API.

### 2026-08-16 — PC/Android: update + sync + реферал и с VPN, и без

- PC: `[Update] check fail: Update check timeout` — check шёл на hostname nip.io через полный туннель и зависал; `10.66.66.1` давал ECONNREFUSED. Теперь check/download как ConfigSync: public IP+Host (bypass), tunnel только запасной.
- Android LTE: sync/реферал/OTA не пробовали public (app excluded) → «Ошибка синхронизации», ссылка «…». Public first и с VPN, и без.
- Сборки: `android/SilentVPN-debug.apk`; PC `pc/build-debug-510510/win-unpacked/SilentVPN-Admin.bat`.
- Push `android`: `31fa2ae` `fix(android): sync referral and OTA over public API`.

### 2026-08-16 — Android: интернет сразу, без overlay на connect

- В 1.0.160 туннель `0.0.0.0/0` уже давал картинки, а данные шли фоном (Wi‑Fi public / proxy). Overlay `10.66.66.0/24` как раз глушил интернет до конца sync.
- Убрал overlay с initial sync и ConfigSync. Sync: Wi‑Fi public, LTE TunnelApiProxy, AllowedIPs не трогаем.
- Сборка: `android/SilentVPN-debug.apk`.

### 2026-08-16 — PC: syncconf после смены сервера

- При выборе сервера незащищённый `Disable-NetAdapter` прошлого disconnect снимал уже новый `wg-turn` → `syncconf: No such file` и лишняя переустановка.
- Disable только в очереди stop с epoch; syncconf не вызываем, если адаптера нет.
- Сборка: `pc/build-debug-660125/win-unpacked/SilentVPN-Admin.bat`.

### 2026-08-16 — PC tunnel API settle + Android overlay на Улье (Wi‑Fi)

- **PC:** `Tunnel API timeout — публичный API` при живом туннеле: ConfigSync бил в `10.66.66.1` до готовности маршрутов. Теперь ждём settle и не орём «недоступен»; fallback тише.
- **Android:** overlay initial sync не только LTE, а любой excluded (Улей / сервер 1–2 на Wi‑Fi). В overlay не уходим на public — обновляем WG-кеш через tunnel. Битый кеш не применяем (проверка ключей), без ошибки «невалиден».
- Сборки: PC `pc/build-debug-437088/win-unpacked/SilentVPN-Admin.bat`; Android `android/SilentVPN-debug.apk`.

### 2026-08-16 — PC: быстрый съём адаптера + Android overlay sync как 1.0.160

- **PC:** после выкл Windows ещё писала «VPN включён», пока `uninstalltunnelservice` (10–20 с). Теперь `Disable-NetAdapter` сразу при disconnect, служба снимается в фоне.
- **Android:** вернул LTE initial sync через `withApiOverlayBrief` как в 1.0.160 (кэш/хеши/профиль обновляются при включении). Прокси-only путь оставлял невалидный кеш.
- Сборки: PC `pc/build-debug-271074/win-unpacked/SilentVPN-Admin.bat`; Android `android/SilentVPN-debug.apk`.

### 2026-08-16 — PC: залипание «VPN активен» + Android змейка 1–2 оборота

- **PC:** после неудачного/отменённого connect UI оставался «вкл», меню писало «Переключение недоступно: VPN активен». Тумблер нельзя было нажать во время «Подключение…». Теперь: выкл работает и во время connect; меню лочится только если туннель реально готов; stale `vpn-ready` после выкл игнорируется.
- **Android:** до старта VPN ждался `refreshWifiSubscriptionProfile` — змейка 6–10 оборотов. Профиль ушёл в фон; WG из кеша поднимается сразу. Цель — 1–2 оборота как 1.0.160.
- Сборки: PC `pc/build-debug-564328/win-unpacked/SilentVPN-Admin.bat`; Android `android/SilentVPN-debug.apk`.

### 2026-08-16 — PC: выкл/смена 3→2 + Android скорость как 1.0.160

- **PC:** выключение сначала ждало `notifyDisconnect` (API), и только потом гасило WG. Новое включение стартовало поверх живого туннеля, а поздний `vpnDisconnect` снимал уже новый `wg-turn` (bypass снят, peer соты 3 при выборе 2, 0 МБ). Теперь: WG гасится сразу; отложенный disconnect не убивает новый connect (`disconnectToken` + `vpnConnectSeq`); смена peer не возвращает `alreadyActive`.
- **PC UI:** GET `/api/vpn/servers` больше не откатывает локальный слот — «Сервер 1» не прыгал обратно на 2/3. Кеш WG не переклеивается на чужой слот.
- **Android:** снова ранний WG из слот-совпадающего API/кеша (как 1.0.160), без ожидания GETCONF 22 с. GETCONF upgrade без DOWN/UP при тех же ключах. IPv6 в WG не возвращали.
- Сборки: PC `pc/build-debug-560830/win-unpacked/SilentVPN-Admin.bat`; Android `android/SilentVPN-debug.apk`.

### 2026-08-16 — PC 0 МБ после reconnect + Android KeyFormatException

- **PC:** фоновый `/uninstalltunnelservice` прошлого disconnect снимал уже новый `wg-turn` (cap ожидания 1.5с). 63 воркера, 0 МБ, Tunnel API timeout. Connect теперь ждёт полный stop; uninstall не стартует после нового connect.
- **Android:** IPv6 в WG-конфиге давал `KeyFormatException` и «двойное» (кеш → ошибка → GETCONF). Откат к пути 1.0.160: только IPv4 AllowedIPs, битый кеш не роняет сессию.
- Сборки: PC `pc/build-debug-152964/win-unpacked/SilentVPN-Admin.bat`; Android `android/SilentVPN-debug.apk`.

### 2026-08-16 — Соты: tunnel API + Android IPv6 leak (страна РФ на Улье)

- На сотах `10.66.66.1` висел на `lo` без слушателя :8000 → клиентский `ECONNREFUSED`, ConfigSync уходил на публичный IP Улья (в логе «ошибки главного улья» при работе на соте).
- На сотах: `10.66.66.1/32` на lo + `socat` `silent-tunnel-api-proxy` → Улей `:8000`. Provision обновлён.
- Android LTE: IPv4 через WG, IPv6 мог идти мимо туннеля. Попытка `::/0` в WG откатана (KeyFormatException) — см. запись выше.

### 2026-08-16 — Улей (Сервер 1): двойное подключение + страна Россия

- **PC:** после быстрого disconnect фоновый `Disable-NetAdapter` догонял уже готовый туннель; leftover `olcrtc` слал `vpn-stopped`; Windows `syncconf` при смене сота→Улей **не меняет PublicKey** → `10.66.66.1` timeout и leak (гео РФ при IP NL).
- Фикс: поколение `wgApplyEpoch` отменяет stale stop; syncconf только если ключи/peer те же; `vpn-stopped` не сбрасывает UI если туннель жив; olcrtc-dead не трогает WDTT.
- **Android LTE:** подъём WG на Улье (peer=API IP) давал `internet_restored` / network recovery → повторный DOWN/UP. 15с settle без reapply; `internet_restored` не обходит grace, если VPN не был на паузе.
- Сборки: PC `pc/build-debug-839570/win-unpacked/SilentVPN-Admin.bat`; Android `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`.

### 2026-08-15 — PC смена сервера без ожидания teardown + Android LTE без overlay

- PC: меню сервера лочилось по `vpnIsReady` пока WG ещё умирал. Теперь лок только пока тумблер ON — после выкл слот можно сменить сразу.
- Android LTE (ADB Vivo LTE): туннель Сота 2 поднимался за 3с, затем overlay заново рвал WG и 12с+ долбился в `10.66.66.1` — «двойное подключение» и интернет через ~2 мин.
- Фикс: LTE API через TunnelApiProxy (bind к VPN), без overlay-рестарта WG. На сотах DNAT `10.66.66.1:8000` → Улей подтверждён.
- PC debug пересобран; Android debug APK пересобран.

### 2026-08-15 — Выбор сервера: слоты по Соте, не по индексу + LTE как 1.0.160

- **Корень «всегда Улей / всегда Сота 3»:** `resolve_manual_server_cell` брал `entries[i]` по всем worker-сотам и писал в БД `queen`/`cell:uuid`. Login без `preferred_server` затирал слот пустой строкой → Улей. Лишние соты сдвигали Сервер 2/3.
- **Фикс backend:** Сервер 1 = Улей, 2 = Сота 1 (номер в имени), 3 = Сота 2. В `Device.preferred_server` и `selected_server` только `server1/2/3`. Login/register не затирают слот пустой строкой.
- **Android vs 1.0.160:** на LTE больше не стартует ephemeral bootstrap (~2 мин) до публичного `register/getConfig`. Кеш WG используется только если слот совпадает с выбранным сервером.
- **PC:** то же правило кеша; debug пересобран после фикса.
- Деплой: `python scripts/deploy_hive.py` из `backend/` (первый прогон не рестартнул API из‑за ro `cell-agent`; API/nginx перезапущены отдельно, health 200, `MANUAL_SERVER_SLOTS` в процессе).
- PC debug: `pc/build-debug-435827/win-unpacked/SilentVPN-Admin.bat`
- Android debug APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`

### 2026-08-15 — VK-only: вынос olcrtc из активных точек + деплой

- По запросу пользователя «полностью и деплой» вычищены активные точки `olcrtc`:
  - backend `app/api/vpn.py`: удалены публичные `olcrtc*` endpoint'ы (`/olcrtc-config`, `/olcrtc2-config`, heartbeat/failure routes);
  - admin-ui: удалён `Olcrtc2Panel`, `BypassPage` переведён в VK-only, из `HivePage` убраны `olcrtc`-подписи/бейджи;
  - Android: `MenuBypassScreen.kt` переписан в чистый VK/WDTT экран (режим VK + динамический выбор сервера через `/api/vpn/servers`), без `olcrtc`-switch/leave/reset логики.
- Проверки локально:
  - `backend`: `python -m compileall app/main.py app/api/vpn.py` — OK;
  - `backend/admin-ui`: `npm run build` — OK;
  - `android/app`: `.\gradlew.bat compileDebugKotlin` — OK;
  - `pc`: `npm run build:renderer` — OK.
- Прод деплой:
  - `python scripts/deploy_stable.py`;
  - затем ручной `docker compose restart api nginx` на VPS (чтобы контейнер подхватил свежие роуты).
- Пост-проверка прода:
  - `GET /api/health` → `200`;
  - `GET /api/vpn/olcrtc-config` → `404`;
  - `GET /api/vpn/olcrtc2-config` → `404`;
  - `GET /api/vpn/servers` → `401` (роут жив, нужна авторизация).

### 2026-08-15 — hotfix после регрессии: Android не включает VPN + серверы 1/2/3

- Причина регрессии совместимости: часть старых клиентов/потоков всё ещё обращается к `olcrtc*` API; после полного удаления роутов получали `404`.
- Фикс backend (`app/api/vpn.py`): возвращены совместимые endpoint'ы
  - `GET /api/vpn/olcrtc-config`, `GET /api/vpn/olcrtc2-config` → `200` с disabled payload;
  - heartbeat/failure `POST /api/vpn/olcrtc*` и `POST /api/vpn/olcrtc2*` → `{"ok": true, "disabled": true}`.
- UI на клиентах переведён в «Выбор сервера»:
  - Android: `MenuBypassScreen.kt` + `MainScreen.kt` — выбор только `Сервер 1/2/3`, без UI «вариантов обхода»;
  - PC: `MenuBypassPanel.tsx`, `MainScreen.tsx`, `bypassStore.ts` — аналогично `Сервер 1/2/3`.
- Дополнительно для жалоб по Discord: в `scripts/deploy_threat_dns.py` добавлен allowlist `discord*` доменов.
- Проверки:
  - `android/app`: `.\gradlew.bat compileDebugKotlin` — OK;
  - `pc`: `npm run build:renderer` — OK;
  - `backend`: `python -m compileall app/api/vpn.py` — OK.
- Деплой и валидация:
  - `python scripts/deploy_api.py` (после `deploy_stable.py`) — обновление API в контейнере;
  - прод-check: `GET /api/vpn/olcrtc-config` = `200`, `GET /api/vpn/olcrtc2-config` = `200`, `GET /api/health` = `200`;
  - `python scripts/deploy_threat_dns.py` применён (на момент прогона `threat_filter enabled=false`, DNAT off).

### 2026-08-14 — ADB: первая прогрузка TM Android ~20с

- Устройство: Vivo V2520A (`10AFB105UN003QC`), не Memu.
- Лог: `15:59:01` prefetch CONN_FILE → `waiting peer 5s/15s` → `15:59:21` `subscriber media timeout` / code=1. ICE не было.
- Корень: диск `telemost-conn.json` **не** сбрасывался на fail (`shouldInvalidatePrefetchOnStop=false`) → повтор на том же guest token.
- Фикс: wipe CONN_FILE на early fail/media_timeout; Telemost wait SOCKS **12с** (не 90). APK обновлён.

### 2026-08-14 — Telemost Wi‑Fi старт >30с (не «мало комнат»)

- **Корень 1 (API):** warm/sticky claim делал HTTP carrier-probe Telemost (до 12с); pool требовал `carrier is True` → при `?` шли в on-demand provision (~20с+settle). Логи: частые `provisioned`/`on-demand` вместо pool hit.
- **Корень 2 (клиент):** ждали ICE до **25с** до tunnelReady + PC cleanup sleeps 600+700мс.
- **Фикс:** TM assign без carrier HTTP (unit active достаточно; WB probe остаётся); ICE wait TM **8с**; PC sleeps 250мс.
- Сборки: PC `build-debug-496328`; Android `assembleDebug` → `SilentVPN-debug.apk`. API задеплоен.

### 2026-08-14 — PC «SOCKS не поднялся» после warm TM=0

- **Корень:** PC connect = cache-only; после prune/warm=0 кеш указывал на мёртвую комнату → CNC не слушает SOCKS.
- **Фикс сервер:** Telemost warm снова **1/dt** (pc+android = 2 unit); агент поднимает с 0→1; on-demand assign проверяет `ensure_unit_ready`.
- **Фикс PC:** при SOCKS/peer fail → `reportOlcrtcRoomFailure` + один retry с новой комнатой.
- Сборка: `pc/build-debug-144543/win-unpacked/SilentVPN-Admin.bat`.

### 2026-08-14 — Сота 1 idle CPU: warm Telemost = 0

- **Симптом:** 4 vCPU / ~4 GiB, мало комнат, 0 живых TM-клиентов, CPU всё равно 20–50%.
- **Корень:** idle `olcrtc2-srv` (warm SFU Telemost) жрёт ~15–25% **на каждую** комнату без VPN-клиентов; плюс steal гипервизора до ~27%. Не Playwright и не «хвост» от 2 пробных коннектов.
- **Фикс:** `TELEMOST_WARM_PER_DT_CAP=1`, default `warm_pool_by_provider.telemost=0` (create on assign); prune сорвал все TM unit на Соте 1 → **olcrtc2_running=0, CPU ~0% idle**.
- **Цена:** первый Telemost-коннект без warm чуть дольше (создание комнаты). WB warm на Соте 2 без изменений (2/dt).
- Деплой: `olcrtc2_settings.py` + `olcrtc2_room_agent.py` + restart api.

### 2026-08-14 — Cold start Telemost: кеш CONN_FILE + меньше ожиданий

- Главный тормоз: `hardReset(before_start)` стирал OkHttp CONN_FILE → каждый тумблер = полный Yandex auth.
- Теперь prefetch живёт 4 мин (RAM+диск); DNS resolve параллельно; слипы hardReset только если был native; UI poll 200мс до ready.
- PC: disk hit для telemost-conn.json; sleep после sing-box 600→200; один фоновый warm `i.ytimg.com` после ready (не блокирует).

### 2026-08-14 — Убрали gstatic-пробы на старте olcrtc (Android+PC)

- Зачем были: «peer жив?» до открытия TUN и периодический health.
- На Telemost каждый dial к `www.gstatic.com` крадёт vp8 и даёт 2–4с на fail → долгая первая загрузка.
- Теперь старт ждёт **ICE/peer latched** из логов; один dial только fallback. Health gstatic на PC тоже off (как Android).
- Остаются: SOCKS listen; HB через SOCKS; TelegramPathWarmup только для **VK/WDTT**, не olcrtc; PC `warmupBrowsingPath` только VK.

### 2026-08-14 — Анализ: обрывы TM + медленный Android cold start

- Сота 1/2 после апгрейда: **4 vCPU / 3.8 GiB**, BBR+fq, steal ~0–2%. Egress YouTube TTFB ~0.16с — канал соты не «мёртвый».
- Сота 1 под живыми TM: load ~2.5, каждый `olcrtc2` ~15–25% CPU — норма для vp8 encode, не квота 50%.
- Обрывы «то да то нет»: в основном клиент (leftover hardReset / onDestroy / wipe кеша) — уже пофикшено; краткие фризы — ICE reconnect Telemost (18с grace), не смена комнаты.
- Android первая загрузка дольше PC: cold path OkHttp+CONN_FILE+ICE+hev+excludeRoute, потом первый CDN через узкий vp8. После прогрева «более-менее» — ожидаемо. Потолок TM ≠ WDTT/WB.

### 2026-08-14 — Android: Telemost убивался onDestroy, кеш комнаты стирался

- Лог TM: комната есть, ICE connected, затем `hardReset: vpn_onDestroy` ×4 и `code=1`. WB→TM «нет конфига», TM не встаёт даже после VK/рестарта.
- Причина: на каждый connect копились коллекторы `lastError` → disconnect; stale `OlcrtcVpnService.onDestroy` убивал новый старт; `code=1` после нашего kill вызывал `reportOlcrtcRoomFailure` и **стирал слот Телемоста**.
- Фикс: один watch-job; onDestroy/STOP игнорируют более новый epoch; leftover hardReset только если VpnService уже мёртв; первый `code=1` — повтор той же комнаты без wipe.

### 2026-08-14 — Android: один путь смены канала, без «ждём конфиг»

- Переключение WB↔TM↔VK шло двумя путями: тумблер гасил VpnService **без** `hardReset` native/hev, Apply ещё и ждал fetch («Получение сессии…»). leftover WB накладывался на Телемост → «нет конфига», затем вылет на VK (DISCONNECT мёртвого FGS).
- **Один путь:** радио можно выбрать при живом VPN; Apply — cache-only (слоты с login и с включённого VK), leave + `hardReset`, DISCONNECT только если сервис жив. Тумблер OFF тоже сносит leftover.
- ICE `Failed to find pair for add binding` — шум pion (IPv4 srflx vs пустой IPv6 related), не красная ошибка. Туннель при этом живой.
- PC: диалог Apply больше не показывает «Ждём конфиг канала…».

### 2026-08-14 — Android: reconnect Телемоста; PC тумблер как Android

- После выкл. тумблера на TM старый worker `waitForSocksDial` делал `hardReset(start_failed)` и убивал **новый** процесс → вечное «Подключение» / «SOCKS слушает, peer не отвечает». Лечится только kill app. Теперь epoch: старый worker не трогает новый connect; ждём свободный :8808.
- PC: сразу ставили `connected=true` и снимали `connecting` до vpnConnect → «Подключено» пока змейка крутится, UPPERCASE текст. Как Android: серое «Подключение...» → зелёное «Подключено» когда тумблер уехал.
- Лог: каждый connect чистит панель (olcrtc тоже). Обход TM/WB/VK пишется commit/localStorage — после закрытия приложения тот же канал.
- Сборки: Android `SilentVPN-debug.apk`; PC `pc/build-debug-19811/win-unpacked/SilentVPN-Admin.bat`.

### 2026-08-14 — PC меню обхода как 1.0.160 (диалог, не футер)

- Было не то: футер «Было/Будет» + вечные кнопки + подсказка про VPN (как VkCredMode). В 160 — нижний диалог **«Применить?»** и строка **«VK → olcrtc»**.
- PC `MenuBypassPanel`: радио pending, подтверждение оверлеем как Android. Текст смены семейства `VK → olcrtc`, внутри — `Телемост → WB Stream`.
- Android: тот же короткий текст в AlertDialog (не `olcrtc / WB Stream`).
- PC debug: `pc/build-debug-507804/win-unpacked/SilentVPN-Admin.bat`.

### 2026-08-14 — PC VK: тумблер снова сразу ON (как 1.0.160)

- После серого «Подключение...» UI ждал `waitVpnReady` (WG + воркер) → 5–8 с на VK. В 160: `setConnected(true)` сразу, prepare/воркеры в фоне.
- Вернул: тумблер и «Подключено» сразу; `waitVpnReady` только проверяет туннель и при фейле откатывает. Краткий restart wdtt не гасит UI (`connectInFlightRef`).
- PC debug: `pc/build-debug-552402/win-unpacked/SilentVPN-Admin.bat`.

### 2026-08-14 — PC: змейка 1.5 оборота + диалог обхода как Android 160

- Змейка: vpnConnect сразу, UI «Подключение...» минимум **1.5 оборота** (`SNAKE_MIN_VISIBLE_MS`), потом бегунок ON и «Подключено». Не ждать воркер.
- Обход: в 160 это **Material AlertDialog** по центру (скругление 28, поля по бокам), не нижний шит на всю ширину и не дерево с вертикальной чертой. Радио 20px, вложенность `padding 12`, щель 8px между VK и olcrtc.
- PC debug: `pc/build-debug-235620/win-unpacked/SilentVPN-Admin.bat`.

### 2026-08-14 — Сота 2: тот же CPUQuota 50%, канал ещё лучше

- WB-сота `78.17.74.27`: YouTube ~15 мс, Cloudflare 20 МБ ≈ **67 МБ/с (~540 Мбит)**, steal **0%**, load 0.2. Интернет в порядке.
- Был тот же шаблон: `CPUQuota=50%` / `MemoryMax=512M` на всех `olcrtc2@`. Снято без рестарта (7 живых → infinity / 1G), BBR+fq, `tcp_slow_start_after_idle=0`. cell-agent обновлён.
- 5 старых unit в `failed` (не running) — на трафик не влияют.

### 2026-08-14 — Сота 1: интернет ок, резали CPUQuota 50%

- Egress живой: YouTube TCP ~27мс / TTFB 0.19с, Cloudflare 20 МБ ≈ **40 МБ/с (~320 Мбит)**. Канал соты не «плохой».
- Резали **каждому** `olcrtc2@` `CPUQuota=50%` (пол-ядра) при 5 процессах на **2 vCPU** + steal ~10–13% (гипервизор). vp8 упирался в квоту → секундные подвисания как «обрыв».
- Снято без рестарта сессий: `CPUQuota=infinity`, `MemoryMax=1G`, BBR+fq, `tcp_slow_start_after_idle=0`, буферы/backlog. Шаблон unit + cell-agent, чтобы apply снова не ставил 50%.
- Потолок Телемоста (vp8 / SFU) никуда не делся — это не WDTT.

### 2026-08-14 — Android: подвисание Телемоста + «нет конфига» TM→WB + вылет на VK

- **Подвисание на несколько секунд (видео / Telegram «соединение»):** не смена комнаты. На узком Telemost/vp8 клиент сам делал SOCKS-пробы к gstatic (health watch, liveness suspect, watchdog) — они крали полосу. Пробы при живом туннеле выключены; native ICE-reconnect Telemost всё ещё может дать короткий буфер.
- **TM→WB «нет конфига»:** Apply был cache-only. Слот WB часто пуст (prefetch только login/VK). Теперь Применить само fetch’ит пустые слоты (TM и WB), соседний не затирается.
- **Вылет при включении VK:** leftover `libolcrtc2`/hev + `startForegroundService(DISCONNECT)` при уже выключенном VPN. Теперь hardReset + `startService`, DISCONNECT только если сервис ещё жив.
- Debug APK: пересборка `SilentVPN-debug.apk`.

### 2026-08-14 — Android hang: не рвать комнату; WDTT-баланс мимо Сота 1/2

- **Почему рвало:** olcrtc2-srv закрывает сессию по control liveness (~4 мин missed pong) и **сам reconnect**. Android делал hardReset + новый assign → минута «зависло». Теперь glitch (stream_dead/peer_closed/SOCKS) **не** рестартит процесс и **не** меняет комнату. Рестарт только если native умер (`process_exit`).
- **Балансир:** вчерашнего исключения Сота 1/2 из WDTT **не было** — `pick_cell` брал все active. Теперь Сота 1 (`87.58…`) и 2 (`78.17…`) `accepts_wdtt=false`; spill только на 3, 4, … (если нет — Улей). Админка: бейдж «olcrtc — не WDTT-баланс».
- Деплой `deploy_api.py`. Debug APK: `SilentVPN-debug.apk`.

### 2026-08-14 — Сота 1 100% CPU + Android WB hang ~1 мин

- **Не max_clients=1.** После `deploy_api` агент снова делал `warm<12 → 20`. На проде было **76 комнат / 2 сессии**: TM 19+20 на Соте 1, WB 17+20 на Соте 2.
- Срезали: cap TM warm=2 / WB=3; агент больше не раздувает до 20; excess idle tear 90с (не 15 мин). Prune: **73→11** (TM 2+2, WB 3+4).
- Android Wi‑Fi: srv `session close reason=liveness duration=4m2s`, клиент ждал новый канал **60с**. Теперь первый stream_dead/peer_closed — та же комната; reassign timeout 20с; grace 18с.
- Деплой `deploy_api.py` + `prune_olcrtc2_warm.py`. Debug APK — пересборка.

### 2026-08-14 — olcrtc стабильность A–D (код + деплой API)

План: `.cursor/PLAN_OLCRTC_STABILITY.md`. **Не release** — debug-сборки PC/Android.

- **A.** PC `MenuBypassPanel`: pending + «Применить»/«Отмена» внизу (как 1.0.160 / `MenuVkCredModePanel`). Цвета из темы.
- **B.** `TELEMOST_MAX_CLIENTS=1` (как WB); assign только empty (`stickies==0`). Heal-скрипты больше не ставят 3/25. Прод: `deploy_api.py` + `heal_olcrtc2_max_by_provider.py` → все active rooms max=1 (TM pc/android 8+8, WB 2+2).
- **C.** Dual-cache изолирован (PC `olcrtcCachePolicy.mjs`, Android `isolateProviderKeysForCache`). PC `tunnel-api-request`: olcrtc2 timeout 90с, **без** public fallback при живом WG. Android: tunnel fail / LTE → не public. Prefetch не refresh’ит живой слот.
- **D.** PC HB/leave/failure через SOCKS `10.66.66.1:8000`; `missed_pong` не убивает без SOCKS streak (2/3). Android `SOCKS_API_FAIL_SUSPECT_STREAK=3`. lastFailed room не стартуем. Endurance 40 мин — вручную.

Тесты: backend `test_olcrtc2_session_rules_unit.py` 5/5; PC `npm test` 41/41; Android `OlcrtcSessionPolicyTest` BUILD SUCCESSFUL.

### 2026-08-14 — ПЛАН: olcrtc стабильность (комнаты / конфиги / меню PC)

Заказчик: улучшать olcrtc. Код **не начинать** без команды. Полный план: `.cursor/PLAN_OLCRTC_STABILITY.md`.

**1. Комнаты отваливаются (WB / Телемост)**  
Корень: Telemost `max_clients=3` (shared vp8); WB уже 1. HB на БС уходит в public/underlying → sticky stale → prune. Ложный `/olcrtc2-room-failure` teardown. Кеш мёртвой room.  
Канон: **1 fp = 1 комната**, leave=soft sticky (не session-mode teardown 11.08), failure=teardown только этой room.

**2. Конфиги затираются / не доезжают**  
ПК Wi‑Fi без БС — ок. Android Wi‑Fi ок; **LTE почти всегда белые списки** → до Улья только VPN `10.66.66.1`.  
Корень: PC `tunnel-api-request` режет timeout до 8с и падает в nip.io (второй assign затирает живую room). Android public fallback на LTE. `saveOlcrtcCache` может писать чужой слот. prefetchBoth refresh’ит живые слоты.  
Канон: LTE/БС = только tunnel; dual-cache изолирован; denied не писать в кеш.

**3. Меню обхода PC**  
Сейчас Apply сразу по клику. Нужно как 1.0.160 / `MenuVkCredModePanel`: pending + **«Применить» внизу**.

Порядок фаз: A меню PC → B max_clients=1 + heal БД → C доставка конфигов PC/Android → D liveness/endurance.

### 2026-07-27 — olcrtc bypass в release 1.0.160 (PC + Android)

- Меню «Варианты обхода» (VK / olcrtc + Telemost|WB) доступно в release, не только debug.
- Сняты гейты `BuildConfig.DEBUG` / `isDebugBuild` на family/provider/connect/prefetch; DNS и хеши остались debug.
- Версии: Android `versionCode/Name 160` / `1.0.160`; PC `package.json 1.0.160`.
- Релизы: `assembleRelease` + `build-installer.bat` OK. Push `android` + `pc`.

### 2026-08-13 — Android: нет логов / не коннектится после reinstall

- Bypass сбрасывался на WDTT → тишина в SVPN_OLC. Debug дефолт → olcrtc2.
- API был `https://132.243.234.162` (TLS hang); → nip.io + migrate prefs.
- `olcrtc2-config` bind на первый LTE при Wi‑Fi → hang; prefer Wi‑Fi/Ethernet.
- Ephemeral на Wi‑Fi скипался из‑за «users/me OK»; для assign всегда пробуем.
- APK установлен; ICE connected / connect path ожил.

### 2026-08-13 — Android: cold-start olcrtc без re-login

- После reinstall кеш olcrtc пуст; assign раньше только на login → «выйти/зайти». Живую WB-room вшить нельзя (404).
- Фикс: при старте сессии auto-warm Telemost+WB (как login); connect cache-miss без 120с public hang; Wi‑Fi probe 12/20с → ephemeral VK.
- APK: `SilentVPN-debug.apk`.

### 2026-08-13 — Android «через раз»: reassign timeout 2.5с → WB 404

- Лог: peer suspect/dead (socks_api_fail) сработал; recover с `withTimeout(2500)` → stale room `svpn_8fa7…` → join 404.
- Фикс: reassign timeout 60с; peer_dead всегда refresh (в т.ч. LTE); не стартовать ту же room; без cache-fallback после failure.
- PC green hang: UI жив, cnc/TUN нет с ~16:11, sticky HB по public — выкл/вкл; нужен socks-liveness как на Android.
- APK: `SilentVPN-debug.apk` (установлен). Watch: `phone_watch_20260813-164816/`.

### 2026-08-13 — Android green hang: SOCKS/sid fail → reassign

- После ready ~1–2 мин: flood `remote not ready` / sid timeout при редких `tunnel to`; HB уходил на Wi‑Fi (`OK via default`) → UI зелёный, сайты нет.
- Фикс: `streamDeadStreak` не сбрасывать на `tunnel to`; после 3 → suspect, после 6 → `peer_dead`; `noteSocksPathFail` с HB; online=true не через underlying при ready; watchdog probe при suspect.
- APK поставлен: `SilentVPN-debug.apk` на телефон.

### 2026-08-13 — TM idle тяжелее WB; warm→2; endurance 60м

- Сота1: idle Telemost unit ≈ 6–13% CPU (Yandex SFU) → 50–60% при 8 warm без клиентов.
- Сота2: idle WB ≈ 2–3% → при сессии ~15–25% норма. Не «неровные комнаты», разная цена unit.
- `warm_pool_per_dt=2` (по 2 free на dt); sticky/busy сохранены. Endurance WB 60м запущен.

### 2026-08-13 — warm shrink: CPU Сота1 без «нет комнат»

- `warm_pool_per_dt=4` (уже было 4 после агента; раньше раздувало до ~20→40+ unit).
- Срезано 7 лишних free (6 telemost android + 1 wb pc); sticky/online не трогали.
- Итог: 16 комнат = по 4 free на каждый `provider:dt` (TM pc/android + WB pc/android).
- Сота1: olcrtc 40→8, load ~60→~8 (остывает). Запас Connect сохранён.

### 2026-08-13 — endurance WB 40м: peer не умер

- Отчёт: `backend/scripts/reports/endurance_olcrtc2_20260813-143623/summary.json`
- PC ~2379с SOCKS 155/0 HB 77/2; Android ~2379с SOCKS 152/3 HB 79/0.
- `dead_reason=process_exit:1` в конце лимита скрипта (не mid-run peer death).
- Вывод: голый olcrtc2-cnc на Wi‑Fi держит WB ~40м; старые обрывы 2–15м — скорее клиент/heal/LTE, не «WB всегда падает».

### 2026-08-13 — Сота 1 ~100% CPU при тесте WB на Соте 2

- Hive: Сота1 CPU **100%** (load ~60 на 2 ядрах), Сота2 **~76%** (load ~6), TX ~32 Mbps — живой WB.
- Причина Сота1: **~40 warm `olcrtc2-srv` Telemost** (unit’ы active), sticky Telemost=0; клиенты WB на Соте2 не при чём.
- В БД: 40 telemost + 43 wbstream rooms; sticky только WB (2 pc + 2 android).
- WDTT online на сотах = 0 (olcrtc не считается hive VPN); Улей ~102 WDTT, `wdtt-server` ~118% CPU.

### 2026-08-13 — Android LTE HB: NetworkOnMainThread + nip.io

- Лог: `socks CONNECT fail host=132.243.234.162:443` при живом VPN — SOCKS с Main → NOTM / битый IP Host.
- Фикс: HB/leave/failure SOCKS на `Dispatchers.IO`; CONNECT+SNI всегда `132-243-234-162.nip.io`; IPv4 ATYP в SOCKS.
- APK: `SilentVPN-debug.apk` — ждать `heartbeat OK via socks`, online=4.

### 2026-08-13 — Android LTE: heartbeat через SOCKS (whitelist)

- App в disallow → HB в underlying → nip.io режется БС на LTE → sticky нет → телефон не в сессиях.
- VPN `Network.bind`/`socketFactory` для excluded app → EPERM (не работает).
- Фикс: `POST /olcrtc2-heartbeat` (и leave/failure) через локальный SOCKS `127.0.0.1:8808` → peer → exit → nip.io.
- `OlcrtcTunnelManager.openSocksTcp` + `activeSocksEndpoint`; APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`.

### 2026-08-13 — endurance script PC+Android до смерти peer

- `backend/scripts/endurance_olcrtc2_clients.py` — 2× olcrtc2-cnc (pc/android), HB + SOCKS probe, лог до exit/socks_fail.
- Запуск: `cd backend; python scripts/endurance_olcrtc2_clients.py --minutes 40`
- `--hb-via-socks` — HB как LTE через SOCKS. Отчёт: `scripts/reports/endurance_olcrtc2_*`.

### 2026-08-13 — админка: вход сбрасывался (NameError в /stats)

- В `get_stats` после правки online пропал `user_devices = …` → NameError → HTTP 500 → UI снимал `admin_token`.
- Фикс задеплоен (`deploy_admin_stats_fix.py`).

### 2026-08-13 — online=1 при 2×WB + смерть ~2 мин (warm heal)

- Online в админке = sticky-сессии (+ Device по sticky fp); не только wdtt `is_connected`.
- Warm heal: не tear WB по carrier; keep recent-healthy без sticky.
- Android HB через underlying (не VPN), интервал 30с.
- Деплой API + APK `SilentVPN-debug.apk`.

### 2026-08-13 — push: olcrtc2 за 2 дня (main + pc + android)

- `main` `0a8976f` — pool/agent/admin/WB max_clients=1/warm scale
- `pc` `8679c13` — olcrtc2 session, hosts-only guest, missed_pong liveness
- `android` `28997f1` — TUN CIDR, liveness suspect, bypass menu

### 2026-08-13 — Android WB: ICE/TURN в hev (CIDR exclude)

- PC жил 6–9+ мин; Android: TURN `185.62.200.94` → ICE closed → handshake fail → exit 143 → hardReset spam.
- Причина: exclude только hostname `stream.wb.ru` (часто `185.62.202.8`), не весь `185.62.192.0/18` как на PC sing-box.
- Фикс: hev TUN `excludeCidrRoutes` WB `185.62.192.0/18` + TM `37.9.0.0/16`; hosts rtc-el-*; STATIC_HOSTS /32; mute x509/TURN noise; grace на handshake reconnect fail.
- APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`.

### 2026-08-13 — PC+Android «зелёный вис» (missed_pong / stream_dead)

- PC ~15 мин + Android ~1 мин → оба повисли; PC: `control missed pong` → socks_health_fail. Комнаты разные (не один WB room).
- Баг клиента: `missed_pong` только логировался; health/grace пропускались из‑за «recent traffic» / fake SOCKS → UI зелёный, sticky не сбрасывался (Android снова `svpn_a44a…`).
- Фикс PC+Android: `peerLivenessSuspect` → force SOCKS dial, grace 8с, stream_dead streak; тест forceLivenessCheck.
- Сборки: `SilentVPN-debug.apk` + `pc/build-debug-744175/win-unpacked/SilentVPN-Admin.bat`.

### 2026-08-12 — olcrtc2 был ВЫКЛ + кеш мёртвых комнат (WB 404 / TM code=1)

- Диагностика: `enabled: false` (после 500 в админке Save с дефолтом выкл). Клиент брал stale cache → WB join 404 / Telemost exit до SOCKS. Комнат из лога в БД уже нет.
- Включил продукт + heal пула; leave снова teardown; assign только при carrier=True; клиент без cache-fallback, кеш v15.
- Админка: Save запрещён пока load не OK (нельзя случайно выключить).
- APK: `SilentVPN-debug.apk`. В админке должно быть «Включён» + цифры Warm.

### 2026-08-12 — админка olcrtc2 HTTP 500 (пул «—», ключ не генерится)

- Причина: битый module docstring в `olcrtc2_assign.py` после soft-leave (лишняя `"""`) → SyntaxError → `/api/admin/olcrtc2` 500.
- Фикс задеплоен (`deploy_api.py`). Обновить страницу админки → цифры пула + «Сгенерировать» ключ.

### 2026-08-13 — PC Telemost смерть ~10 мин (sticky + prune)

- Причина: `stopOlcrtcHeartbeatLoop()` всегда делал **leave** → sticky снималась; при `start` тоже leave. Agent prune (stale 180с + excess warm) **teardown** живой комнаты → peer «RTP closed».
- PC: stop без leave (leave только на disconnect); HB 30с + лог fail.
- Backend: `HEARTBEAT_STALE_SEC=300`; excess tear пропускает recent-healthy &lt;15 мин.
- Деплой API + PC debug.

### 2026-08-13 — Android Telemost fix + конфиг только login/sync

- Android Telemost: откат **mapdns** (регрессия) → снова DNS=real, IPv4-only, udp→tcp, TG via VPN.
- Конфиг olcrtc2: fetch **только** login + sync при VK; TM↔WB = dual-cache без сети.
- PC: dual-cache `v12_telemost`/`v12_wbstream`; убраны prefetch в меню/connect/live-sync loop.
- APK: пересобрать debug.

### 2026-08-13 — PC Telemost «умер» через ~9 мин + ложные ERROR

- Симптом: после tunnelReady ICE `Failed to read` / sing-box `connection … forcibly closed` → peer мрёт.
- Причина: blanket `udp→block` + `process_name` на Win без админа часто не матчит cnc → TURN refresh не проходит.
- Фикс: **direct ip_cidr** (staticHosts + conn JSON + `37.9.0.0/16` для Telemost) до UDP-block; mute ICE/RST шум; WG stop ждёт idle до olcrtc; dead-handler для olcrtc2.
- PC: пересобрать debug (`build-debug.bat`).

### 2026-08-13 — Android Telemost latency vs PC (тот же Wi‑Fi)

- PC быстрый: sing-box DNS через SOCKS + sniff(domain) + мгновенный block QUIC.
- Android был медленнее: DNS снаружи + CONNECT по IP; QUIC в TUN висел до udp-timeout.
- Фикс: **mapdns** (CONNECT по имени, как PC sniff) + `udp:tcp` timeout **150мс** + pipeline/tcp-fastopen; IPv4-only; TG via VPN.
- APK: `SilentVPN-debug.apk`. Лог: `mapdns=fake-ip (паритет PC)`, `QUIC-fastfail`.

### 2026-08-13 — PC WB TURN refresh + Android скорость как PC

- WB ~2мин: `Fail to refresh permissions` — `olcrtc2-cnc.exe` после TUN уходил в sing-box (UDP TURN мёртв). Фикс: **cnc/olcrtc → direct** в process_name.
- Android: убраны ICE settle 1.2с + pre-hev TLS 4с (на PC их нет) → ready быстрее; health с 45с; hev connect-timeout 3.5с.
- APK + PC debug пересобрать.

### 2026-08-13 — PC: ложный «туннель не поднялся» при живом olcrtc2

- Симптом: Telemost/WB работают, но alert «проверьте srv/бинарники»; в логе `socks5 code=4`.
- Корень: `isVpnReadyForUi()` смотрел только olcrtc **v1**, не olcrtc2 → `vpn-ready` не слался → `waitVpnReady` timeout.
- Фикс: ready = olcrtc2 **или** v1; mute SOCKS code=4; лог `SOCKS auth … RFC1929 → cnc + sing-box`.
- Debug: пересборка.

### 2026-08-13 — PC: лог-шум + Cursor жрал Telemost

- WB/TM работали; в логе ложные `[olcrtc2:err]` (pion INFO на stderr) + `api2.cursor.sh`×сотни через TUN → Telemost потом падал.
- Фикс: Cursor/Silent/Code → **direct** в sing-box; mute ICE/WSL/UDP noise; WB 498 = soft (Go guest сам).
- Debug: пересборка `build-debug.bat`.

### 2026-08-13 — PC: Telemost/WB timeout + меню без «Применить»

- Симптом: prefetch timeout → Go cloud-api/WB guest тоже timeout; меню с кнопкой подтверждения.
- Корень auth: остаток WG/TUN ловил HTTPS (на Android — whitelist OkHttp). Фикс: **всегда cleanupVpn** перед olcrtc; prefetch через **Electron net.fetch** + IPv4 fallback.
- Меню: выбор применяется сразу (без кнопки/диалога); при живом VPN — стоп → смена.
- Debug: пересобрать `build-debug.bat`.

### 2026-08-13 — PC olcrtc2: паритет с Android (не «один сервер»)

- `olcrtc2Session.js` был упрощённый: SOCKS port → сразу sing-box, без dial, без UDP/QUIC block, без Telemost prefetch.
- Как Android/v1: ipv4_only + DNS TCP без fake-ip; block UDP/QUIC; waitForSocksDial до TUN; Telemost/WB CONN_FILE + STATIC_HOSTS; forceKill; soft post-TUN.
- Debug: `pc/build-debug.bat` → `build-debug-*/win-unpacked`.

### 2026-08-13 — оба через VPN (YT+TG), без выкидывания Telegram

- Пользователь: Telegram тоже должен идти через VPN — иначе смысл обхода.
- Вернул профиль «оба более-менее жили»: `Telegram via VPN`, IPv4-only, mapdns off, udp→tcp, pre-hev TLS, без ::/0/hev-ipv6 и без disallow TG.
- APK: `SilentVPN-debug.apk`. Лог: `Telegram via VPN`, `tgVia=vpn`, `pre-hev CONNECT+TLS`, `tunnelReady`.

### 2026-08-13 — откат к лучшему рабочему (как 1.0.160 + TG вне TM)

- IPv6 sink / hev-ipv6 / TG-via-VPN на TM ломали YouTube и давали exit 141.
- Вернул профиль **160**: mapdns fake-ip + IPv4-only `allowFamily`, ICE settle 4с на TM, soft post-hev (без hard-fail).
- Telemost: **Telegram вне TUN** (`tgVia=direct`); WB: TG через VPN.
- APK: `SilentVPN-debug.apk`. Лог: `mapdns=fake-ip (как 160)`, `tgVia=direct`, `tunnelReady`.

### 2026-08-13 — IPv6 sink ломал Telemost (exit 141)

- Симптом: `SOCKS мёртв сразу после hev`, `exit code=141`, `vpn_onDestroy`×N, YT мёртв, вкл нестабильно.
- Причина: `::/0` без hev-ipv6 глотал **AAAA TURN/STUN Telemost** → ICE в чёрную дыру → peer/SIGPIPE.
- hev-ipv6 раньше забивал vp8 (YT мёртв). Откат на **IPv4-only + allowFamily(AF_INET)** (как 160): ICE на LTE AAAA жив, трафик сайтов IPv4 через hev.
- Tradeoff: возможны серые ~HE при reopen YT (AAAA→LTE). Стабильность важнее.
- APK: `SilentVPN-debug.apk`. Лог: `IPv4-only (allowFamily…`.

### 2026-08-13 — серые экраны при КАЖДОМ открытии YT (VPN жив)

- Симптом: зашёл в YT → ~10с серое; вышел и снова → опять серое; VPN не рвался. То же TG.
- Это не cold-start SFU: `allowFamily(AF_INET)` пускал **AAAA на LTE** → Happy Eyeballs таймаут при каждом старте приложения, потом IPv4 через VPN.
- Фикс: IPv6 в hev (`ipv6` + `::/0`), убран allowFamily; убран бесполезный app-heat.
- APK: `SilentVPN-debug.apk`. Лог: `IPv4+IPv6 via hev`, `no AAAA→LTE`.

### 2026-08-13 — задержка TG/YT = первый CONNECT после hev

- Не «магия канала»: после TUN первый SOCKS CONNECT (SFU data-path + TG DC / ytimg) долгий → часики в приложениях.
- Фикс UX: `heatAppsBeforeReady` (ytimg + api.telegram.org + DC) **после hev, до tunnelReady** — ждём на тумблере ~2–4с, открытие TG/YT уже тёплое. Без фонового flood.
- APK: `SilentVPN-debug.apk`. Лог: `app-heat N/3 …ms (ytimg+tg до ready)`.

### 2026-08-13 — TM≠WB носитель: goolom vs livekit

- Пользователь прав: один `libolcrtc2`/`vp8channel`, но **разный SFU**: Telemost=`goolom` (Яндекс), WB=`livekit` (WB stream) + разные соты. WB шире по медиатрубе — отсюда быстрые TG+YT на WB.
- Клиент больше не режет TM отдельно (warm skip / idle flood / частый health) — старт как у WB: warm pre-TUN + тот же settle/health.
- Пул: TM `max_clients=3`, WB `25` (на одного юзера не влияет). Дальше ускорять TM = носитель/сота, не «ещё warm».
- APK: `SilentVPN-debug.apk`.

### 2026-08-13 — откат агрессивного bg warm (YT ещё медленнее)

- 5× YouTube TLS + 5× TG DC сразу после ready забивали Telemost/vp8 → YouTube дольше, TG без пользы.
- Фикс: убран flood; pre-hev только gstatic; idle warm 1× ytimg + 1× api.telegram.org через 1.8с и только если канал свободен.
- APK: `SilentVPN-debug.apk`.

### 2026-08-13 — Telemost: серый YT ~5с + TG часики 10–15с

- После ready канал холодный (`warm skip`): первый YouTube CDN и первый TG DC через vp8 долго.
- Фикс: фоновый `startPostReadyWarm` сразу после tunnelReady (ytimg/ggpht/youtubei + api.telegram.org/DC) — тумблер не ждёт; hev connect-timeout 5с.
- APK: `SilentVPN-debug.apk`. В логе: `bg warm yt=… tg=…`.

### 2026-08-13 — Telemost: TG + быстрее (значок≈тумблер)

- YouTube ок; Telegram мёртв из‑за `disallow Telegram … direct`; значок VPN до тумблера ~10с (hev → долгий post-hev TLS×4).
- Фикс: TG снова через VPN (как WB); TLS **до** hev; после TUN один быстрый dial → сразу ready; ICE settle 1.2с max (не 4с).
- APK: `SilentVPN-debug.apk`. Лог: `Telegram via VPN`, `pre-hev CONNECT+TLS OK`, `post-hev dial OK`, без `disallow Telegram`.

### 2026-08-13 — Telemost vs WB: порядок ICE + TUN parity

- Симптом: после mapdns/OEM фикса всё ещё `post-hev CONNECT+TLS OK`, сайты нет; WB на том же коде ок.
- Сравнение с 1.0.160 / WB: у TM был settle ICE 800мс (нужно **4с**), double YouTube-warm до/после hev (flood vp8), exclude≈43 + TG CIDR (у WB ~DNS+2 host), `::/0` blackhole IPv6 (TLS-probe IPv4 ок, Chrome AAAA мёртв).
- Фикс: telemost ICE settle 4с; warm skip на TM; exclude только turn/stun (+DNS) как WB-паттерн; без TG CIDR (только disallow pkgs); IPv4-only + allowFamily как 160/WB.
- APK: `SilentVPN-debug.apk`. Лог: `settle=4000ms`, `YouTube warm skip`, `tgCidr=0`, `IPv4-only`, ips≈≪43.

### 2026-08-13 — Telemost ready/лог ок, сайты нет (mapdns + OEM + IPv6 leak)

- Лог пользователя: `tunnelReady` + `post-hev OK` + `tgVia=direct`, но трафика нет; тумблер крутится, значок VPN уже есть. Комната `940386…` / unit `o2-5777716db841` на соте **active**.
- Корень: (1) LTE `mapdns=fake-ip` — dial по домену из Silent OK, Chrome получает `198.18.x` без reverse → peer EOF; (2) `disallow OEM pkgs=185` (`com.vivo.*`) выкидывал OEM-браузеры мимо VPN; (3) `allowFamily(AF_INET)` пускал YouTube по IPv6 мимо hev.
- Фикс: mapdns выкл (реальный DNS + exclude); OEM только точный список push/analytics; `::/0` blackhole вместо allowFamily; post-hev = CONNECT **+ TLS** probe.
- APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`. В логе ждать: `mapdns=off`, `DNS=real`, `OEM pkgs` ≪ 185, `post-hev CONNECT+TLS OK`.

### 2026-08-12 — Telemost мёртв при живом WB (регресс TG via VPN)

- **Симптом:** после hardReset WB переключается ок; Telemost «лог нормальный / ICE+SOCKS», сайты нет.
- **Сравнение с 160 / lib:** `libolcrtc2.so` уже hardcode `vp8channel` fps=60 batch=64 (как YAML v1); srv transport=vp8channel; пул TM на `87.58.213.193` живой. Не баг бинаря.
- **Корень:** в hardReset-фиксе ошибочно вернули `bypassTelegramOutsideTun=false` для обоих («как 160») → фон TG жрёт узкий Telemost/vp8 → «вкл без интернета».
- **Фикс:** снова `bypassTelegramOutsideTun(telemost)=true` (WB — TG в VPN); убран широкий exclude `yandex.ru`, добавлен `goloom.strm.yandex.net`.
- APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`. В логе на TM ждать `tgVia=direct`.

### 2026-08-12 — hardReset TM→WB (без kill app) + post-hev SOCKS gate

- **Факт:** cold start WB ок; после Телемоста WB «вкл, не пашет» пока не убьёшь приложение; Телемост cold тоже пустой при зелёном ICE.
- **Причина:** hev/native/`suppressDestroyStop` не чистились как при kill; post-hev dial игнорировался → зелёный тумблер без трафика.
- **Фикс:** `hardReset` (destroyForcibly + двойной hev stop) на stop/start/Apply; post-hev SOCKS обязателен иначе fail; exclude hosts только своего провайдера. *(TG на TM — см. запись выше; не через VPN.)*
- APK: `SilentVPN-debug.apk`.

### 2026-08-12 — Telemost: TG вне TUN + max_clients=3 (vp8 budget)

- Лог: `tgVia=vpn` + `Telegram via VPN (telemost)` при ICE connected → ничего не грузит (TG жрёт vp8).
- WB: первый раз YT+TG ок; после свитча TG ок / YT нет — отдельно; на WB TG остаётся в VPN.
- Фикс: `bypassTelegramOutsideTun(telemost)=true`; Telemost `max_clients=3`, WB=25.
- Деплой + APK debug.

### 2026-08-12 — возврат pool 1.0.160 (leave≠teardown, max_clients=25)

- **Почему ломалось:** session-mode `max_clients=1` + leave/park/teardown убивали комнаты при Telemost↔WB; клиентский кеш указывал на мёртвый URL (TM wedge / WB join 404).
- **Как в 26–27 июля / [olcrtc](https://github.com/openlibrecommunity/olcrtc):** одна srv-комната шарится многими cnc; leave только sticky; Telemost room ~сутки, WB пока жив owner/srv ([issue #93](https://github.com/openlibrecommunity/olcrtc/issues/93)).
- **Сервер:** soft leave = clear sticky + recount; assign в shared pool `online < max_clients`; prune не рвёт комнаты со sticky; `DEFAULT_MAX_CLIENTS=25`.
- **Клиент:** dual-cache + preferCache / Apply cache-only как 160; cache key v16.
- Деплой: `deploy_api.py` + `heal_olcrtc2_pool_max_clients.py`. APK: `SilentVPN-debug.apk`.

### 2026-08-12 — park sticky + Apply revalidate (не cache-only после soft leave)

- **Симптом:** TM→WB→TM «включается но не грузит» → снова WB «нет конфига» / join 404.
- **Причина:** soft leave снимал sticky → комната в warm → prune/чужой claim рвали URL; клиент `swap cache-only` / preferCache поднимал мёртвую room без carrier-probe.
- **Сервер:** leave = **park sticky** (не warm); `HEARTBEAT_STALE_SEC=600`.
- **Клиент:** Apply всегда assign/revalidate selected; leave → dirty slot → connect без preferCache.
- Деплой: `deploy_api.py`. APK: `SilentVPN-debug.apk`.

### 2026-08-12 — почему «конфиги стираются» при Telemost↔WB + dual-cache keep

- **Симптом:** logout→TM (YT еле, TG нет)→Apply WB (bootstrap, TG ок, YT нет)→Apply TM → bootstrap не поднимается, «нет конфига».
- **Причина:** Apply при живом VPN делал leave → клиент **wipe слота** + сервер **teardown** комнаты. Второй слот часто пустой → третий switch требовал bootstrap и рвался.
- **Комнаты в пуле** (warm) не стирались — стирался **клиентский sticky-кеш** и **назначенная** комната.
- **Фикс:** leave = soft-warm на сервере (sticky снят, unit+room живы) + клиент `keepCache` обоих слотов; wipe только `reportOlcrtcRoomFailure`. Connect `preferCache` если слот есть. TG через VPN на обоих; IPv4-only Telemost+WB.
- Деплой: `deploy_api.py` (soft leave). APK: `SilentVPN-debug.apk`.

### 2026-08-12 — dual-cache как 1.0.160 + soft leave + Telemost IPv4

- **Почему ломалось vs 160:** session-mode leave=teardown сносил комнату → клиентский кеш указывал на мёртвый room; force-prefetch на Apply создавал новые и затирал смысл dual-cache.
- **Сервер:** leave/heartbeat_offline → soft keep sticky+unit (~10м, `HEARTBEAT_STALE_SEC=600`); failure → tear. Agent prune сносит протухшее.
- **Клиент:** login/Wi‑Fi → `prefetchOlcrtcBothProviders`; Apply при живом слоте = swap cache-only; leave keepCache.
- **Telemost серый YouTube:** IPv4-only TUN всегда (не только LTE).
- Деплой: `deploy_api.py`; APK: `SilentVPN-debug.apk`.

### 2026-08-12 — Wi‑Fi без :443: ephemeral не только LTE + Apply/connect mutex

- Лог: `ensureApi … mobile=false` → только public FAIL → NO_SESSION; Apply отменял connect mid-ephemeral (`StandaloneCoroutine was cancelled`).
- `ensureOlcrtcConfigApi`: после public miss на Wi‑Fi тот же ephemeral+tunnel-only; Mutex сериализует Apply/connect.
- Connect miss / force-fetch / roomFailure retry — ensure всегда (не только `isOnMobileData`).
- Apply: `cancelPendingOlcrtcConnectForApply` до ensure.
- preferCache и на Wi‑Fi, если queen unreachable.
- APK: `SilentVPN-debug.apk`

### 2026-08-12 — фикс LTE: leave не wipe + tunnel-only fetch

- Лог: WB connect OK, leave wipe → Apply ephemeral 30с била **public** `:443` вместо 10.66 → оба пустые.
- Leave **не стирает** v14-кеш; LTE connect = preferCache; Assign только через `fetchOlcrtcConfigTunnelOnly` в ephemeral.
- Apply больше не долбит public prefetch после ensure.
- APK: `SilentVPN-debug.apk`

### 2026-08-12 — лог LTE: WB «нет сессии» без bootstrap + Telemost slow

- По SVPN_OLC: после leave на LTE prefetch WB ~40мс FAIL (nip.io без VK) → NO_SESSION; после re-login через tunnel WB OK.
- Фикс: `ensureOlcrtcConfigApi` (ephemeral bootstrap) на Apply и connect miss; Telemost LTE → IPv4-only (меньше зависаний YouTube на v6).
- В логе ждать: `[CFG] LTE: ephemeral bootstrap` → `accept OK` → без NO_SESSION.
- APK: `SilentVPN-debug.apk`

### 2026-08-12 — Logcat SVPN_OLC + фикс Apply race wipe

- Тег Logcat: `SVPN_OLC`, флаги `[CFG]|[CACHE]|[APPLY]|[CONN]|[LEAVE]|[FAIL]|[HB]|[TM]|[WB]|[SESS]|[TUN]|[AUTH]`.
- Фильтр Android Studio: `tag:SVPN_OLC` (или `package:com.silent.vpn tag:SVPN_OLC`).
- Apply: leave только старого, wait stop, потом setProvider; late-leave без session snapshot не трогает prefs.
- APK: `SilentVPN-debug.apk`

### 2026-08-12 — автотесты сессии + Apply stop + bind session

- Юнит-тесты `OlcrtcSessionPolicyTest` (+ recovery): heartbeat leave, v14 кеш, leave по snapshot, denied accept, Apply при VPN.
- Policy `OlcrtcSessionPolicy`; Repository `bindOlcrtcSession` / fail/leave по сессии не prefs; Apply при смене канала → leave+DISCONNECT.
- Сервер smoke carrier: 5/5 WB + 5/5 Telemost alive. `test_olcrtc2_session_rules_unit.py` 4/4 ok.
- APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`

### 2026-08-12 — аудит: heartbeat leave рвал сессии + Telemost leak

- **P0:** `startOlcrtcHeartbeatLoop` вызывался дважды → `cancel` → `finally { leaveOlcrtcRoom() }` при живом VPN: teardown room + wipe кеша → «нет сессии» / зелёный труп Telemost.
- Фикс: leave только на disconnect (снимок provider/room); heartbeat без leave в finally; не перезапускать активный loop.
- Кеш: denied/пустая room не пишется и не возвращается из accept (fallback на кеш); Apply force-fetch выбранного провайдера.
- TUN: убран `allowFamily(AF_INET)` only + IPv6 `::/0` в TUN (анти-leak YouTube QUIC мимо hev); hev уже `udp: tcp`.
- APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`

### 2026-08-12 — Telemost «лог ок, сайты нет»

- Клиент: SOCKS+TUN ready, warm YT pre-TUN ok. На соте `o2-bc3f…` Google :443 шли ~1 мин, затем **control missed pong → liveness** — UI оставался зелёным.
- Корень: hev `udp: udp` пускал **QUIC** в узкий Telemost/vp8 (на PC olcrtc UDP/QUIC block).
- Фикс: hev `udp: tcp` + health-watch SOCKS после ready → peer_dead/красный лог.
- APK: `SilentVPN-debug.apk`

### 2026-08-12 — конфиги Telemost и WB раздельные

- Да, раньше один слот кеша — затирали друг друга → «нет сессии» при переключении.
- Сейчас: `olcrtc_config_cache_v14_telemost` и `…_wbstream` отдельно; legacy v13 не читаем.
- «Применить» греет **оба** слота (пустой добирает с API, полный не трогает).
- APK: `SilentVPN-debug.apk`

### 2026-08-12 — «нет сессии» при Telemost↔WB + Telemost без YouTube

- Смена провайдера: wipe всего кеша + async prefetch → тумблер раньше fetch → «нет сессии».
- Фикс: кеш **v14 per-provider**; смена не стирает другой слот; leave/fail чистит только свой; Apply **ждёт** fetch; connect force-fetch.
- Вылет на LOGIN — уже пофикшен ранее.
- Telemost «вкл, YouTube нет» без красного — отдельно (трафик/vp8); сначала стабилизировать сессии.
- APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`

### 2026-08-12 — вылет на LOGIN + «нет сессии» при смене Telemost↔WB

- Корень LOGIN: `WdttTunnelManager.stopInternal` не сбрасывал `isBootstrapMode` → после входа `isMainVpnSessionForUi=false` → экран входа при первом VPN.
- Корень конфигов: ICE kill@8с по media «connected» рвал Telemost до SOCKS → `clearOlcrtcCache` → «нет сессии»; API отдаёт один provider в кеше → смена WB↔TM без fetch = пусто.
- Фикс: reset bootstrap flag; убран ICE kill@8с; кеш только для текущего provider; смена провайдера чистит кеш.
- APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`

### 2026-08-12 — Android debug APK (carrier fail / нет конфига)

- Сборка: `assembleDebug` OK. APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`
- Включено: retry после мёртвой room, без возврата старого cfg, текст вместо «olcrtc-config нет».

### 2026-08-12 — WB join 404 / Telemost ICE без SOCKS (логи 14:02)

- Логи: `svpn_3b36…` WB join 404 + «olcrtc-config нет»; Telemost `265127…` ICE/pc connected → code=1 до SOCKS (~15с = `wait for peer`).
- На момент разбора обе room **уже сняты** из БД; пул: WB android~20, Telemost~23; smoke carrier **join/connection ok**.
- Корень WB: systemd active ≠ живая конференция (join 404). Фикс API: `_carrier_room_alive` (WB join / TM connection) на sticky+warm assign + heal WB; деплой `deploy_api.py`.
- Telemost «ICE ок / SOCKS нет»: cnc поднимает SOCKS **после** `bringUpLink`/`waitForPeer`; media к Яндексу ≠ peer olcrtc2-srv → timeout ~15с → code=1.
- Клиент: не возвращать мёртвый cfg (`?: cfg` убран); retry fetch после fail; яснее текст вместо «olcrtc-config нет». Нужен новый APK.
- Скрипты: `diag_olcrtc2_rooms_now.py`, `smoke_olcrtc2_carrier.py`.

### 2026-08-12 — WB join 404 + «нет конфига» + loadtest

- WB: клиент цеплялся к мёртвой `svpn_*` (guest/join 404). На Соте 2 за 2ч **146× not found** при active systemd.
- Баг клиента: `reportOlcrtcRoomFailure` при сбое fetch возвращал **старый cfg** → «новый канал» = та же мёртвая room.
- Фикс клиента: clear cache, не возвращать old cfg, early-fail на join 404/not found.
- Сервер: rebuild WB warm, prune; smoke assign OK (telemost+WB).
- SOCKS :5678 без auth — **не наш** (наш olcrtc = :8808 с auth). Вероятно другое приложение на устройстве.
- APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`

### 2026-08-12 — olcrtc2: гонка assign + loadtest 20 юзеров

- Симптом: 2–3 подключились — остальным «нет места»; Телемост «не летает».
- Корень: concurrent `/olcrtc2-config` без claim-lock → **N fingerprint на 1 комнату** (max_clients=1 нарушен; Telemost до 6 fp/room). Warm только `warm_pool_per_dt=3`.
- Фикс: claim-lock + `FOR UPDATE SKIP LOCKED` + резерв `online_count`; warm default/prod **12**.
- Скрипт: `backend/scripts/loadtest_olcrtc2_sessions.py` (+ `diag_olcrtc2_telemost.py`). Отчёты: `backend/scripts/reports/`.
- Host’ы Telemost на Соте 1 сами OK (MODE=telemost, Link connected, тот же srv md5 что WB).

### 2026-08-12 — WB: YouTube ок, Telegram нет

- В логе было `disallow Telegram … direct` + tgCidr exclude — TG шёл мимо VPN (оптимизация Telemost/vp8).
- На WB YouTube и так летает; у ISP с DPI Telegram без VPN мёртв.
- Фикс: на `wbstream` Telegram **через VPN**; bypass TG только для `telemost`.
- В логе ищи: `Telegram via VPN (provider=wbstream)`, `tgVia=vpn`.

### 2026-08-12 — WB 403 guests: auto-upgrade затирал фикс cell-agent

- Симптом: клиент `guests cannot create rooms` / guest JWT; на Соте 2 srv `mode=telemost` на `svpn_*` → Telemost 404.
- Корневая причина: ручной фикс `main.py` на соте перезаписывался `hive_cell_agent_auto` со **старого** `/opt/silent-vpn/backend/cell-agent/main.py` на Улье.
- Фикс: синхронизирован `cell-agent/main.py` на queen + Cell 1/2; apply пишет `MODE=wbstream` + `OLCRTC2_AUTH_TOKEN`; 6 WB host unit’ов **Link connected**.
- `upgrade_cell_agent_olcrtc2.py` теперь сначала кладёт agent на queen, потом на соту.
- Клиенту: Apply → WB Stream → VPN (сменить канал если старый sticky).

### 2026-08-12 — UI как 160 + фикс WB host JWT

- Меню обхода снова как 1.0.160: VK | olcrtc → Яндекс Телемост / WB Stream (движок olcrtc2).
- WB ошибка «гости не могут создать комнату»: apply теперь требует/рефрешет account JWT; heal tear WB без token + warm.
- APK debug пересобран. Пуш не делали.

### 2026-08-12 — olcrtc2 WB Phase 3 (Сота 2)

- Go: `olcrtc2-srv/cnc` mode=telemost|wbstream; pkg Token→auth; library carrier WB.
- cell-agent apply: реальный MODE + `OLCRTC2_AUTH_TOKEN`; deploy srv на Соту 1+2.
- Агент warm: `providers_enabled` оба; create WB API с queen; remote DELETE при tear.
- Админка: чекбоксы warm + IP Сота1/2. PC/Android debug: выбор Телемост/WB.
- Бинарники: `olcrtc2-cnc.exe`, `libolcrtc2.so`, srv на сотах. Пуш не делали.
- Docs: `.cursor/OLCRTC2_AGENT.md`.

### 2026-08-12 — olcrtc2: provider→cell + egress probe

- Роли: Улей = WDTT only; Сота 1 `87.58.213.193` = Telemost; Сота 2 `78.17.74.27` = WB (`cells.telemost` / `cells.wbstream`).
- Settings/assign/create: `cell_ip_for_provider`; админка — два IP; agent_status отдаёт `cells`.
- Egress probe `scripts/probe_olcrtc2_cell_egress.py`: Сота 1 YouTube TTFB ~0.38с / TCP 26–82ms; Сота 2 ещё быстрее (~0.16с). Узкое место — Telemost/vp8, не «мертвый» Google с соты.
- Docs: `.cursor/OLCRTC2_AGENT.md`.

### 2026-08-12 — YouTube минута на Wi‑Fi: fake-ip 198.18 + Telegram жрёт vp8

- Лог: warm 3/3 ок, CDN sid открылся, потом минутами `149.154.*` / `redirector`; на LTE `tunnel to 198.18.0.5` → EOF (mapdns leak).
- PC olcrtc: DNS без fake-ip (tcp через SOCKS). Android mapdns на Wi‑Fi ломал googlevideo.
- Фикс: Wi‑Fi = real DNS (меню) + exclude DNS; LTE = mapdns; Telegram CIDR+pkg вне TUN.
- В логе: `real DNS (Wi‑Fi как PC)`, `disallow Telegram`, нет `tunnel to 198.18.*`.
- APK: `SilentVPN-debug.apk`.

### 2026-08-12 — YouTube 10–20с vs 160: warm ДО hev TUN

- Тумблер уже ~3–4с (`tunnelReady`); «предзагрузка» YouTube — после TUN VK/TG/vivo жрут Telemost/vp8, CDN `rr*googlevideo` через 20–30с / на Wi‑Fi только redirector.
- 1.0.160: тот же vp8, но прогрев path до открытия full-tunnel.
- Фикс: `YouTube warm pre-TUN` (youtube/ytimg/redirector по SOCKS) → затем hev.
- ICE `failed … 10.112…` после TUN — шум (STUN с не того iface), сессия уже up.
- APK: `SilentVPN-debug.apk`. В логе: `YouTube warm pre-TUN N/3 …ms` до `hev TUN ok`.

### 2026-08-12 — YouTube Wi‑Fi grey + LTE false ICE-kill

- Лог Wi‑Fi: tunnelReady ок, `youtubei`/`redirector` есть, CDN `rr*googlevideo` нет; vivo/stsdk жрёт Telemost/vp8 ([olcrtc](https://github.com/openlibrecommunity/olcrtc): Telemost=только vp8, скорость datachannel>vp8).
- LTE: `peer latched` → ложный kill «ICE без SOCKS 8с»; auto-reassign не сработал на «SOCKS не поднялся».
- Фикс: kill только без peer latch; lastFailHint+reassign на SOCKS fail; `disallow OEM` (vivo/bbk/…) из hev TUN.
- В логе: `disallow OEM noise pkgs=N`, нет `ICE без peer/SOCKS 8с` при latch.
- APK: `SilentVPN-debug.apk`.

### 2026-08-12 — LTE: мёртвый preferCache + ICE без SOCKS 8с

- Лог: `preferCache room=876118` → ICE+KCP → 15с `code=1` → override `273778` OK; Wi‑Fi sync ~0.9с → tunnelReady ~2.5с.
- LTE больше не берёт кеш вслепую: softRefresh ≤3с → кеш; `lastFailed` room пропускается через reassign.
- `waitForSocks`: ICE Connected без SOCKS 8с → kill + reassign (не ждать code=1 ~15с).
- STUN warn после TUN с `10.112.*` — пост-ready ICE через VPN; сессия уже up (не блокер тумблера).
- APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`.

### 2026-08-12 — убрана долгая «предзагрузка» после tunnelReady

- Wi‑Fi+LTE работают; задержка — `warm TCP google/youtube/nip` на узком Telemost/vp8.
- Фикс: после hev только короткий `connectivitycheck` (2с); warm google/yt/nip снят.
- APK: `SilentVPN-debug.apk`. В логе не должно быть `warm TCP www.google.com`.

### 2026-08-12 — откат получения olcrtc-config к схеме 1.0.160

- Пользователь: «нет конфига» на Wi‑Fi и LTE после dirty/bad-room/bootstrap.
- Вернул как в **1.0.160**: LTE `preferCache=true` сразу из кеша; Wi‑Fi `sync` затем кеш; leave/failure **не** затирают кеш; убраны dirty/bad-room/ephemeral bootstrap для конфига.
- Кеш key `v13` (чистый старт). Один раз Wi‑Fi → Меню → Применить → дальше кеш работает на LTE.
- APK: `SilentVPN-debug.apk`.

### 2026-08-12 — olcrtc2 LTE «нет конфига» при переключении с Wi‑Fi

- Wi‑Fi OK (есть delay — пол Telemost/vp8). LTE: leave чистил кеш + nip.io мёртв → «нет конфига».
- Как VK-хеш в сборке: на LTE перед Telemost — **ephemeral bootstrap** (зашитый hash) → `/olcrtc2-config` через `10.66.66.1` → стоп bootstrap → olcrtc.
- Leave снова **не затирает** olcrtc-кеш (только dirty); bad-room только на failure.
- В логе ищи: `LTE: ephemeral VK bootstrap → /olcrtc2-config`.
- APK: `SilentVPN-debug.apk`.

### 2026-08-12 — olcrtc2: tunnelReady на LTE, но «ничего не грузит» + Wi‑Fi «нет конфига»

- Вердикт: **backend OK** (room `491033` unit active; SOCKS dial OK = peer жив). Ломал **клиент**.
- vs **1.0.160**: после hev не было `connectivitycheck.gstatic.com` до ready → Android не VALIDATED VPN; убран warm TCP.
- «Нет конфига»: dirty без fallback на кеш после wipe.
- Фикс: как 160 — 204-прогрев до ready + warm google/nip/youtube; кеш-fallback для non-bad rooms; leave snapshot→clear.
- APK: `SilentVPN-debug.apk`.

### 2026-08-12 — olcrtc2: клиент снова `251431` после wipe пула

- Причина: soft-refresh 1.2с → miss → кеш v11 с orphan Telemost (srv снесён) → code=1; после fail «нет конфига».
- Сервер OK: warm android отдаёт `122624…` (assign smoke PASS).
- Фикс APK: кеш **v12** (сброс), бан `251431` + bad-rooms, connect ждёт fresh до **12–15с**, dirty без fallback на кеш.
- APK: `SilentVPN-debug.apk`. Меню → Применить → Телемост; room ≠ 251431.

### 2026-08-12 — olcrtc2: Wi‑Fi+LTE code=1 одна wedged-комната `251431…`

- Симптом: ICE connected → SOCKS нет → code=1; «новый канал после early fail» = **тот же** room id.
- Причина: leave делал restart в той же Telemost-комнате (не лечит wedge); `ensure_unit_ready` видит только systemd active; failure возвращал старый cfg/ту же warm.
- Фикс API: leave/failure → **всегда teardown** комнаты (как VK); heal wipe+`ensure_warm_pool`.
- Фикс Android: `reportOlcrtcRoomFailure` не принимает тот же room id (иначе ложный «новый канал»).
- API задеплоен; пул пересоздан; APK пересобран.

### 2026-08-12 — olcrtc2 LTE: code=1 + tunnelReady без трафика (vs 160)

- Лог: room `104945…` ICE connected → `code=1` до SOCKS (wedged + cache-first без refresh).
- Потом room `251431…` tunnelReady, но на мобильном ничего не грузит: `ipv6Tun=true` + `excludeRoute ips≈12` (вместо ~36).
- Сверка с **1.0.160 Telemost** (не WDTT): IPv4-only `allowFamily(AF_INET)`, полный DNS exclude multi-A, udp-timeout 800.
- Фикс: вернуть IPv4-only+mapdns; exclude = STATIC+getAllByName; soft-refresh всегда ≤1.2с (dirty ≤2.5с).
- APK: `SilentVPN-debug.apk`.

### 2026-08-12 — olcrtc2: медленный connect + «10с до первой загрузки»

- Симптом: Wi‑Fi/LTE tunnelReady ок, но тумблер дольше чем раньше; после ready ~10с «тишины» у YouTube/Telegram.
- Не баг пути: логи `SOCKS dial OK` / `ICE already connected` — туннель жив.
- Самозадержки клиента: soft-refresh **всегда** ждал до 3.5с `/olcrtc2-config`; ICE sleep до 4с; excludeRoute DNS×11; hev connect-timeout 8с.
- Фикс: **cache-first** + dirty только после leave/failure; ICE wait 0.8с; STATIC_HOSTS → exclude без повторного DNS; hev connect-timeout 5с.
- Улей/WDTT (~75 Мбит, RTT VPS) Telemost/vp8 (телефон→Яндекс SFU→сота) **не догонит** по первой загрузке — это пол, не клиентский sleep.
- APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`.

### 2026-08-12 — olcrtc2: долгое «Отключение» + code=1 после leave

- Причина disconnect spinner: leave ждал `apply+settle 8с` на API; ползунок в DISCONNECTING.
- Причина code=1: connect из кеша в комнату, пока srv ещё restart / wedged (`690531…`).
- Фикс API: leave → `warming` + restart в фоне (HTTP сразу); stale warming tear агентом.
- Фикс Android: leave timeout 2с параллельно stop VPN; connect soft-refresh 3.5с, иначе кеш.
- Пул re-apply; API задеплоен. Нужен новый debug APK для UI/connect.

### 2026-08-12 — olcrtc2 code=1 после leave→warm (wedged Telemost)

- Симптом: peer connected → SOCKS 15с → `olcrtc вышел code=1 до SOCKS` (Wi‑Fi и LTE).
- Причина: leave оставлял unit «active» без restart → srv wedged в комнате; клиент ICE к Яндексу ок, peer/SOCKS нет.
- Фикс: leave/heartbeat_offline → `apply_olcrtc2_unit` (restart) + settle; warm assign снова через `ensure_unit_ready`.
- Прод: `deploy_api.py` + force re-apply всех warm unit’ов на Соте 1; sticky сброшены. Новый APK не нужен.

### 2026-08-12 — olcrtc2 конфиг без VK: leave не убивает кеш/комнату

- Баг: `leaveOlcrtcRoom()` всегда `clearOlcrtcCache()` + leave teardown комнаты → после disconnect Wi‑Fi/LTE снова «включите VK».
- Фикс API: leave/heartbeat_offline → sticky off, комната **в warm** (srv жив); teardown только `failure:*`.
- Фикс Android: кеш не чистить на leave; connect = `resolveOlcrtcConfigForConnect()` (кеш сразу); denied не затирает кеш; убран текст «включите VK».
- API задеплоен; APK пересобран. Один раз Применить если кеш уже пустой.

### 2026-08-12 — olcrtc2 «нет конфига / включите VK»: вернули LTE-кеш

- Как было (2026-07-27): конфиг на LTE через VK `10.66.66.1` или из кеша; nip.io с LTE часто мёртв.
- Регресс: после code=1 делали `clearOlcrtcCache` + долгий ensure_unit_ready на warm → пустой кеш + таймаут → текст про VK.
- Фикс: не сносить кеш до нового assign; LTE без туннеля — connect из кеша сразу; warm assign только быстрый probe; heal агента без re-apply×8с.
- API задеплоен; APK пересобран.

### 2026-08-12 — olcrtc2 code=1: sticky на мёртвый unit

- Лог: SOCKS auth=on, peer connected, exit code=1 до SOCKS. Room `487312…` уже не в БД.
- Причина: после замены `olcrtc2-srv` sticky указывал на unit без env (crash-loop `o2-c532`, status=2) — ICE к Telemost есть, srv в комнате нет.
- Фикс: cell-agent `POST /v1/olcrtc2/status`; assign `ensure_unit_ready` на sticky/warm; агент heal+teardown мёртвых; settle 8с.
- Crash-loop unit вычищен; API+cell-agent задеплоены.

### 2026-08-12 — откат latency-тюнинга + SOCKS5 auth (YourVPNDead)

- IPv4-only / QUIC 40мс / KCP 2ms **ухудшили** YouTube~10с и Telegram~20с — откат к dual-stack + udp 150 + KCP 5мс; сота srv обновлён.
- YourVPNDead: `SOCKS5 без auth на 8808` — у olcrtc2 creds намеренно обнулялись. Фикс: per-session RFC1929 → hev + `OLCRTC2_SOCKS_USER/PASS` в cnc; PC sing-box тоже.
- Exit IP соты через SOCKS — норма для VPN; без auth любой app мог ходить. С auth — только hev/sing-box.
- Референсы GitHub ([поиск olcrtc](https://github.com/search?q=olcrtc&type=repositories)): [olcbox](https://github.com/alananisimov/olcbox) / [WireTurn](https://github.com/spkprsnts/WireTurn) — тот же hev+локальный SOCKS; upstream [olcrtc#8](https://github.com/openlibrecommunity/olcrtc/issues/8) уже имел SOCKS auth.
- APK `SilentVPN-debug.apk` ~07:51.

### 2026-08-12 — olcrtc2 latency: IPv4-only hev + KCP 2ms

- После warm-dial: Telegram всё ещё 1–5с — HE по IPv6 в TUN (SOCKS IPv6 hang) + QUIC wait 150мс + пол Telemost SFU.
- Android hev: **ipv4-only** (`allowFamily(AF_INET)`), `udp-read-write-timeout:40`, `tcp-fastopen`, connect 3с.
- KCP `SetNoDelay(1,2,2,1)` в vendor (нужны новый `libolcrtc2.so` + `olcrtc2-srv` на соте).
- Пол Telemost (телефон→Яндекс SFU→сота) WDTT на Улье не догонит — это не баг клиента.

### 2026-08-12 — olcrtc2 Android: убрана пачка warm TCP после tunnelReady

- Симптом: «предзагрузка» перед страницами/видео; в логе `warm TCP …nip.io OK (x8)`.
- Причина: после ready шли 8 параллельных SOCKS CONNECT (gstatic/google/yt/nip.io) — на Telemost/vp8 забивали канал.
- На Улье (WDTT) этого почти не замечали (шире канал). `[pc]` в логе = PeerConnection (pion), не ПК-клиент.
- Фикс: убраны warm-dial’ы; tunnel уже проверен `waitForSocksDial(gstatic)`.

### 2026-08-11 — olcrtc2 warm-пул (вместо create-on-demand 90с)

- Почему ~1.5 мин: session-mode создавал комнату Playwright **на каждый connect**; prune ещё и сносил idle.
- Фикс: `warm_pool_per_dt=3` (pc+android), агент `ensure_warm_pool` + prune **хранит** свободные; assign = warm hit ~1с.
- После apply — sleep 5с (srv в комнате), меньше peer-connected→code=1.
- Прод: free pc=3 / android=3. Админка: Warm PC/Android + поле запаса.
- Deploy: `deploy_api.py` (API+agent+admin-ui).

### 2026-08-11 — olcrtc2 «конфиг нет кеш/сеть»

- Причина: `/olcrtc2-config` ждёт Playwright 30–90с, клиент рвал через **5–20с**; на LTE nip.io + пустой кеш после failure.
- Фикс: readTimeout **120с** / connect 30с; кеш не сносить пока нет нового; LTE hint — VK/Wi‑Fi → Применить.
- APK пересобран.

### 2026-08-11 — olcrtc2 LTE: OkHttp CONN_FILE (как v1)

- Симптом LTE: `carrier auth failed: Get cloud-api.yandex.ru…` → code=1 до SOCKS.
- Причина: Go TLS/DNS на мобильном не достучится до Telemost API; Wi‑Fi ок.
- Фикс: перед `libolcrtc2` — `prefetchTelemostConnViaOkHttp` → `OLCRTC_TELEMOST_CONN_FILE` + `OLCRTC_STATIC_HOSTS` (как старый olcrtc).
- YouTube медленнее «одного сервера»: Telemost/vp8 потолок ~10 Мбит + RTT соты; fps60 уже; WDTT быстрее.
- APK `SilentVPN-debug.apk` ~20:25.

### 2026-08-11 — olcrtc2: кеш мёртвой комнаты + YouTube/Telegram

- Первая долгая ошибка: LTE `preferCache` брал старый room без srv → timeout.
- Фикс: connect всегда `syncOlcrtcLiveChannel` сначала; `reportOlcrtcRoomFailure` чистит кеш.
- YouTube при tunnelReady: vp8 **fps 60**; hev UDP timeout 150мс (QUIC→TCP); warm googlevideo.
- Telegram «думает» — нормальная задержка Telemost/vp8 (не WDTT).
- APK + srv на Соте 1 обновлены.

### 2026-08-11 — olcrtc2 Android code=1: DataChannel→vp8channel

- Симптом: peer connected ~15с → `datachannel timeout` / exit 1 / SOCKS нет (Android + srv на соте).
- Причина: Telemost SFU **не открывает** WebRTC DataChannel; туннель только через **vp8channel** (как olcrtc v1).
- Фикс: `vendor/olcrtc/cmd/olcrtc2-{cnc,srv}` → `client.Run`/`server.Run` + `vp8channel`; ICE filter режет `10.66/16`; sticky до active; prune grace.
- Задеплоено: srv на Соту 1, assign на queen; APK `SilentVPN-debug.apk` (~20:02); PC `pc/resources/olcrtc2-cnc.exe`.

### 2026-08-11 — olcrtc 2.0: Android native + клиенты для теста

- `libolcrtc2.so` (arm64/armv7) из `backend/olcrtc2/cmd/olcrtc2-cnc`; меню Telemost снова активно.
- PC debug: `pc/build-debug-977561/`; Android: `SilentVPN-debug.apk`.
- Инструкция агента: `.cursor/OLCRTC2_AGENT.md`.

### 2026-08-11 — olcrtc 2.0 продукт готов к PC-тесту

- Smoke PASS: create Telemost на Соте 1 → assign → `olcrtc2@unit` → release teardown.
- Вкл: `enabled`+`agent_enabled`, Playwright `silent-olcrtc2-host-provision` на `87.58.213.193:9101`.
- Тест: PC `build-debug-534461` → Обход → Телемост → Применить → VPN → YouTube.
- Android native olcrtc2 — ещё нет (меню Telemost disabled).

### 2026-08-11 — olcrtc 2.0 Phase P каркас (session-mode + агент)

- `Olcrtc2Room`/`Olcrtc2Sticky`, `olcrtc2_assign` (1 fp=1 room), `GET /olcrtc2-config` → assign
- cell-agent `/v1/olcrtc2/apply|teardown|create`; агент prune; админка agent+pool stats
- Telemost create только через соту `:9101` (не queen). Нужен deploy host-provision на Соту 1.

### 2026-08-11 — olcrtc 2.0: заказчик = продукт session-mode, не smoke

- Нужно сразу: агент создаёт комнату **под каждого** пользователя (1=1), cap, heartbeat, teardown — как v1 session-mode, exit только на **соте**.
- Ручной Room ID в админке — только diag; продукт = assign on demand.
- План переписан: `.cursor/PLAN_OLCRTC2.md` → Phase P (приоритет).

### 2026-08-11 — фикс crash debug клиентов (PC UI + Android Hilt)

- **PC:** `isDebugBuild()` вызывали как функцию, а это boolean → падение UI. Фикс в `bypassStore.ts`; debug `pc/build-debug-534461/`.
- **Android:** установленный debug APK без Hilt `SilentApp_GeneratedInjector` → мгновенный FATAL. Чистый `assembleDebug`; WDTT-only до native olcrtc2; APK `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`.

### 2026-08-11 — olcrtc 2.0 Phase 4 partial (админка + debug клиенты)

- Почему не было в админке: Phase 2 = только srv на соте; UI/API — Phase 4.
- Админка: «Варианты обхода» → секция olcrtc 2.0 (room/key/apply сота).
- API: `GET /api/vpn/olcrtc2-config`; admin `/api/admin/olcrtc2`.
- PC debug: меню VK|Телемост, `olcrtc2-cnc.exe` + sing-box (`build-debug-534461`).
- Android debug: меню показывает Telemost как «скоро»; connect только WDTT до libolcrtc2.
- Проверка: админка room+ключ → «Применить на соту» → PC debug → Обход → Телемост → Применить → VPN.

### 2026-08-11 — olcrtc 2.0 Phase 2 (Telemost + Сота 1) + фикс админки 502

- **502 админка/API:** контейнер API падал на `ImportError apply_units_via_host` / missing `agent_leader` — полный `deploy_stable` + harden `main.py` (агенты не валят lifespan). Health **200**.
- Phase 2: Telemost `GetConnectionInfo` + Dial (vendor olcrtc), `olcrtc2-srv`/`cnc`, деплой на **Соту 1** `87.58.213.193` (`CELL_OLCRTC2_OK`, unit с MemoryMax/CPUQuota). Улей не трогали.
- Старт srv: `/opt/silent-vpn/olcrtc2/olcrtc2.env` → `OLCRTC2_ROOM` + `OLCRTC2_KEY`.

### 2026-08-11 — olcrtc 2.0 Phase 1 (loopback SOCKS)

- `backend/olcrtc2/`: MockCarrier `DialPair` → `secure` (XChaCha20-Poly1305) → smux → SOCKS5 cnc + srv egress
- Тесты: `go test ./...` OK; smoke `go run ./cmd/olcrtc2-smoke` → PASS
- План: Phase 0–1 отмечены в `.cursor/PLAN_OLCRTC2.md` / `backend/docs/PLAN_OLCRTC2.md`
- **Не деплоить на Улей** рядом с `wdtt`

### 2026-08-11 — olcrtc 2.0 старт (каркас)

- План: `.cursor/PLAN_OLCRTC2.md` / `backend/docs/PLAN_OLCRTC2.md`
- Go: `backend/olcrtc2/` — Carrier interface, MockCarrier tests, stubs telemost/wbstream
- Правило: **не деплоить на Улей** рядом с `wdtt`, пока нет соты

### 2026-08-11 — клиенты 1.0.161 (olcrtc UI снят)

- Android/PC: version **1.0.161**, force WDTT, меню обхода убрано из release. Push `android`/`pc`/`main`.

### 2026-08-11 — olcrtc полностью снят с продукта

- **Почему:** правки olcrtc на Улье снова били CPU рядом с `wdtt` и ломали быстрый VK.
- **Прод:** `olcrtc@*` / host-provision / proxy — stop+disable; providers+agent `enabled=false`; sticky wipe; rooms offline.
- **API:** `GET /api/vpn/olcrtc-config` всегда `enabled=false`.
- **Админка:** секция olcrtc удалена; пункт меню «VK / хеши» (только VkPage).
- **PC/Android:** `isOlcrtcBypass()=false`, меню «Варианты обхода» убрано из release (debug — только VK cred). Native `libolcrtc`/exe оставлены мёртвым кодом до отдельной чистки.
- Клиентам для UI нужен следующий билд/OTA; на проде olcrtc уже не отдаётся.

### 2026-08-11 — olcrtc WB session-mode (как Телемост)

- **Проблема:** Playwright на `stream.wb.ru` с IP Улья → HTTP 498 antibot; «нет свободных комнат» при выборе ВБ.
- **Решение:** create/delete через WB API (`POST/DELETE /api-room/api/v1/room`) с JWT из storage_state; `roomType=1`, `roomPrivacy=1`, `ownerId` из JWT `user`; уникальный title → `roomId`.
- **Код:** `ai/olcrtc_wb_api.py`; `create_room_best` сначала API для wbstream; teardown → remote DELETE; оба провайдера enabled в session-mode.
- **Прод smoke:** WB PC + Android assign/Link/release **PASS** (`olcrtc_enable_wb_session.py`).

### 2026-08-11 — olcrtc session-mode («как VK»)

- **Проблема:** shared-пул + autoscale/`min_free` + Playwright на Улье → Chromium-шторм, 502 host-provision, тормоза VK (инцидент 11.08).
- **Модель:** create on demand (`ensure_session_room`) → max_clients=1 → leave/`failure` = `release_session_room` (sticky+delete+stop unit). Агент только prune+heal; `session_mode=true`; Telemost-only; `OLCRTC_HOST_ONLY=1`.
- **Прод:** wipe `olcrtc_session_reset.py`, host-provision active, agent enabled session-mode. Smoke PC+Android Telemost assign/release **PASS**.
- Клиенты: clear olcrtc cache on leave (PC `v10`, Android already `v10`).
- Доки: `backend/docs/olcrtc.md`. Админка: рычаг Session-mode.

### 2026-08-11 — Telemost Android exit=1: unit не поднят для room

- Клиент получил `03337594714540` (`android-telemost-2`), а srv unit был **inactive** → ICE ok, SOCKS нет, code=1.
- Причина: агент создал комнату в БД, `apply_units` из Docker падал на `127.0.0.1:9101`.
- Фикс: `apply_olcrtc_units_from_db.py` → unit-2 **Link connected**; `OLCRTC_HOST_PROVISION_URL=http://172.17.0.1:9101` в compose.

### 2026-08-11 — olcrtc pool redesign: on-demand scale + admin UX + RAM

- Shared-пул сохранён (не delete-on-disconnect). При `pool_denied` — debounce heal/scale ~45с; цикл агента **150с**; idle GC дефолт **5 мин** (миграция со старых 45).
- Heal error чистит sticky; Playwright `browser.close()` в `finally`; метрики без фейкового `target_capacity_hint=1100`.
- Админка Bypass: вкладки Обзор / Комнаты / Агент (`OlcrtcManagePanel`).
- RAM: `diag_memory` — **wdtt ~3.2GB** (главный), API ~400MB; на wdtt выставлены `MemoryHigh=4G` / `MemoryMax=6G` (без рестарта).
- Деплой: `deploy_stable.py` + admin-ui dist. Тесты: `test_olcrtc_autoscale_unit.py` 9/9.

### 2026-07-27 — OTA 1.0.160 rebuild (Android + PC)

- Android: `assembleRelease` с bootstrap hash as-is; OTA `SilentVPN-release-1.0.160.apk` (72MB) — LTE cache v10 + WB 403 reassign.
- PC: `build-installer.bat` → `Silent VPN Setup 1.0.160.exe` (91MB) перезалит (кодовых диффов не было, свежий билд).
- Версия без bump: **1.0.160**.

### 2026-08-11 — Hive spill / random / olcrtc «нет комнат» + кнопки

- **Почему при CPU 100% не раскидывало на соты:** spill только когда online на Улье ≥ ~85% ёмкости; CPU сам по себе не эвакуирует. Живых клиентов rebalance не двигает (только offline).
- **Рандом queen/cell на каждый connect — хуже текущего:** рвёт sticky WG endpoint/pubkey, гонки manifest, обрывы. Оставляем sticky + spill gate.
- **«Нет свободных» при 0/2:** `_least_loaded_room` лочил *все* active комнаты провайдера (`FOR UPDATE SKIP LOCKED`) → параллельный assign пустой. Фикс: фильтр слота + лок по одной.
- **Кнопки статуса:** агент liveness возвращал draining→active; теперь admin hold + stop/start unit. Сортировка unit по числовому хвосту.
- Задеплоено `deploy_api`.

### 2026-08-11 — Улей CPU 100% / RAM ~9G

- Постоянно: **wdtt-server ~113% CPU, ~3.3G RSS**, ~6200 UDP на `:56001` (живые WG-сессии).
- Пики: Playwright host-provision (ThreadingHTTPServer) поднимал **несколько Chromium** → peak **6.4G**, load avg ~25 на 6 ядрах; 6× olcrtc@ ещё +~40% CPU.
- Фикс: create под `Semaphore(1)`, `MemoryHigh/Max` на host-provision, `MAX_CREATE_PER_CYCLE=2`, рестарт provision + kill chrome. wdtt не рестартили (уронит всех клиентов).

### 2026-08-11 — max_clients не применялся (везде 2, только pc-telemost 250)

- «Записать YAML / применить» писало YAML без сохранения формы → max в UI не попадал в БД.
- `reconcile` перестали писать max (защита от отката) → **Сохранить** тоже не меняло `0/2` в таблице.
- Агент: onBlur не слал PUT, если число уже совпадало с agent (комнаты залипли на 2).
- Фикс: reconcile снова пишет max на слот+хвосты; Apply сначала Save; кнопка «Применить» у мест агента; heal выравнивает max всех active под agent. Задеплоено.

### 2026-08-11 — Админка olcrtc: нули в Обзоре + лишние комнаты + ложный WB error

- **Нули в карточках** при «Всего свободно 1255»: UI ждал `metrics.by_slot`, при пустом/старом API показывал заглушки 0; теперь карточки считаются из списка `rooms`.
- **Лишние комнаты после max=250:** `ensure_rooms_synced` на каждый GET откатывал `max_clients` из legacy JSON (250→2) → free мало → агент плодил `-2`/`-3`. Фикс: sync больше не трогает max; PUT агента пишет max и в JSON slots.
- **WB «All connection attempts failed»** при живом пуле: Playwright-сбой досоздания больше не ставит `last_error`, если active-комнаты уже есть; подсказка в UI.
- Задеплоено `deploy_stable` + `deploy_api` (admin-ui dist).

### 2026-08-11 — Android olcrtc: Telegram ок, YouTube нет

- Симптом: Telemost `tunnelReady` + SOCKS OK, Telegram жив, YouTube нет. В логе `mapdns=fake-ip`, warm `nip.io OK`.
- Причины: (1) YouTube/Cronet **QUIC UDP:443** — olcrtc SOCKS только TCP; без `REP=0x07` на UDP ASSOCIATE клиент висит (патч был в vendor working tree, бинарь мог быть без него). (2) `allowFamily(AF_INET)` пускал **IPv6 мимо VPN в LTE** (в РФ YT часто мёртв, Telegram по IPv4 через SOCKS ок).
- Фикс: пересобран `libolcrtc.so` с drain+`REP=0x07`; hev `ipv6` + VpnService `::/0` (без allowFamily AF_INET); warm `i.ytimg.com`; udp timeout 400ms; **1.0.162**.
- Debug APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`. В логе ждать: `ipv6Tun=true`, `warm TCP www.youtube.com OK` / `i.ytimg.com OK`.

### 2026-07-27 — релиз+пуш: host-unhealthy prune + Android auto-retry

- Push `main` `3745e09`, `android` `9650dfb`.
- OTA Android **1.0.160** пересобран (hash `6EJ_t4ee…`) + авто-retry после reassign.
- Backend уже был на проде; git синхронизирован.

### 2026-07-27 — agent: host-in-room + client auto-retry (почему «не перемещает»)

- **Почему:** liveness считал комнату живой по guest-join HTTP, даже если host `olcrtc@*-wbstream` не в комнате → клиент `guests cannot create rooms`; `report_room_failure` не ставил `status=error`; Android после reassign **не reconnect**.
- **Фикс backend (задеплоено):** `report_room_failure` → `status=error` при guest 403/404/мертв; host-provision `GET /v1/unit-health` (Link connected); agent prune удаляет host-unhealthy; heal пересоздаёт.
- **Фикс Android (в коде, нужен OTA):** после early-fail/timeout — один авто-повтор `connect` на новой комнате.
- YouTube серые превью на A12 + Telemost: отдельно от WB — CDN thumbs (`i.ytimg.com`/`yt3.ggpht.com`) часто ломаются DNS/QUIC при живом SOCKS; видео может идти.

### 2026-08-11 — Инцидент: VK «ждёт 1–2 мин» (не клиентский DNS)

- Симптом у пользователя на **старом release и новом** клиенте: VK-путь работает, но долго.
- На Улье: ~102 online / ~6700 активных WDTT-потоков; WRAP OK без ошибок; VK `auth.getAnonymToken` с Улья ~0.15с.
- Параллельно **olcrtc host-provision** крутил Playwright и сыпал `POST /v1/create → 502` каждые ~55с (CPU chrome ~100%), рядом с `wdtt-server` ~113%.
- **Срочно на проде:** `systemctl stop silent-olcrtc-host-provision` + `olcrtc_room_agent.enabled=false` (существующие комнаты живы). Соты 87.58 / 78.17: agent отвечает, **WDTT :56000/:56001 closed** — весь VPN на Улье.
- Дальше: лог клиента за минуту ожидания (капча 90с?). Не путать с DNS-пушем `0eaf4b0`/`1135f8f`.

### 2026-08-11 — DNS: пресет «Как на сервере» + свой DNS (Android + PC, release)

- Меню **DNS** больше не debug-only: доступно в release на Android и PC.
- Новый дефолт **«Как на сервере»** (`server`) — **ничего не подменяет**, DNS берётся из `wg_dns` (важно для «Фильтр угроз (DNS)» = `10.66.66.1`). Прежний дефолт «Яндекс» остался обычным пресетом.
- Новый пункт **«Свой DNS»**: поле ввода, до 3 адресов IPv4/IPv6 через запятую, валидация + нормализация; невалидный ввод не даёт применить.
- Android: `DnsPreset` + `object DnsSettings` (единая точка чтения prefs → адреса; `override`/`describe`/`shortLabel`/`ipv4Servers` для olcrtc), `PREF_DNS_CUSTOM`, `MenuDnsScreen` (поле + `themeTextFieldColors`), сняты гейты `BuildConfig.DEBUG` в `WireGuardHelper`, `SilentVpnService`, `OlcrtcTunnelManager`, `MainScreen`.
- PC: `dnsPreset.ts` (`server`/`custom`, `sanitizeCustomServers`, `dnsMenuLabel`), `MenuDnsPanel` (поле + валидация), сняты гейты `isDebugBuild` в `prepareVpnConnect`/`bootstrapVpn`/меню.
- PC `normalizeDnsValue`: при пустом override теперь берётся **серверный** `wg_dns` (раньше всегда хардкод `1.1.1.1, 1.0.0.1, 77.88.8.8` — фильтр угроз не работал).
- `DnsPreset.DEFAULT` пустой ⇒ везде, где нужен fallback-адрес, используется `DnsPreset.FALLBACK` (Яндекс).
- Тесты: Android `DnsPresetTest` (10), PC `test/dns.test.js` (6). Android 1.0.161 debug собран.

### 2026-08-11 — Регрессия ЧС/БС: туннель рвал воркеры (fix)

- Симптом: после коммита ЧС/БС «воркеры набираются и сразу ошибка» на любой сети; DNS/DoH тут ни при чём.
- **Причина:** в `WireGuardHelper` из `excludeKey` пропала ветка `isBootstrap && !apiOverlayMode -> "bootstrap-companion"`. `wgSemanticKey` считает только PrivateKey/Address/PublicKey/Endpoint, поэтому ключ стал меняться на **каждый новый TURN-адрес** → `DOWN/UP` туннеля → обрыв уже набранных воркеров. Ветка возвращена.
- Ещё два дефекта того же коммита: в **БС** `included.add(packageName)` тащил Silent в туннель (libclient замыкался сам на себя) — теперь self только при `apiOverlayMode`, VK-пакеты исключены, пустой БС → fallback в ЧС; резолв доменных правил сайтов выполнялся синхронно под `wgApplyMutex`/`Dispatchers.Main` — теперь фоново (`refreshSiteBypassExcludes` async + `resolveSiteBypassExcludes` для UI-пути).
- **DoH-эксперимент откатан** (Go `dns.go`/`doh.go` + Kotlin) — в `git stash` ветки `android` как `doh-dns-experiment`; DNS работает как в 1.0.160. Проверено пользователем: Wi-Fi + мобильный OK.

### 2026-08-11 — PC: Яндекс.Браузер в списке исключений

- Симптом: Яндекс Браузер установлен, в «Исключения → Приложения» не видно.
- Фикс `listInstalledApps`: реестр StartMenuInternet/App Paths/Uninstall + LocalAppData/USERPROFILE, versioned `Application\<ver>\browser.exe`, ярлыки Яндекса не режутся SKIP_NAME; stub→browser.exe рядом.
- Тест: фейковое дерево LOCALAPPDATA. Пересобрать PC debug.

### 2026-08-11 — Исключения UI: единая кнопка «Добавить» + БС = все отмечены

- Сайты: поле на всю ширину + primary-кнопка «Добавить» снизу (PC `primaryBtn*`, Android `TvPrimaryButton`) — без боковой обрезанной кнопки.
- БС: при переключении и при пустом выборе — **все приложения уже отмечены**; пользователь снимает лишние. ЧС — пустой старт.

### 2026-08-11 — Исключения: ЧС/БС + сайты (домен/IP) + PC список

- **ЧС/БС приложений** возвращены (как до `c2dec06` / эталон SpaceNeuroX):
  - ЧС — выбранные мимо VPN (`excludeApplications` / host-bypass exe)
  - БС — только выбранные через VPN (`includeApplications` / bypass всех остальных exe)
  - Смена режима сбрасывает выбор
- **Сайты:** ручной список домен/IP/CIDR/wildcard → DNS → дыры в AllowedIPs (Android, компактный complement) или host-routes (PC). Лимит 100 правил. UI вкладки «Сайты | Приложения», меню «Исключения».
- **PC список программ:** Start Menu + Uninstall registry + явный скан `%LOCALAPPDATA%\Yandex` / Program Files\Yandex; фикс PS `-Include` через `\*`.
- Файлы: Android `SiteBypassRoutes.kt`, `AppExclusionsScreen`, `AppExclusionPackages`, `AllowedIpsHelper`; PC `siteBypass.js`, `exclusionsPolicy`/`State`, `listInstalledApps`, `AppExclusionsPanel`.
- iOS — вне объёма. Тесты: `npm test` (PC exclusions) + unit `SiteBypassRoutes`/`AllowedIpsHelper`.

### 2026-07-27 — olcrtc agent: liveness prune + create

- `ai/olcrtc_room_liveness.py`: WB guest-join / Telemost cloud-api → alive|dead|unknown
- Агент каждые 15м: sync `auth.token` → probe → **hard-delete** мёртвых (+sticky) → heal error → create до `target_rooms_*`
- Админка: `liveness_prune`, `last_liveness` в GET room-agent. Прод smoke: **9/9 alive**, yaml 9 units.

### 2026-07-27 — WB hot bootstrap: account JWT + новые комнаты на прод

- UI create: android `019fa3a0-3ff8-77fa-a5a5-2c87a48e34e0`, pc `019fa3a0-4ed6-7467-b45b-8b536cec1fec`
- `scripts/wb_hot_bootstrap.py` + `wb_push_rooms.py`: account `authType=wb`, YAML `auth.token`, units restarted
- Host: `Link connected` (не guest 403/404). JWT ttl ~60с — push сразу после логина.

### 2026-07-27 — Realme Android 12: WB 403 + протухший auth.token

- Лог: `room=019fa372…` (удалённая) + `guests cannot create rooms` / exit 1; Telemost — ICE+SOCKS, dial ещё шёл.
- Причины: LTE `preferCache` отдавал мёртвый room без fetch; srv YAML без/с протухшим JWT (`invalid_token`); WB `accessToken` ttl ≈45–90с, порог «свежести» 60с мешал сохранить state.
- Прод: WB временно `enabled=False`, units остановлены; Telemost active. Скрипт `scripts/wb_hot_bootstrap.py` + фикс TTL в `olcrtc_room_provision_host.py`.
- Android: cache `v10`, `resolveOlcrtcConfig` всегда пробует fetch; early-fail → clear+reassign; hint на guest 403.

### 2026-07-27 — hotfix 1.0.161: Android integrity + PC bypass label

- **Android:** release 1.0.160 падал с «VPN-модуль изменён или повреждён» — pin SHA-256 из `jniLibs`, а в APK попадал ELF после `strip*DebugSymbols` (размер тот же, хеш другой). Фикс: `keepDebugSymbols += "**/libclient.so"`.
- **PC:** в боковом меню нет подписи выбранного обхода (на Android «Варианты обхода · VK/olcrtc»). Фикс: `bypassNavLabel` в `MainScreen`.
- Версии: сначала ошибочно подняли до **1.0.161** — **откатили обратно на 1.0.160** (пользователь не просил bump). Фиксы остаются в коде 1.0.160.

### 2026-07-27 — Android: olcrtc-config через VK-туннель (LTE)

- Симптом: на мобильной сети «olcrtc-config нет (кеш/сеть)»; после Wi‑Fi конфиг подтягивался. VK работал.
- Причина: `fetchOlcrtcConfig` ходил только на публичный nip.io (`vpnNetwork=null`) — на LTE/белых списках недоступен.
- Фикс: при живом VK — `/olcrtc-config` через `10.66.66.1` (`withUserBackendApi` / overlay / direct); в `syncAll`/post-connect tunnel sync; prefetch в release; перед olcrtc-connect — prefetch пока WDTT ещё up.
- Версия без bump: **1.0.160**.

### 2026-07-27 — olcrtc online/sticky: дубли Android + PC не в online + silent dead

- **Дубли online:** `online_count` был ±1; heartbeat искал sticky по `room.slot_label` вместо `device_type` → каждый reconnect/heartbeat +1. Фикс: `online_count = COUNT(sticky)`; leave удаляет sticky; reconcile чистит stale sticky.
- **Leave:** Android/PC при disconnect шлют `online=false` по всем провайдерам из кеша **до** stop VPN; PC heartbeat через `tunnelApiRequest`.
- **Silent dead:** peer_dead в лог как error; после 2 fail recover — полный disconnect с красным «обход остановлен».
- Деплой: backend `olcrtc_assign.py` + `vpn.py`; клиенты android/pc.

### 2026-07-27 — olcrtc: bootstrap prefetch + sticky только выбранный provider

- Login через временный VPN: `syncLoginDataViaBootstrapTunnel` / `syncLoginDataViaTunnel` тянет `/olcrtc-config` до disconnect bootstrap.
- `?provider=` в olcrtc-config: sticky/online только у Telemost **или** WB; остальные — peek без sticky; чужие sticky снимаются.
- Версия клиентов без bump: **1.0.160**.

### 2026-07-27 — olcrtc: speedtest/Intermeter не должен ронять VPN

- Симптом: при Яндекс.Интернетометр / Speedtest — `туннель оборван — переподключение…` (SOCKS probe к gstatic таймаутится под нагрузкой → watchdog SOCKS_DEAD).
- Фикс: учитывать свежий `tunnel to` как признак живого peer; SOCKS_DEAD только после 3 fail подряд и без recent traffic; VP8 track EOF = stream noise; openstream не escalate при живом трафике.
- Debug APK собран локально (push по запросу).

### 2026-07-27 — room-agent WB: antibot 498 + heal снова OK

- Симптом в админке: `wbstream/pc: All connection attempts failed`, last ok со вчера; host `ok+pw tm=1 wb=1`.
- На VPS: `stream.wb.ru` → **HTTP 498** + `__wbaas/challenges` (antibot по IP Улья); Telemost при этом живой (200).
- Фикс Playwright: UA/args, ожидание challenge, явная ошибка antibot, proxy env `OLCRTC_WB_PLAYWRIGHT_PROXY`; агент — cooldown 6ч на WB antibot, Telemost не блокируется; пути storage → `agent_states/`.
- После деплоя heal: Telemost 4/4, WB 5/4, `last_ok` обновлён, 9 unit’ов active. Deploy: `deploy_olcrtc_host_provision` + `deploy_api` + `apply_olcrtc_units_from_db`.

### 2026-07-27 — olcrtc recover: unit/auto-тесты + policy

- Вынесена чистая `OlcrtcRecoveryPolicy` (initial grace, everReady gate, Wi‑Fi↔LTE, debounce, watchdog, peer-closed grace, prefetch invalidate, await underlying).
- `SilentVpnService` / `OlcrtcTunnelManager` / `VpnNetworkHelper` читают решения из policy.
- Unit: `OlcrtcRecoveryPolicyTest` + доп. кейсы в `NetworkRecoveryPolicyTest` — **все `testDebugUnitTest` OK**.
- Device smoke: `OlcrtcRecoveryDeviceTest` (fingerprint + policy на устройстве).
- Исправлено по тестам/ревью: после stop prefetch не reuse (media timeout); peer-closed grace message SOCKS vs ICE; await только через policy.
- Push — по запросу пользователя.

### 2026-07-27 — olcrtc recover: LTE / самолётик без залипания

- Симптом: UI «переподключение», интернета нет; на мобильной — только kill app + airplane.
- Причины: мёртвый TUN 0.0.0.0/0 без peer; await застревал на prefer wifi; `reportOlcrtcRoomFailure`/nip.io на LTE вешал recover.
- Фикс: stop TUN сразу (отдать интернет); await prefer≤3.5с → любой транспорт; на LTE старт только из кеша; ждать ready≤55с + 1 retry; без cancel in-flight. Push `android`.

### 2026-07-27 — olcrtc recover: не cancel своим watchdog

- Лог: `watchdog_olcrtc_down`×N → `StandaloneCoroutine was cancelled`.
- Фикс: не cancel in-flight recover (кроме disconnect). Push `android` `370bb5a`.

### 2026-07-27 — olcrtc DNS без fake-ip (Яндекс + меню DNS)

- Android hev: mapdns/fake-ip выкл; DNS = `DnsPreset` (Яндекс default), excludeRoute DNS IP (UDP через SOCKS мёртв).
- PC sing-box: fake-ip выкл; `tcp://` DNS через SOCKS из `dns_override` / меню DNS.
- «О сервисе»: после VK TURN/DTLS — строка «плюс Olcrtc».
- Push: `android` + `pc`. Откат fake-ip — по результату теста скорости.

### 2026-07-27 — olcrtc «иногда отваливается» после peer closed

- Симптом: Telemost живёт десятки минут → `[pc] closed` → OpenStream timeout; UI «как подключено», reconnect нет.
- Причины: (1) goolom сам reconnect, а мы сразу kill на closed; (2) watchdog ждал `!running`, а процесс жив при мёртвом peer; (3) та же комната после expiry.
- Фикс: grace 12с на peer_closed (отмена если снова Connected / SOCKS жив); SOCKS probe watchdog; stuck `running&&!ready`; на peer_dead — `reportOlcrtcRoomFailure` + новый room в JSON. Push `android` `b21ec61`.

### 2026-07-26 — Wi‑Fi↔LTE reconnect правильно (на базе `8991030`)

- База: последний push `8991030` (NOT_VPN + transport_switch обе стороны).
- Баг петли: после `stop()` `olcrtcProc=null`, старый `watchExit` слал `process_exit_early` на уже новый старт → `session stopped`×N.
- Фикс: stale exit всегда ignore (`olcrtcProc !== proc`); `process_exit_early` без peer_dead; `stop(silent)` + suppress peer_dead; `awaitUnderlyingReady(prefer wifi|cell)` до restart; blackout не сбрасывает fingerprint; кеш olcrtc не сносить на LTE; connect LTE `preferCache`.
- Покрывает: Wi‑Fi→LTE и LTE→Wi‑Fi (оба `transport_switch`). Debug APK локально.

### 2026-07-26 — UI: шрифты debug-меню = как Подписка/Сессии

- Android/PC «Варианты обхода», DNS, VK-креды: заголовок `14sp SemiBold` / `text-sm font-semibold` (было 18 Bold / text-base–lg bold).
- Подсказки и «Назад» — те же alpha/размеры, что у Бонусы/Сессии.
- Push: `android` `db65dc8`; `pc` `a06cbfc`.

### 2026-07-26 — Android olcrtc: reconnect + плитка + EOF noise

- Симптомы: `remote not ready (EOF)` в логе при живом VPN; после `peer … closed` / звонка / Wi‑Fi↔LTE — без reconnect, VPN-иконка «залипает»; QS-плитка не включала/выключала olcrtc.
- Фикс: `OlcrtcTunnelManager` — peer_closed/process_exit → `sessionDeadHandler`; transient stream EOF не красные при `tunnelReady`; `SilentVpnService.recoverOlcrtcAfterNetwork` (сеть/звонок/watchdog); `VpnSessionState` + `VpnTileConnect` + tile combine на olcrtc; UI → CONNECTING при обрыве.
- Debug APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`. Push: `android` `8efee00`; backend vp8 YAML `main` `fe2d6f5`; `pc` vp8 уже был `358569f`.

### 2026-07-26 — libolcrtc CGO: netlinkrib permission denied

- После OkHttp auth: `load interfaces: netlinkrib: permission denied` (Android 11+ SELinux).
- Причина: сборка `CGO_ENABLED=0` → `net.Interfaces()`. Нужен NDK+CGO `getifaddrs`.
- `build_olcrtc_android.bat` как libclient (`CGO=1`, NDK API 24). nocgo fallback — пустой список iface.

### 2026-07-26 — olcrtc: Jitsi убран (только Telemost + WB)

- Backend `PROVIDERS = (telemost, wbstream)`; агент без `_provision_jitsi`; админка Bypass без Jitsi.
- Клиенты default → `telemost`; legacy prefs `jitsi` → telemost.
- Прод: `purge_olcrtc_jitsi.py` + `apply_olcrtc_units_from_db.py` (disable `olcrtc@*-jitsi`).

### 2026-07-26 — Chrome «Сеть недоступна» при olcrtc

- Не падение VPN: Chrome/Android captive-portal в момент `establish` (generate_204).
- Сайты при этом работают; попап при каждом вкл. Смягчение: warm `connectivitycheck.gstatic.com` до tunnelReady, `setUnderlyingNetworks`, `setMetered(false)`.
- Если останется: в Chrome/системе выкл. «Частный DNS» (Private DNS) Auto — часто ложный offline на VPN.

### 2026-07-26 — Android olcrtc: сайты/админка нет, Telegram ок = DNS

- Симптом: Telegram работает, YouTube/админка/сайты — нет (не только YT).
- Причина: olcrtc SOCKS TCP-only; UDP DNS в TUN мёртв; VPN DNS `8.8.8.8` на LTE часто тоже мёртв. Telegram ходит по IP.
- Фикс как PC fake-ip: hev `mapdns` `198.18.0.2` → fake-ip → SOCKS CONNECT по домену; `allowFamily(AF_INET)`; exclude системный DNS + ICE hosts.
- В логе: `mapdns=fake-ip`, `warm TCP www.google.com OK` / `nip.io OK`.

### 2026-07-26 — Android olcrtc: YouTube IPv6 + почему TM≠WB

- Оболочка одна (cnc SOCKS+hev), движки разные: **WB=`livekit`**, **Telemost=`goolom`** (ICE/WS) — логи и скорость connect разные по природе.
- YouTube: Cronet IPv6+QUIC мимо IPv4-TUN; плюс hev UDP. Фикс: `allowFamily(AF_INET)`; hev udp reject; dial→hev (не hev до dial на TM — шторм CONNECT).
- В логе: `engine=livekit|goolom`, `IPv4-only`, `warm TCP www.youtube.com OK`, `tunnel to …googlevideo…`.

### 2026-07-26 — olcrtc скорость (vp8 60/64 + max_clients=2)

- Причина 3–20 Мбит: (1) YAML без `vp8.fps/batch` (дефолт 30); (2) `max_clients=1000` — все делят один SFU; (3) потолок Telemost ~10 Мбит в коде olcrtc (`vp8channel/kcp.go`).
- Порядок скорости (docs): `datachannel` > `vp8` > `sei` > `video`. Telemost = только vp8; WB DC нужен moderator.
- Фикс: srv+cnc `vp8: fps:60 batch_size:64`; agent/rooms `max_clients=2`; hev MTU 1400. Прод YAML+units перезапущены.
- Референс: https://github.com/openlibrecommunity/olcrtc — community URI `vp8-fps=60`.
- Debug: `pc/build-debug-153216/`, `SilentVPN-debug.apk`. Пуш — по просьбе.

### 2026-07-26 — Hardening + SOCKS5 auth (olcrtc)

- VPS: публичный CONNECT 8080/18443 закрыт ранее; убран лишний UFW `56002/udp`; host-provision `:9101` — `X-Internal-Secret` (без секрета → 401), UFW только Docker.
- olcrtc локальный SOCKS без auth = любой процесс на устройстве жжёт peer/room. Фикс: **автогенерация login/pass на сессию** → `socks.user`/`socks.pass` в YAML + sing-box/hev + dial-probe RFC1929.
- Proxy-флот SOCKS (`silent-socks`) уже с user/pass — не трогали.
- Debug: `pc/build-debug-597808/`, `android/.../SilentVPN-debug.apk` (SOCKS auth). Пуш — после проверки пользователем.

### 2026-07-26 — Android olcrtc: YouTube (QUIC) + быстрее Telemost

- Симптом: TM/WB connect OK, в логе `tunnel to 172.217…` / gstatic, но YouTube не играет; Telemost connect дольше WB.
- Причина YouTube: hev `udp: tcp` (не RFC) + olcrtc SOCKS без ответа на UDP ASSOCIATE → QUIC зависает (на PC — block QUIC в sing-box).
- Фикс: hev `udp: udp` + короткий `udp-read-write-timeout`; olcrtc `REP=0x07` на non-CONNECT; кэш OkHttp auth 4 мин; warm youtube/ytimg.
- Debug APK: `SilentVPN-debug.apk`.

### 2026-07-26 — LTE: Go DNS timeout + WB guest TLS

- Симптомы после CGO: WB `guest-register` Post fail (Go TLS); Telemost OkHttp OK → `lookup goloom.strm.yandex.net: i/o timeout`.
- Фикс: OkHttp prefetch WB (`OLCRTC_WBSTREAM_CONN_FILE`); Java DNS → `OLCRTC_STATIC_HOSTS` → Go `protect.DialContext` dial tcp4 по IP; YAML DNS = системный, не 8.8.8.8.
- Debug APK: `android/app/build/outputs/apk/debug/SilentVPN-debug.apk`. Ждать в логе: `WB auth OkHttp OK`, `STATIC_HOSTS=…`, `prefetched` / без `goloom… i/o timeout`.

### 2026-07-26 — LTE Telemost: OkHttp whitelist + без ANR

- VK ≠ TM/WB: VK — TURN по хешу; TM/WB — HTTP auth + WebRTC SFU.
- OkHttp → Yandex → `OLCRTC_TELEMOST_CONN_FILE` (не Улей). Старт только в `worker` (без ANR).

### 2026-07-26 — WB: JWT только на srv (не на клиенте)

- Один `auth.token` на srv+cnc → WB выбивает host (`reconnect reason=carrier`) → клиент `wait for peer`.
- JWT только в server YAML; `/olcrtc-config` без `auth_token`; клиент = guest. Telemost Android OK.

### 2026-07-26 — Android WB YAML: trimIndent ломал transport

- После `auth.token`: вставка строки с другим отступом → `trimIndent()` → битый YAML → `transport required`.
- Фикс: сборка YAML через `joinToString` (как PC); fallback transport `vp8channel` для WB/Telemost; hev `stopIfLoaded` перед повторным TUN.

### 2026-07-26 — Android WB: guest 403 → auth.token аккаунта

- Симптом: `carrier auth failed … get token status 403 … guests` при `provider=wbstream` (комната без гостей).
- olcrtc: если нет `auth.token` — guest register → getToken 403. Нужен JWT из `wb_auth_auth_slice.accessToken`.
- Backend: `providers.wbstream.auth_token` → `/olcrtc-config` + srv YAML `auth.token`; sync из storage_state (`sync_olcrtc_wb_auth_token.py`).
- PC/Android: пишут `auth.token` в client YAML. Прод: token в settings, `olcrtc@pc-wbstream`/`android-wbstream` active.
- **Нужна пересборка Android debug** (и PC debug, если тестируете WB на ПК).

### 2026-07-26 — Android Telemost ICE WARN (TURN timeout)

- Причина: hev full-tunnel до/во время STUN к `turn.tel.yandex.net`; UI красил `fail` как error. `[pc]` в логе = pion PeerConnection, не Windows.
- Фикс `OlcrtcTunnelManager`: пауза после SOCKS dial → hev; `excludeRoute` Yandex/WB hosts (API 33+); ICE TURN noise не как fatal в UI; post-TUN dial.

### 2026-07-26 — Telemost/WB rooms созданы и залиты на прод

- Cookies с ПК залиты; селекторы create обновлены (`create-call-button`, «Новая видеовстреча»).
- PC Telemost `77258956512770`, Android `41676137683602`; WB pc/android UUID в пуле.
- YAML + `olcrtc@*-telemost/wbstream` active; sticky сброшен. Клиенту: выкл/вкл VPN.

### 2026-07-26 — olcrtc agent: автосоздание Telemost + WB (host Playwright)

- Host systemd `silent-olcrtc-host-provision` `:9101` (Chromium вне Docker).
- Агент создаёт Jitsi + Telemost + WB: `target_rooms_telemost/wbstream` (дефолт 4), heal `error`.
- Деплой: `deploy_olcrtc_host_provision.py` + `deploy_stable.py`. Нужен один раз storage_state в админке.
- Без cookies: host `tm_state=0 wb_state=0` — комнаты TM/WB не создаст.

### 2026-07-26 — olcrtc: live-канал + room-failure + пояснение пула

- `POST /api/vpn/olcrtc-room-failure` — peer dead → sticky сброс, комната `error`; агент пытается heal (Jitsi авто; Telemost/WB только с cookies).
- PC/Android: в «Варианты обхода» живой room id; лог `канал:…` / `канал сменился:…`; при peer dead — report + новый `/olcrtc-config`.
- Админка пул: подпись `online/max` = сейчас онлайн / лимит на комнату (0/25 ≠ «25 человек в созвоне навсегда»).
- PC debug: `build-debug-453069`. Backend+admin задеплоены (`deploy_stable.py`).
- Важно: Telemost `72153214476536` в логе — протухший peer; без нового room URL или Playwright cookies агент не создаст Телемост сам.

### 2026-07-25 — olcrtc 1000+ закрытие задач (load-test + соты + LTE-path)

- Load-test API: `scripts/loadtest_olcrtc_1000.py` → **pass** (1000 fingerprint, spill по 22+22 комнатам, denied 0).
- Соты: `deploy_olcrtc_to_hive_cells.py` → olcrtc + cell-agent на `87.58.213.193`, `78.17.74.27` (`CELL_OLCRTC_OK`).
- LTE-path: Android Telemost assign OK (`10347145470417`); Android WB без cookies — disabled.
- YuMoney webhook flow задокументирован в `.cursor/APIS.md`.
- Capacity после bump telemost/wb: **1175** слотов.
- **Деплой:** `deploy_api.py` + admin-ui OK (health 200). **Push:** `main` `fc8228b`; `pc` `8f12002` (раньше).

### 2026-07-25 — olcrtc 1000+ прогрев пула (масса, не 1–2 юзера)

- Цель: **≥1100 слотов** (`target_capacity`) ≈ 1000 online + 10%; `max_clients=25` на комнату.
- Прод: `python scripts/seed_olcrtc_mass_pool.py` → Jitsi pc/android комнаты + **47 systemd unit’ов active**; agent `enabled`.
- Агент создаёт **Jitsi без cookies**; WB/Telemost — только с `storage_state`.
- `pool_denied=true` только если **ни один** провайдер не дал комнату (пустой WB больше не валит весь пул).
- Assign: резерв слота при выдаче (`online_count+1` + `FOR UPDATE SKIP LOCKED`) — иначе без heartbeat все садились в 1 комнату.
- Проверка: `python scripts/prove_olcrtc_scale.py` → `VERDICT pass=true` (capacity 1112, 60 fp → 22 rooms, denied 0).
- Авто: assign sticky+cap; agent догоняет capacity; apply пачками по 8 unit’ов.

### 2026-07-25 — olcrtc 1000+ каркас (Hive-плоскость)

- БД `olcrtc_rooms` / `olcrtc_room_sticky`; assign sticky+max_clients; heartbeat API.
- Админка: таблица пула (drain/active/off) + metrics; agent расширяет пул по free ratio / target_capacity.
- Queen: `apply_olcrtc_units_from_db.py`; соты: `deploy_olcrtc_cell.py` + cell-agent `/v1/olcrtc/apply`.
- Клиенты: cache bump, pool_denied текст, heartbeat loop.

### 2026-07-25 — olcrtc: per-provider systemd (fix wait-for-peer)

- Симптом: клиент Telemost `wait for peer` / code=1 — srv сидел в Jitsi (failover).
- Фикс: отдельные unit’ы `olcrtc@{pc|android}-{jitsi|wbstream|telemost}`; YAML из DB через `apply_olcrtc_units_from_db.py`.
- Prod: pc-telemost = `72153214476536`, android-telemost = `10347145470417`.

### 2026-07-25 — olcrtc: пул WB/Telemost + room-agent

- Пул `rooms[]` / `device_types` для **jitsi + wbstream + telemost** (PC≠Android).
- `olcrtc@pc` / `@android`: failover profiles всех включённых провайдеров на слот.
- Отдельный агент `ai/olcrtc_room_agent.py` (+ `olcrtc_room_accounts.py`, Playwright provision) — **не** VK-хеши; без рандомной регистрации.
- Админка `/bypass`: редактор пула у всех провайдеров + блок агента.
- Host: `scripts/olcrtc_room_provision_host.py`, seed `configure_olcrtc_prod.py`.
- Клиенты: cache bump PC v4 / Android v5. Docs: `backend/docs/olcrtc.md`.

### 2026-07-24 — Whitelist email: ужатие доменов

- Из `ALLOWED_EMAIL_DOMAINS` убраны Microsoft / Yahoo / Proton / Rambler / GMX / AOL / Zoho / Tutanota / mail.com / `vk.com`.
- Осталось: Gmail, Mail.ru-семья, Yandex-семья, Apple (icloud/me/mac), **`vk.ru`**.
- Уже зарегистрированные (outlook/yahoo/proton и т.д.) **не удалялись** — whitelist только на `/auth/register`; вход и VPN работают как раньше.
- Задеплоено (`deploy_api.py`) + push `main`.

### 2026-07-24 — Вариант 2 обхода: olcrtc (debug) рядом с WDTT/VK

- Админка: **«Варианты обхода»** (`/bypass`, redirect `/vk`) — секция 1 VK/WDTT + секция 2 olcrtc (key, Jitsi/WB/Telemost, YAML apply)
- API: `GET/PUT /api/admin/bypass/olcrtc*`, публичный `GET /api/vpn/olcrtc-config`
- VPS: `scripts/deploy_olcrtc.py` → systemd `olcrtc.service`, доки `backend/docs/olcrtc.md`
- PC/Android debug: UI выбора семьи обхода; путь olcrtc = cnc SOCKS + sing-box/hev TUN (бинари не в git). Release форсирует WDTT. Путь VK не ломался.
- **Prod seed (configure_olcrtc_prod.py):** `enabled=true`, все 3 провайдера в API; `olcrtc.service` жив на **Jitsi** `https://meet.egovm.ru/SilentVpnOlcrtcHive` (meet.jit.si требует token). WB/Telemost room ID — плейсхолдеры e2e (нужны свежие комнаты с сайтов, guest create недоступен). Android debug: bootstrap уходит в olcrtc при выборе варианта; бинарь в `assets/olcrtc/`.
- **2026-07-24 fix SOCKS/VK:** PC — `olcrtc.exe`+`sing-box.exe` в `resources/` (SOCKS только после peer; таймаут 90с; abs data dir). Android — выбор bypass пишется сразу (без «Применить»), бинарь `GOOS=android` в assets. Debug: `pc/build-debug-358349/`, `SilentVPN-debug.apk`.
- **2026-07-24 UX обхода:** вход/bootstrap **только VK**. olcrtc-config prefetch+кеш после логина. Выбор варианта только в меню после входа **с «Применить»**. Android: connect из кеша больше не форсирует WDTT при olcrtc. Debug: `pc/build-debug-550243/`, `SilentVPN-debug.apk`.
- **2026-07-24 olcrtc hang/config:** PC — olcrtc-config через `tunnelApiRequest` IPC (+bypass) до connect. Android — SOCKS wait в фоне (не main), логи в `traceApp`; иначе UI «вечно Подключение» без лога. Debug: `pc/build-debug-665807/`.
- **2026-07-24 Android Permission denied + PC sing-box:** Android 10+ нельзя exec из `filesDir` (`error=13`) — `libolcrtc.so` в `jniLibs/arm64-v8a` + запуск из `nativeLibraryDir` (fallback codeCache как libclient). PC: sing-box `address[]` вместо deprecated `inet4_address`; лог ready для olcrtc без «WG+workers». ICE TRACE `172.20.96.1→docker` на Win — шум интерфейсов, не блокер если SOCKS ready. Debug: `pc/build-debug-526945/`, `SilentVPN-debug.apk`.
- **2026-07-24 olcrtc YouTube + Android empty log:** PC — block QUIC/UDP в sing-box (YouTube→TCP), DNS tcp через SOCKS, фильтр спама stderr. Android — `traceApp`→`logUi` (лог в UI), watchdog не зовёт WDTT resume при olcrtc, бинарь CGO+codeCache, без пустого TUN. Debug: `pc/build-debug-752310/`, `SilentVPN-debug.apk`. **Осталось:** Android TUN bridge (hev/sing-box) для трафика приложений; PC+Android не в одной комнате одновременно.
- **2026-07-24 olcrtc regression fix:** PC — откат жёсткого DNS/block-all-UDP (ломало SOCKS code=4); при смене olcrtc→VK полный cleanup + `vpnIsReady.olcrtc` не блокирует reconnect. Android — exec **только** `nativeLibraryDir` (codeCache тоже noexec/error=13). Debug: `pc/build-debug-456033/`, `SilentVPN-debug.apk`.
- **2026-07-24 olcrtc warmup + Android TUN:** PC — SOCKS dial-probe до `ready` (нет ложного «подключено» + долгого прогрева), тише xmpp/sing-box лог. Android — hev JNI (`libhev-socks5-tunnel.so`) + `OlcrtcVpnService` TUN→SOCKS после dial OK. Debug: `pc/build-debug-426668/`, `SilentVPN-debug.apk`.
- **2026-07-24 hev crash + PC sites lag:** Android crash при варианте 2 = `NoSuchMethodError HevSocksTunnel.TProxyGetStats` (JNI RegisterNatives) + `ensureLoaded` на stop; фикс: добавить `TProxyGetStats`, stop только если lib уже loaded. PC: dial-probe по домену `www.gstatic.com` (DNS через peer), DNS TCP через SOCKS + block UDP:53/QUIC, фильтр ICE unreachable / socks code=4. Debug: `pc/build-debug-592311/`. **Масштаб:** одна Jitsi-комната ≠ 1000+ юзеров — см. TASKS «olcrtc room pool».
- **2026-07-24 olcrtc faster + Android DNS/notif:** PC — dial ×2 + warm доменов, `sniff_override_destination`, фильтр ICE «no candidate pairs». Android — сайты не работали (UDP DNS через hev/SOCKS мёртв) → `excludeRoute` DNS API33+; уведомление «Подключение к серверу» не сменялось (postVpn только WDTT) → watch `OlcrtcTunnelManager.tunnelReady`. Debug: `pc/build-debug-886348/`, `SilentVPN-debug.apk`.
- **2026-07-24 olcrtc death + logs + UDP:** UI не показывал `[olcrtc] dial/warm` (sendLog фильтр). После смерти peer UI оставался «вкл» → меню не давало сменить на VK; фикс: `setOlcrtcSessionDeadHandler` → `vpn-stopped` + cleanup мёртвой сессии на connect. Speedtest «нет интернета» — UDP через SOCKS мёртв → block all UDP (TCP-сайты ок). **Скорость ~5 Мбит и PC≠Android в одной комнате** — лимит datachannel + одна Hive-комната; полный pool — TASKS. Debug: `pc/build-debug-797197/`.
- **2026-07-24 PC fake-ip:** минута после ready — DNS/DoH через peer (`tunnel to dns.google:443`×N). sing-box: fake-ip + hijack-dns + sniff. TASKS room pool расписан (MVP: N комнат + N srv + sticky выдача). Debug: `pc/build-debug-476140/`.
- **2026-07-24 room pool MVP + PC log/DNS:** PC — reject DNS HTTPS/SVCB (EOF `mc.yandex.ru`), INFO stderr не как `:err`, фильтр `api2.cursor.sh`. Backend — пул Jitsi `pc`/`android`, `GET /olcrtc-config?device_type=&fingerprint=`, админка rooms, `olcrtc@pc`+`olcrtc@android` (Hive / HiveAndroid), crypto_key без ротации. Клиенты передают device_type. Prod проверен: android → HiveAndroid. Debug: `pc/build-debug-279338/`.
- **2026-07-24 sing-box bad rdata:** hijack DNS только `:53` + block LLMNR/mDNS; фильтр `bad rdata` в UI. Debug: `pc/build-debug-696665/`, Android `assembleDebug` из `android/app`.
- **2026-07-24 Android LTE + PC/Wi‑Fi conflict:** (1) оба srv делили `data/` → раздельно `data-pc`/`data-android`; (2) LTE `failed to send handshake` к meet.egovm.ru = DPI → Android-слот на `meet.playform.ru`; CONNECT `:8080` запасной. ICE `dummy0`/`fe80` — шум, в UI не показываем. **Wi‑Fi PC+Android одновременно — OK.** LTE → TASKS: WB/Telemost (не сегодня).

### 2026-07-23 — Login 500: исчерпан пул WireGuard `10.66.66.0/24`

- **Симптом:** регистрация OK, `POST /api/auth/login` → **500** (`RuntimeError: No available WireGuard addresses` в `ensure_device_session` → `_get_next_wg_address`). 128 ошибок за сутки.
- **Причина:** backend выдавал IP только из `10.66.66.0/24` (~253 клиента), хотя **wdtt0 уже `10.66.0.0/16`**. В БД было 257 device-сессий → пул забит. `prune_idle_*` не вызывался.
- **Важно:** удалялись только строки **`devices`** (VPN-сессии / WG-IP), **не `users`**. Аккаунты, подписки, email — на месте (233 users). После входа сессия создаётся заново.
- **Срочно:** DELETE 165 idle offline device >6h.
- **Расширение пула:** `WG_SUBNET=10.66.0.0/16` (~65k IP, минус `10.66.66.1` и `10.66.67.0/24` под TG). Задеплоено + `restore_api_container`.
- **Код:** idle-prune/reclaim только devices; login `RuntimeError`→503; фикс `queen_load` в hive summary.

### 2026-07-24 — MFA письмо: лого «всё ещё» — не из нашего MIME

- Проверка на проде: исходящее MFA = `multipart/alternative` (text+html), **HAS_PNG=False**, без `logo.png`/`image/png`.
- SMTP: `smtp.mail.ru` от `silent27@bk.ru`. Если вложение видно на **старых** письмах — это до фикса. Если на **новых** после запроса кода — смотреть подпись ящика Mail.ru (веб → Настройки → Подпись), не код Silent.

### 2026-07-24 — Админка MFA: «неверный код» + PNG-лого в письме

- **Код «неверный»:** при копировании из HTML Mail.ru часто вставляет пробелы из-за `letter-spacing` → хеш не совпадал. Нормализация: только цифры. TTL кода **2→10 мин** (письмо может идти дольше 2 мин).
- **PNG в письме:** `_send` прикреплял `logo.png` как inline CID, но в HTML **не было** `cid:silent_logo` → клиенты показывали вложение. Вложение убрано.
- Деплой: `deploy_stable.py` + admin-ui build.

### 2026-07-22 — Backend: паттерны анонимайзеров по аудиту БД (без удаления)

- Аудит users (221 email): явные анонимайзеры/алиасы — см. отчёт в чате. **Никого не удаляли.**
- Новые правила только на **будущие** регистрации: точечный Gmail (`a.b.c.d.e`, ≥4 точки), рандом local Mail.ru-анонимайзера (`504c52c1f5lc`…), `trialN@`. `stisss2107`-подобные ники не режем.
- Деплой `deploy_stable.py`.

### 2026-07-22 — Backend: блок анонимайзеров почты + 1 trial на устройство

- **Проблема:** Mail.ru анонимайзер (до 10 алиасов, часто `@internet.ru`) и hide-my-email/relay → новые аккаунты и бесплатный trial.
- **Фикс email:** `internet.ru` убран из whitelist; hard-block `BLOCKED_EMAIL_DOMAINS` (internet.ru, privaterelay.appleid.com, duck.com, mozmail.com, SimpleLogin/AnonAddy…); запрет `+alias`; Gmail canonical uniqueness (точки/googlemail).
- **Фикс trial:** `require_device_trial_not_reused` на `/vpn/device/register` и `/vpn/config` — один trial на `device_fingerprint` (алиасы на одном телефоне не дают второй бесплатный VPN). Платный аккаунт не блокируется.
- Тесты: `scripts/test_email_validation_unit.py` 7/7. Клиенты не трогали.

### 2026-07-22 — Откат локальных правок клиентов → origin

- PC / Android / iOS: `git reset --hard origin/*` + `clean -fd`. Рабочие деревья чистые.
- PC `8883c6a`, Android `d195bf3` (1.0.159), iOS `a454e6c`. Локальные soft-ramp / preflight / admin-эксперименты сняты.

### 2026-07-22 — PC: админка снова nip.io (+bypass); откат soft-ramp Telegram

- **Админка:** канон `fcfc87a` — всегда `https://132-243-234-162.nip.io/dashboard`. При VPN — `ensurePublicApiBypass`. Tunnel `10.66.66.1/dashboard` **не** открывать (MFA Host guard / решение пользователя). Откат ошибочного `8883c6a` и локального «always tunnel».
- **Воркеры:** soft-ramp 10s/7s + chunk=24 ухудшил Telegram (видео не грузится) — возврат PC к **3s/2s** (legacy 6s/5s) + **chunk=8 / retry 50ms**. Android: убран target-n soft-cascade, dispatcher снова chunk=8; Wi‑Fi `-vk-dns-public` оставлен.
- Debug PC: `pc/build-debug-850631/win-unpacked/` + `SilentVPN-Admin.bat`. Android debug APK после `assembleDebug`.

### 2026-07-22 — PC: админка при VPN снова ломалась (fallback nip.io)

- **ОТМЕНЕНО** пользователем: не открывать `10.66.66.1` — официальный URL nip.io (см. запись выше + `fcfc87a`).

### 2026-07-22 — PC+Android: мягкий каскад воркеров (Telegram медиа без ↓n)

- **ОТМЕНЕНО** пользователем: стало хуже, Telegram видео перестало грузиться. Откат к прежним паузам/chunk (см. запись выше).


- **Симптом:** LTE ок, домашний Wi‑Fi — Silent не коннектится (Honor 200 Pro и др.). Отдельно: большой APK в Telegram по Wi‑Fi падает на 100% — это не Silent.
- **Причина:** после `b7e2201` убрали PreferGo/8.8.8.8 (ломал LTE); на Wi‑Fi ISP DNS poison `api.vk.*` снова возможен.
- **Фикс:** флаг `-vk-dns-public` только если `!isOnMobileData` → Go `creds_direct.go` PreferGo + 8.8.8.8/Yandex/CF **без** LocalAddr-bind; LTE без флага. Ротация хостов снова с `api.vk.com`.
- Preflight чужого WDTT (PC+Android) — отдельно, уже в коде с прошлого шага.


- **Симптом:** после другого VPN на той же технологии (qwdtt/wdtt/WireGuard) Silent «не подключается» / нет сети, помогает только перезагрузка Windows/телефона.
- **Причина:** чужие WG-адаптеры Up + маршруты `0.0.0.0/1`/`128.0.0.0/1`, занятый UDP `:9000`, на Android — Always-On другого приложения или залипший чужой VpnService.
- **PC:** `pc/src/main/vpn/preflightCleanup.js` перед `vpn-connect` — kill чужих wdtt/qwdtt/libclient, освобождение `:9000`, Disable чужих WG/Wintun (не `wg-turn`), снятие чужих `/1` маршрутов, `ipconfig /flushdns`.
- **Android:** `VpnNetworkHelper.describeVpnConflict` — Always-On другого пакета = blocking + Intent в настройки VPN; иначе агрессивный `VpnConnectHelper.prepareForConnect` + пауза в `WireGuardHelper` перед захватом TUN.
- Версии пока **1.0.159** (без bump); в релиз уйдёт следующим OTA.


- **Симптом:** при включённом VPN «Админ-панель» не открывалась (nip.io + bypass — ISP whitelist режет вне туннеля).
- **Backend:** `AdminHostGuard` пускает админ SPA + `/api/admin/*` / `/api/auth/admin/*` с `Host: 10.66.66.1` **и** `ADMIN_PUBLIC_HOST` (nip.io). Сырой IP / чужой Host → 404. Проверено на VPS: tunnel dashboard **200**, no-host **404**, admin API **401** (не 404).
- **PC:** VPN ON/OFF → **всегда** `https://132-243-234-162.nip.io/dashboard` + `ensurePublicApiBypass` при VPN (`fcfc87a`). Tunnel `/dashboard` не использовать.
- Деплой: `deploy_stable.py`.
- **Push:** `main` `109c77c`; админка nip.io — `pc` `fcfc87a` (не `8883c6a`).
- **Build-agent на VPS:** `build_pc.sh` / `build_android_go.sh` / `ensure_go.sh` **идентичны** локальным (API **24**, `GOTOOLCHAIN=go1.26.3`, PC **reuse** `wdtt-client.exe` из git без `PC_FORCE_REBUILD_WDTT=1`) — лишних расхождений в ночной сборке нет.

### 2026-07-22 — Landing: гайд — Подписка / Бонусы / Сессии

- В инструкцию `#guide` добавлены 3 интерактивных демо в том же стиле клиента (меню → экран, курсор, caption): **Подписка** (тарифы → ожидание YuMoney → успех), **Бонусы** (реф-ссылка + промокод), **Сессии** (онлайн-точки, подпись устройства).
- TOC: +«Подписка» / «Бонусы» / «Сессии»; в меню демо «Устройства» → «Сессии (n/3)» как в PC/Android. Стиль/переходы не менялись; `guide.css`/`guide.js` → `?v=5`.
- Push `silentvpn3.github.io` `main`: `b58578d` (rebase поверх sync релизов 1.0.159). Сайт: https://silentvpn3.github.io/#guide

### 2026-07-22 — bump PC/Android 1.0.159 + push

- Android `1.0.159` / code 159; PC `1.0.159`. Включает коммиты после 158 (theme bg, Ugoos, Win10 wg-turn, admin nip.io, Go pin) — без Wi‑Fi Telegram экспериментов (откатили).
- Debug сборки; OTA release — отдельно.

### 2026-07-22 — build-agent: API 24 на VPS + GOTOOLCHAIN (Android/PC)

- **Почему release на сервере ломался при том же git:** на VPS оставался старый `build_android_go.sh` (**android29**); `deploy_stable` не трогает `build-agent/`.
- **Фикс + деплой:** `build_android_go.sh` API 24 + жёсткий `GOTOOLCHAIN=go1.26.3`; `ensure_go.sh` не перетирает заданный toolchain; `python scripts/deploy_build_agent.py` — на хосте и в контейнере проверено.
- **PC vs локально:** NDK/API29 к PC не относится (CGO=0 Windows). Выровняли Go 1.26.3 в `build_pc.sh` + локальных `build-debug.bat`/`build-installer.bat`. Отличие: сервер может **reuse** `wdtt-client.exe` из git (`PC_FORCE_REBUILD_WDTT=1` — пересобрать).
- **OTA 1.0.158 на сервере ещё старая** — нужна пересборка Android release через build-agent.

### 2026-07-21 — PC: Win10 оставляет wg-turn после disconnect

- **Симптом:** на Windows 10 после выключения VPN адаптер `wg-turn` остаётся Connected → нет интернета, пока не выключить вручную. На Win11 ок.
- **Причина:** `forceStop` без проверки/elevation; install мог быть через UAC, uninstall — нет; плюс Win10 часто не рвёт адаптер после `sc stop`. Bypass снимали до stop → `/1+/1` в мёртвый туннель.
- **Фикс:** stop → verify → Disable-NetAdapter → при залипании UAC uninstall; порядок: сначала туннель, потом bypass; перед install Enable disabled-адаптера.
- Debug: `pc/build-debug-883533/win-unpacked/SilentVPN-Admin.bat` — проверить на Win10: выкл VPN → адаптер wg-turn не Connected.

### 2026-07-20 — PC: YouTube после flood→капча (рамп 9→27)

- **Симптом:** flood → автокапча → 9/9 OK, сайты ок, YouTube нет (Android с 9 ок — мобильный CDN легче).
- **Причина:** legacy жёстко clamp n=9 без рампа; full tunnel @9 мало WDTT-полосы для desktop YouTube (как 2026-07-09).
- **Фикс:** boot 9 (капча без шторма) → рамп до **27** (`-target-n`, паузы 6s/5s). Go больше не режет target-n в legacy.
- Debug: `pc/build-debug-471885/win-unpacked/` (SilentVPN-Admin.bat). В логе ждать `n=9→27` и рост до 27 воркеров.

### 2026-07-20 — PC: админка снова через главную ссылку nip.io

- После MFA Host guard tunnel `10.66.66.1/dashboard` → **404**. Клиент снова открывает `https://132-243-234-162.nip.io/dashboard`.
- При VPN перед `openExternal` — `ensurePublicApiBypass` (браузер доходит до nip.io).
- Убрана подпись «только 10.66.66.1»; `getAdminPanelUrl` всегда `PUBLIC_ADMIN_URL`.
- Debug: `pc/build-debug-208755/win-unpacked/Silent VPN.exe` (лучше `SilentVPN-Admin.bat`).

### 2026-07-20 — Фикс фона главной: nip.io URL + видимость

- PC брал `https://132.243.234.162/static/...` → TLS fail → битый значок. Теперь всегда `nip.io`.
- Opacity фона поднята (~0.32–0.38); onError скрывает битую картинку.
- Android: тот же URL; SVG лого пропускаем (BitmapFactory); логи загрузки.
- theme_settings: logo.svg→png, strip `?t=` из asset URL.
- IPC fetch-theme-asset на PC **не нужен** (после рестарта клиента картинка ок) — откат незавершённого.

### 2026-07-20 — Оформление: деплой + лого/фон только debug

- Логотип (`logo_url`) и фон главной (`home_bg_image_url`) применяются **только в debug** PC/Android; release игнорирует.
- Деплой backend (theme API + admin-ui + static logo) без push.

### 2026-07-20 — Оформление: лого, dark-превью, ч/б фон главной, debug radio

- **Админка «Оформление»:** вместо круга «SV» — логотип (SilentLogo / `logo_url`); переключатель Светлая/Тёмная только для превью (пользователь в клиенте сам); на «Главная» — загрузка любой картинки фона.
- **Backend:** `ThemeResponse.home_bg_image_url`; `POST /api/admin/theme/upload-home-bg` и `upload-logo` (сразу пишут URL в theme + bump revision); default `logo_url` → `/static/logo.png`.
- **Клиенты PC/Android:** фон главной — grayscale + opacity ~0.18–0.22, без blur; лого из `logo_url` на логине; ConfigSync уже тянет theme.
- **PC debug «Режим VK-кредов»:** радиокнопки и «Применить» в цветах темы (не синие системные).
- **Android debug:** `RadioButton` selected/unselected = `fg` темы.
- **iOS:** поле `home_bg_image_url` в `ThemeData` (рендер фона — когда UI догонит).

### 2026-07-20 — Админка устройства: ПК=«ПК», модель телефона, анти-дубли

- ПК всегда «ПК» (поле имени убрано). Телефон: Client Hints / UA; если браузер скрыл модель — поле один раз + localStorage.
- Дубли: merge token↔fingerprint, collapse same UA+IP+type, dedupe при GET `/api/admin/sessions`.
- Accept-CH для `Sec-CH-UA-Model`. MFA 2 мин + resend, глаз пароля — без изменений.

### 2026-07-20 — Админка MFA: модель телефона / имя ПК, глаз пароля, 2 мин + resend

- Устройства: телефон — модель (Client Hints / UA); ПК — было имя компьютера (отменено → снова «ПК»).
- Логин: переключатель видимости пароля.
- MFA: TTL **2 минуты**, `POST /api/auth/admin/mfa/resend`.
- Деплой: `admin-ui` + `deploy_stable.py`.

### 2026-07-20 — Админка: MFA по почте + trusted devices + один URL

- Вход: пароль → код на `ADMIN_MFA_EMAIL` (`silent27@bk.ru`) → JWT с серверной сессией (`jti`). Запомненное устройство (`device_token`) пропускает MFA.
- Меню щита у логотипа: активные сессии и trusted devices, отзыв (DELETE `/api/admin/sessions|devices`).
- **Только** `Host: ADMIN_PUBLIC_HOST` (`132-243-234-162.nip.io`): UI + `/api/admin/*` + `/api/auth/admin/*`. Tunnel `10.66.66.1` для админки → **404** (клиентский VPN API через tunnel без изменений).
- UI: «Запомнить логин» / «Запомнить это устройство», шаг ввода кода.
- Env на VPS: `ADMIN_MFA_EMAIL`, `ADMIN_PUBLIC_HOST`. Деплой `deploy_stable` + `restore_api_container` (mkdir перед `docker cp` для новых пакетов).
- **Следствие для PC:** пункт «Админ-панель» открывает **публичный nip.io** (+ bypass при VPN). Tunnel `/dashboard` → 404.
### 2026-07-17 — PC: админка «через время» снова не открывается при VPN

- В логе нормален `[WG] Bypass API: 132.243…` — это для app API/peer, **не** для браузерной админки.
- При VPN+whitelist браузер на **nip.io** идёт мимо туннеля → отваливается; рабочий URL только `http://10.66.66.1:8000`.
- Усилен `open-admin-panel`: пока full VPN жив — всегда tunnel (не откат на nip.io при флапе wdtt); probe `/health`; подпись в меню «только 10.66.66.1 — не nip.io».

### 2026-07-17 — Android TV/Android 9 (Ugoos TOX1): bootstrap не стартует

- **Железо:** Ugoos TOX1, Amlogic S905X3, Android 9 — типичный кейс «временный VPN не поднимается».
- **Корень:** `libclient.so` с NDK **API 29** на API 28 падает (linker `android_get_device_api_level`, код 1); на 32-bit ещё SIGSYS код 159 (Go <1.26.3).
- **Баг в пайплайне:** Windows `build_android_go.bat` уже API 24 + Go 1.26.3, а **ночной OTA** `backend/build-agent/build_android_go.sh` всё ещё собирал с **android29** → release/OTA для приставок оставался сломанным.
- **Фикс:** `build_android_go.sh` = API 24 + `GOTOOLCHAIN=go1.26.3`; детект Ugoos/TOX/Amlogic в `DevicePlatform`; подсказки по кодам 1/159 в логе.
- **Дальше:** пересобрать libclient + debug/release APK и отдать пользователю / OTA (после `build_android_go` + assemble).

### 2026-07-17 — PC: админка при VPN + белые списки → tunnel, не nip.io bypass

- **Почему ломалось:** старый «фикс» открывал `https://nip.io` и ставил **bypass мимо VPN**. На Wi‑Fi/LTE с белыми списками ISP режет публичный nip.io вне туннеля → админка недоступна. Через VPN на тот же public IP — hairpin/timeout.
- **Как на Android:** API/админка при VPN → `http://10.66.66.1:8000` (DNAT на api). Пользователь уже подтвердил `/dashboard` через tunnel.
- **Фикс PC:** `open-admin-panel` / `get-admin-panel-url` — VPN ON → tunnel `/dashboard`, VPN OFF → public nip.io; **без** `ensureNipIoBypassRoutes` для админки. Подпись в меню: «при VPN: 10.66.66.1:8000».
- Файлы: `pc/src/main/main.js`, `tunnelApi.ts`, `MainScreen.tsx`. Нужна пересборка/debug PC.

### 2026-07-17 — Админка: пик онлайна на дашборде

- Карточка «Онлайн»: вместо «подключений активно» — **максимум: N** (all-time peak concurrent VPN).
- Хранение в `app_settings` (`peak_online_devices`, `peak_online_at`); обновление при `set_device_online` / connect и при `GET /api/admin/stats`.
- Файлы: `app/services/peak_online.py`, `admin.py`, `vpn_service.py`, `vpn.py`, `DashboardPage.tsx`.

### 2026-07-17 — Автокапча при error 10 шла с n=63 + VK домены .ru

- **Баг:** VK Calls `error_code=10` → Go `falling back to legacy` **внутри** процесса с полным n=63 (шторм капчи). Запасные 9 воркеров только при старте с `vk-auth-mode=legacy`.
- **Фикс:** in-process legacy из vkcalls **запрещён**; сигнал `LEGACY_ESCALATE_CAPTCHA` → хост перезапуск auto/manual с **n=9**.
- **Домены:** приоритет `api.vk.ru` / `id.vk.ru` / `domain=vk.ru` / join `vk.ru/call/join` (без api.vk.com в ротации Go).

### 2026-07-17 — PC: интернет пропадал после Bypass/Update (full tunnel)

- **Симптом:** воркеры 63/63, интернет был → после `Bypass API chunk Command failed` / `Tunnel API timeout → public` сеть отваливалась.
- **Причина:** `route delete` до успешного `add` + параллельные bypass (OTA Update ×N) сносили /32 peer+VK → blackhole при `0.0.0.0/1+128.0.0.0/1`.
- **Фикс:** upsert (change/add, delete только чужой next-hop); mutex на bypass; не сбрасывать физ. шлюз до stop WG; throttle public bypass 3с.

### 2026-07-17 — Flood control: каскад VKCalls → авто-капча → ручная

- **Почему «фикс не работал»:** коммит flood (2026-07-12) намеренно **запрещал** legacy fallback при `error_code=9`, чтобы не было шторма капчи при n=63. Итог: bootstrap/main зависали на flood, запасные режимы не включались (`floodCount` на Android был мёртвый).
- **Сейчас:** Go по-прежнему не падает в legacy внутри процесса; пишет `FLOOD_ESCALATE_CAPTCHA`. Хост (PC Electron + Android) при timeout/flood перезапускает с **auto (n=9)** → при провале **manual**. Throttle VK Calls усилен (PC ~3.5–5.5с, Android 4–7с; flood cooldown 8–12с).
- Нужна пересборка `wdtt-client` / `libclient` + debug/release клиентов.

### 2026-07-17 — Android 9: bootstrap — два бага libclient (API29 linker + Go 1.26 SIGSYS)

- **Симптом:** временный интернет для входа не поднимается на Android 9 (Smart TV / эмулятор API 28).
- **Баг 1 (код 1):** `CANNOT LINK … android_get_device_api_level` — NDK `*-android29-clang`. **Фикс:** API **24**, `minSdk=24` (`6df817e`).
- **Баг 2 (код 159):** после фикса linker — `libclient завершился (код 159)` сразу. **159 = SIGSYS**: Go **1.26.0–1.26.2** на **32-bit** Android 8–10 пробует `futex_time64`, zygote seccomp убивает процесс ([go#77621](https://github.com/golang/go/issues/77621)). Эмулятор `ABI=x86` / TV `armeabi-v7a` — под ударом; arm64 не затронут этим багом.
- **Фикс:** в `build_android_go.bat` `GOTOOLCHAIN=go1.26.3` + пересборка всех ABI. Перед debug/release всегда `build_android_go.bat`.

### 2026-07-17 — PC: после OTA/ошибки WG — вылет на пустой логин + зависание входа

- Логи пользователя с **debug** (`build-debug-135003`), не release. «Админ-панель» — кнопка для `profile.is_admin` (с ~1.0.147), не новая.
- OTA `silentVpnWipeAll` сносил `%APPDATA%\Silent VPN` → токены и «Запомнить».
- `device/register` при сетевой ошибке делал `clearTokens()`.
- Фикс: OTA wipe без AppData; clearTokens только на 403/409; вход разрешён если bootstrap WG упал (public HTTPS).

### 2026-07-16 — PC: первый запуск после OTA — WG fail + orphan wdtt/консоль

- После install служба `wg-turn` снесена; `runAfterFinish` сразу стартует клиент → первый connect гоняется раньше готовности WG; `wdtt` без `windowsHide` всплывает отдельно.
- Фикс: stamp `post-install.stamp` + пауза 2.5с и warm runtime; kill orphan wdtt на старте; `windowsHide` на wdtt/UAC; retry `runWgInstall` через 2с.

### 2026-07-16 — PC OTA: 100% → закрытие, установщик не открывался

- **Не integrity** (только VPN connect).
- **Корневая причина:** клиент `requireAdministrator` + NSIS `customInit` с `taskkill /IM "Silent VPN.exe" /T`. Setup стартует как child → `/T` убивает сам установщик.
- **Фикс клиента:** bat в `%TEMP%` — sleep ~3с после `app.exit`, потом `start` Setup; лог `%TEMP%\silent-ota-launch.log`.
- **Фикс NSIS:** `taskkill` без `/T` в `installer.nsh` (для следующих релизов на сервере).

### 2026-07-16 — Android OTA: прогресс 0% на Android 11–12

- **Симптом:** шкала/проценты зависают на 0%, потом сразу установка; на Android 16 ок. Скачивание работало.
- **Причины:** (1) hop `withContext(Main)` на каждый chunk в цикле чтения; (2) нет `Content-Length` у StreamingResponse + не использовался `size` из `/updates/check`.
- **Фикс:** прогресс с IO + throttle ~120 мс; `expectedSize = info.size`; backend выставляет `Content-Length` из manifest size.

### 2026-07-16 — PC OTA: после 100% клиент закрывался, установщик не открывался

- **Причина:** `shell.openPath(setup.exe)` + `app.quit()` — установщик оставался в дереве процессов Electron и убивался вместе с клиентом.
- **Фикс:** `spawn(detached+unref)` → fallback `cmd /c start "" path` → потом `app.exit`. NSIS успевает стартовать (UAC) до выхода.

### 2026-07-16 — PC: captcha domain vk.com→vk.ru + WG после капчи

- Redirect URI: `id.vk.com`→`id.vk.ru`, `domain=vk.com`→`domain=vk.ru` (`captchaRedirectUri.js`) — ручное окно грузилось медленно из‑за .com.
- Пока капча в WebView — **не ставим WG** (иначе full-tunnel рвёт загрузку id.vk.ru → авто то работает то нет); после CAPTCHA_RESULT — `pendingWgAfterCaptcha`.
- ConfigSync: не логировать ECONNABORTED/ETIMEDOUT; 10с quiet после капчи (tunnel-only).

### 2026-07-16 — PC: manual captcha без AUTO + Update без ложного Network Error

- **Баг:** в PC Go не было `case "manual"` (на Android был) → при «Ручная» сначала жгли AUTO 30с, потом окно manual с мёртвым session_token (вечная загрузка, нельзя кликнуть).
- **Фикс:** `solveCaptchaBySelectedMode` — сразу `CAPTCHA_SOLVE|manual` как на Android; manual-окно `alwaysOnTop` + show сразу.
- **Update:** `checkForUpdate` при `null` от main IPC больше не падал в axios public → ложный `Network Error` при VPN.
- `captchaInProgress` ставится сразу в очередь CAPTCHA_SOLVE (пауза ConfigSync/Update).

### 2026-07-16 — PC: откат ломающего captcha-prepare + правильный фикс таймаутов

- **Откат:** агрессивный `ensureCaptchaNetworkReady` / DNS-wait / timeout 50s ломали **автокапчу** (0 workers, connect timeout). WebView снова как раньше (auto 28s), плюс только retry `-105` + `clearHostResolverCache` на retry; manual show/focus.
- **Connect timeout:** legacy (auto/manual) ждёт VPN **120с** (`connectWaitTimeoutForAuth`), не 45с — капча+WG не укладывались.
- **ConfigSync/Update spam:** пока `captchaInProgress && !wgApplied` — API на паузе (без `ECONNABORTED`×N); sync-state не логирует `CAPTCHA_BUSY`.
- Go captcha timeouts: auto 30s / manual 90s. VK Calls не трогали.

### 2026-07-16 — Авто/ручная капча: только 9 воркеров (запасной режим)

- **Проблема:** при режиме «Авто капча» / «Ручная» libclient поднимал те же 63 потока, что и VK Calls → десятки параллельных капч.
- **Правило:** VKCalls → полный n (дефолт 63). Legacy auto/manual → **ровно 9** (1 группа).
- **PC:** `resolveWorkerCount` + `workerLimits.effectiveConnectWorkers` + Go `vk-auth-mode=legacy` clamp; UI подписи «Запасной режим: 9 воркеров».
- **Android:** `resolveWorkersForLibclient` / `PrepareVpnConnect` / `WdttTunnelManager` + Go clamp; те же подписи в меню.
- Тесты: PC `workerLimits.test.js` (в `npm test` 24/24); Android `LEGACY_CAPTCHA_WORKERS` в `HashChannelHelperTest`.

### 2026-07-16 — PC + Android: защита целостности клиента (anti-tamper)

- **Цель:** усложнить подмену/пересборку клиентов без поломки VPN-логики, TrustAll/cleartext `10.66.66.1`, debug и OTA/sideload. Play Integrity **не** делали (hard-fail сломает раздачу вне Play).
- **Android:** `AppIntegrity` — release-only проверка SHA-256 подписи APK (`RELEASE_CERT_SHA256` из keystore на gradle) + SHA-256 `libclient.so` по ABI (из `jniLibs` на сборке). **Обязательно** `packaging.jniLibs.keepDebugSymbols += "**/libclient.so"` — иначе AGP `strip*DebugSymbols` переписывает ELF (хеш ≠ pin) → «VPN-модуль изменён или повреждён». Вызов: `SilentApp.onCreate` (фон), `LibClientBinary` перед exec, `MainViewModel.connect` / `ensureBootstrapVpn`. Debug — полный skip. ProGuard: убран blanket `-keep com.silent.vpn.**`, точечные keep + `-allowaccessmodification`.
- **PC:** `integrity.js` + `integrityHashes.js` (генерируется `scripts/gen_integrity_hashes.js` в `build-installer.bat` / `build-debug.bat` после go build) — перед spawn `wdtt-client.exe` в packaged release. Soft-hints (asar unpacked / ELECTRON_RUN_AS_NODE). `ignore-certificate-errors` **не трогали** (нужен для self-signed / паритет Android).
- Fail mode: отказ **нового** VPN connect + понятное сообщение; уже поднятый туннель не рвём. Compile debug Kotlin — OK; PC mismatch smoke — OK.
- **Юнит-тесты (2026-07-16):** Android `IntegrityCrypto` + `IntegrityCryptoTest` — push `76f3dab`. PC `test/integrity.test.js` — push `ba98e04` (`npm test` 21/21). Instrumented smoke `AppIntegrityInstrumentedSmokeTest` — push `b57b94b`.

### 2026-07-16 — Backend: анти-абуз регистрации (временные почты + whitelist + rate limit по IP)

- **Повод:** аудит показал, что `/auth/register` не имел никакой проверки домена email (только формат `EmailStr` + уникальность в БД) — пользователь зарегистрировался с `@suahi.com` (disposable-домен temp-mail.org). Проверка внешними базами: risk-score 91/100, но в самом популярном pip-блоклисте `disposable-email-domains` (7981 доменов) этого конкретного домена **не было** — временные почтовые сервисы генерируют новые домены быстрее, чем блоклисты успевают их подхватывать. Поэтому одного блоклиста недостаточно — нужен строгий **whitelist**.
- **Три слоя защиты в `POST /auth/register` (`app/api/auth.py`):**
  1. **Rate limit по IP** — `app/services/rate_limiter.py`, Redis `INCR`+`EXPIRE` (fixed window), дефолт `REGISTER_RATE_LIMIT_MAX=8` попыток за `REGISTER_RATE_LIMIT_WINDOW_MINUTES=30` (оба — в `config.py`, переопределяются через `.env`, деплой без правок кода). IP — `X-Real-IP`/`X-Forwarded-For` (за nginx) с фолбэком на `request.client.host` (прямые запросы через WG tunnel API). **Fail-open**: если Redis недоступен — не блокируем регистрацию (проверено).
  2. **Disposable-блоклист** — пакет `disposable-email-domains` (requirements.txt, обновляется через `pip install -U` на каждый деплой/пересборку образа, ~8000 известных доменов), проверка домена и всех род. суффиксов (защита от поддоменов).
  3. **Whitelist разрешённых доменов** — `settings.ALLOWED_EMAIL_DOMAINS` (`app/config.py`): если список не пуст — регистрация разрешена **только** с этих доменов. Дефолт: Gmail, Mail.ru/Yandex-семейство, Outlook/Hotmail/Live, iCloud, Yahoo, Proton, Rambler, VK, GMX, AOL, Zoho, Tutanota, mail.com. Пустой список в `.env` = whitelist выключен (остаётся только disposable-блоклист).
- Логика домена: `app/services/email_validation.py` (`validate_registration_email_domain`) — сначала disposable, потом whitelist (если задан); ошибки — понятный русский текст в `HTTPException(400)`. Лимит — `HTTPException(429)`.
- **Деплой:** нужен `pip install -r requirements.txt` в контейнере (новая зависимость `disposable-email-domains`) — обычный `deploy_stable.py`/`deploy_api.py` это делают. Redis уже поднят в docker-compose (`redis` сервис), просто раньше не использовался приложением — теперь первый живой юзкейс.
- Протестировано локально (временный venv, не коммитился): `suahi.com` → блок (whitelist), `mailinator.com` → блок (disposable), `gmail.com`/`mail.ru` → пропуск, rate limiter fail-open без Redis подтверждён.
- Файлы: `app/config.py`, `app/services/email_validation.py` (новый), `app/services/rate_limiter.py` (новый), `app/api/auth.py`, `requirements.txt`, `.cursor/APIS.md`.
- **Деплой на прод выполнен 2026-07-16** (`python scripts/deploy_stable.py` + `npm run build` admin-ui): `health OK`, `admin: 200`, DNAT OK. В контейнер установлены `disposable-email-domains` (7981 доменов) + `redis`. Живая проверка:
  - `@suahi.com` → 400 «только с популярных почтовых сервисов» (whitelist)
  - `@mailinator.com` → 400 «временные / одноразовые»
  - `@mail.ru` → 201 «Регистрация успешна»
  - rate-limit: после 8 попыток с одного IP → 429; тестовые юзеры удалены из БД (`DELETE 6`)
- `deploy_stable.py` / `deploy_api.py` / `restore_api_container.py` обновлены: `pip install … disposable-email-domains redis` при каждом деплое (чтобы пакет не пропадал после recreate).
- **Не запушено** — ждать явной команды «пуш».

### 2026-07-16 — Landing: откат лишнего Smart TV-контента, новый заголовок гайда

- **Убран отдельный раздел «06 Smart TV» из гайда** (и пункт в TOC) — по фидбэку избыточно, поддержка TV уже понятна из карточки на главной. Удалён неиспользуемый CSS (`.demo-tv-frame`, `.demo-tv-screen`, `.demo-tv-stand`, `.demo-toggle.is-focused`) и JS (`runTv`)
- **Карточка Android на главной вернута к исходному виду** — убрана заметка «Тот же файл — для Android TV и Smart TV» (и её CSS `.dl-tv-note`)
- **Hero-текст на главной** дополнен: «Один аккаунт — компьютер, телефон и смарт ТВ» — единственное упоминание TV на сайте вместе с карточкой `04` в `features`
- **Заголовок гайда переименован**: «От скачивания до первого VPN» → «Быстрый старт с Silent VPN» (звучало неестественно)
- Кэш-бастинг `guide.css`/`guide.js` бампнут до `?v=4`
- Файлы: `guide.css`, `guide.js`, `index.html`

### 2026-07-16 — Landing: убраны кэш-артефакты + добавлена поддержка Smart TV

- **Кэш-баг**: пользователь всё ещё видел старый текст с размерами тумблера в подписях под демо — `guide.css`/`guide.js` подключались без версии, браузер держал старые файлы в кэше. Добавлен `?v=3` к обоим подключениям в `index.html` — решает раз и навсегда для будущих правок (бампать версию при каждом деплое статики)
- **Smart TV — реальная фича клиента** (Android `DevicePlatform.kt`: `leanback`/`FEATURE_TELEVISION` детект, `tv_banner.xml`, `LEANBACK_LAUNCHER` intent-filter, bootstrap-сессия 3 мин на TV vs 2 мин на телефоне) добавлена на лендинг:
  - Главная: 4-я карточка в `features` («Работает на Smart TV»), заметка под карточкой скачивания Android («Тот же файл — для Android TV и Smart TV»), grid `features` на `auto-fit` под произвольное число карточек
  - Гайд: новая секция `06 Smart TV` с TV-мокапом (widescreen-рамка + подставка, класс `.demo-tv-frame`/`.demo-tv-stand`) и отдельным демо `runTv` в `guide.js` — вместо мышиного курсора фокус-кольцо на тумблере (`.demo-toggle.is-focused`, чёрное кольцо 6px) имитирует навигацию пультом (стрелки + «ОК»)
- Файлы: `guide.css`, `guide.js`, `index.html`

### 2026-07-16 — Landing: гайд — правильный спиннер на тумблере + человеческий текст

- **Баг «чайка вместо змейки» исправлен**: кольцо-спиннер вращалось по контуру всей вытянутой таблетки (120×60) — на такой форме дуга подсветки визуально «летит» диагональю. Перенёс спиннер на круглый бегунок (48px, класс `.demo-knob-spin` внутри `.demo-toggle-knob`, `is-connecting` вместо `is-spinning`) — теперь чистое вращение кольца вокруг круга, проверено скриншотами Playwright (`toggle_connecting.png`/`toggle_on.png`, локально, не коммитились)
- **Весь текст гайда переписан** — убраны технические описания вёрстки для пользователя («логотип по центру», «тумблер 120×60», «активная — чёрная», «подпись в клиенте: …»); тексты в `index.html` (hero, 5 секций, footer CTA) и подписи-caption в `guide.js` заменены на обычные человеческие формулировки о том, что и зачем делает пользователь
- Файлы: `guide.css`, `guide.js`, `index.html`

### 2026-07-16 — Landing: SPA-инструкция с интерактивными демо

- На [silentvpn3.github.io](https://silentvpn3.github.io/) гайд `#guide`: демо сверстаны по реальному LoginScreen PC/Android (логотип 56×16 + SILENT VPN по центру, серый «Подключение…» → зелёный «Канал готов. Осталось M:SS…», вкладки Войти/Регистрация с чёрным active, кнопка чёрная / «Ожидание канала…» пока не ready; вход = тот же экран без промо; тумблер 120×60; исключения с текстом клиента)
- AI-картинки с чужим логотипом убраны — только HTML/CSS mockups. Файлы: `guide.css`, `guide.js`, правки `index.html`

### 2026-07-16 — MCP + дизайн-стек: Playwright/Firecrawl подключены, ui-ux-pro-max v2, новые design-sources

- **MCP (`C:\Users\silent27\.cursor\mcp.json`, создан):** `playwright` (`npx @playwright/mcp@latest` — браузерная автоматизация/скриншоты, полностью бесплатный) и `firecrawl` (hosted `https://mcp.firecrawl.dev/v2/mcp` — keyless free tier: scrape/search/interact без ключа; `branding`-формат вытаскивает цвета/шрифты сайта-референса). Требуется перезапуск Cursor для загрузки серверов
- **codebase-memory-mcp v0.9.0 подключён** (официальный `install.ps1` → бинарник `C:/Users/silent27/.local/bin/codebase-memory-mcp.exe`, авто-запись в `mcp.json`): локальный граф знаний кодовой базы (tree-sitter + Hybrid LSP: Python/TS/Kotlin/Go/Swift), 15 инструментов — `get_architecture`, `trace_path`, `search_graph`, `detect_changes` (blast radius по git diff), `semantic_query`, dead code. 100% локально, без ключей. **Silent-Project уже проиндексирован**: 6254 узла / 28888 рёбер (все 4 ветки: backend+pc+android+ios). База: `~/.cache/codebase-memory-mcp/`. Инсталлер также сконфигурировал Gemini CLI. Использовать для вопросов «кто вызывает X», «что сломает правка Y» — вместо серии grep
- **Не подключены (осознанно):** Perplexity MCP — API платный (нужен ключ с балансом), поиск уже есть встроенный; Glif MCP — нужен токен + кредиты, дублирует наши `imagegen-frontend-*`/`design` skills (репозиторий вообще в архиве)
- **ui-ux-pro-max обновлён до v2** (`npx ui-ux-pro-max-cli init --ai cursor --global --force`): 67 стилей, 161 палитра, reasoning engine (161 industry-правило), design-system generator (`scripts/search.py --design-system`), 22 стека. Старые imagegen/design skills оставлены — генерацию картинок не заменяем, Glif хуже
- **Правила design-sources (проектное + глобальное) переписаны:** добавлены `21st.dev` (готовые React/Tailwind компоненты), `motion.dev` (production-анимации), `saaslandingpage.com` (референсы лендингов); прописаны обязательные связки: UI → `ui-ux-pro-max` reasoning → `impeccable`/`soft-skill`; картинки → `imagegen-frontend-*` → `image-to-code-skill`; скрейпинг референсов → Firecrawl MCP; визуальная проверка → Playwright MCP

### 2026-07-14 — PC: timeout 15s на payments/init (браузер не открывался)

- Симптом: клик по тарифу → `timeout of 15000ms exceeded`, браузер не открывается
- Причина: без флага main VPN renderer ходил xhr на nip.io (15с) — часто таймаут; `openExternal` даже не вызывался
- Фикс: все API через main IPC (`tunnelApiRequest`): WG→`10.66.66.1`, иначе public HTTPS по IP; timeout 30с

### 2026-07-14 — PC: оплата при VPN + тарифы в тёмной теме

- Симптом: «Месяц» → ожидание → ошибка; на сервере платежи остаются `pending` (init OK, YuMoney notify нет)
- Причина: при full-tunnel VPN браузер не достучался до YuMoney / success nip.io
- Фикс PC `open-external`: перед открытием ссылки оплаты — bypass-маршруты для `yoomoney.ru` / `money.yandex.ru` / nip.io (DNS с таймаутом 2с)
- Тарифы в тёмной теме: белый фон / чёрный текст (`primaryBtnBg/Fg` на PC+Android; превью админки то же)
- Нужна пересборка PC (и при необходимости Android), чтобы увидеть фикс

### 2026-07-14 — MTProto на primary 185.182 не работает (блок Telegram DC)

- Theme кратко указывал на `185.182.65.175:8443`, клиенты: «прокси недоступен»
- `mtg doctor` / TCP: на primary **DC1–DC5 timeout**; Cloudflare OK. На Улье DC1–5+203 OK
- Вывод: хостер primary режет Telegram DC — HTTP/SOCKS для сайтов ок, MTProto exit там невозможен
- Theme возвращён на рабочий Улей: `tg://proxy?server=10.66.66.1&port=8443` (VPN ON)
- Для MTProto на отдельном VPS нужен хостинг с доступом к Telegram DC

### 2026-07-14 — Theme MTProto → новый primary proxy + cleanup football .env

- Причина старого ускорителя: в `app_settings.theme` было `tg://proxy?server=10.66.66.1:8443` (mtg на Улье)
- Обновлено на `185.182.65.175:8443` (MTProto на dedicated primary)
- Football `.env`: оставлены только `API_FOOTBALL_PROXY_URL` + `GITHUB_HTTPS_PROXY` → primary HTTP `:3128`

### 2026-07-14 — 502 админки: восстановление после recreate api

- Причина: `docker compose up -d api` / recreate сбросил `docker cp` файлы; частичный cp `models/__init__.py` без hive-моделей → API падал → nginx 502
- Фикс: `docker cp /opt/silent-vpn/backend/app/. → контейнер` + restart; health/admin снова **200**
- `deploy_proxy.py`: только **restart** (не recreate) + после proxy-файлов полный sync `app/` с хоста + health gate

### 2026-07-14 — Прокси-флот: сайты → отдельный proxy-VPS (не Улей)

- Улей/админка только **управляют** отдельным прокси; VPN-соты не используются как exit для сайтов
- Primary `185.182.65.175`: **HTTP `:3128`** (`top10proxy`) + **SOCKS5 `:1080`** + **MTProto `:8443`** (mtg `simple-run`) + agent `:9101`
- `attached` = SSH на сайт → снос только старого proxy (whitelist) → `.env` на primary HTTP → PM2 reload; **не** ставим SOCKS на сайт
- SSH порт как указан (для Jino **49452** без fallback на 22)
- Футбол `475a0aa5ad19.vps.myjino.ru:49452`: env → `http://…@185.182.65.175:3128`, PM2 online; проверка curl через proxy → `185.182.65.175`
- Деплой: `admin-ui` build + `python scripts/deploy_proxy.py`; в `.env` Улья `PROXY_HTTP_USER/PASS/PORT`

### 2026-07-14 — Прокси attached «футбол»: ошибка SSH порта 49452

- ~~Причина считали порт 49452 ошибочным~~ — **неверно**: у Jino SSH именно `:49452`
- Актуальная схема — см. запись выше (сайт → primary proxy)

### 2026-07-14 — Прокси-флот: тексты + health/ротация порта

- UI/доки: убраны упоминания «футбольный» — подключается **любой** VPS (`dedicated` / `attached` safe)
- Фоновый `proxy_health_loop` (каждые 60с): probe agent + TCP к SOCKS; после 3 фейлов → `POST /v1/rotate-port` на агенте (смена порта, ufw, restart silent-socks); без агента → `blocked`
- `GET /api/admin/proxy/nodes/active` — пул endpoint’ов для сайтов/клиентов
- Деплой: `python scripts/deploy_proxy.py` (+ обновление agent на нодах)

### 2026-07-14 — Прокси-флот (SOCKS): админка + dedicated VPS

- Новый раздел админки **«Прокси»** (`/proxy`): подключение VPS по IP + SSH пароль + порт (22)
- Роли: `dedicated` (чистый proxy-VPS) / `attached` (VPS с другими сервисами — **safe cutover**: только whitelist proxy-софта, не трогает nginx/docker/сайт/БД/`/var/www`)
- Стек на ноде: **sing-box SOCKS5** (`silent-socks`) + **proxy-agent** `:9101`
- Backend: `proxy_nodes`, `/api/admin/proxy/*`, `proxy_provision_service`, `scripts/deploy_proxy.py`
- VPN/Улей/wdtt **не менялись** (только additive API + admin-ui)
- Primary нода: `185.182.65.175:1080` (user `silent`) — endpoint в админке кнопкой «Endpoint»
- Деплой: `cd backend; npm run build` в `admin-ui` → `python scripts/deploy_proxy.py`

### 2026-07-14 — Telegram MTProto proxy: не ускоритель поверх full VPN

- С `server=10.66.66.1` прокси = лишний FakeTLS-хоп на том же exit → медиа медленнее, чем просто VPN
- Вынос на public IP + exclude: в РФ Telegram без VPN обычно не нужен как отдельный путь — продукт = full VPN; «ускоритель» не ship'им в release (остаётся debug-эксперимент / можно убрать)
- Вывод: для Silent VPN Telegram должен идти через VPN; отдельный mtg-прокси поверх туннеля не даёт выигрыша

### 2026-07-14 — Telegram proxy: медиа крутится / не качается (DC 203 CDN)

- Симптом 1: скачивание сразу срывается → `cannot dial to 203 dc: no addresses`
- Симптом 2 (после `allow-fallback-on-unknown-dc=true`): крутится без прогресса — fallback на DC 3/5, CDN-медиа оттуда не отдаётся
- Корень: CDN DC **203** (`getProxyConfig` → `91.105.192.110:443`) mtg узнаёт только через **auto-update** (нужен mtg **≥2.2.x**)
- Фикс на VPS: mtg **2.2.8**, `auto-update=true`, `allow-fallback-on-unknown-dc=false`, `dns=https://1.1.1.1`; в логах `found 91.105.192.110:443 address for DC 203`; `mtg doctor` → DC 203 ✅
- `backend/scripts/deploy_telegram_proxy.py` — default `MTG_VERSION=2.2.8`, те же флаги
- **Проверить:** VPN + прокси → скачать файл/видео

### 2026-07-14 — Telegram MTProto «прокси недоступен»: clock skew + tunnel GW

- Симптом: прокси добавляется, статус «недоступен» (и на `132.243…`, и на `10.66.66.1`)
- **Главная причина (логи mtg):** `invalid faketls client hello` / `incorrect timestamp` — часы VPS отставали на **~4 минуты** (`System clock synchronized: no`). FakeTLS допускает по умолчанию только ~3–5с
- Сопутствующее: тема переведена на `server=10.66.66.1` (трафик через VPN); `10.66.66.1/32` на `lo`; REDIRECT на wdtt0 убран (ломал dest→`10.66.0.0`)
- Фикс: `date -s` по HTTP Date с 1.1.1.1; chrony; mtg `config.toml` с `tolerate-time-skewness = "10m"`, `prefer-ip = only-ipv4`, `defense.blocklist.enabled = false` (firehol_level1 режет RFC1918/10.66.x)
- Проверка: VPS `date -u` == Cloudflare Date; mtg `active`; `*:8443` слушает
- **Проверить сейчас:** VPN ON → удалить старый прокси в Telegram → «Ускорить Telegram» заново

### 2026-07-14 — Landing: telegram.me вместо t.me (блокировка) + промо «2 месяца бесплатно» вместо trial 3 дня

- **На будущее — `t.me` может быть заблокирован (РФ), `telegram.me` — рабочая альтернатива:** проверка показала `https://t.me/silentvpn3` → 403 Forbidden, а `https://telegram.me/silentvpn3` открывает канал нормально (тот же канал, тот же username — просто другой домен-алиас Telegram). Ссылка в самой группе/канале уже стояла как `telegram.me`, поэтому и работала там, а на лендинге была `t.me` → не открывалась у части пользователей. **Если где-то ещё всплывёт «не открывается ссылка на Telegram» — сначала проверить именно домен (`t.me` vs `telegram.me`), а не username/канал.**
- Заменено в `landing/index.html`: карточка канала + ссылка в футере (оба вхождения `t.me/silentvpn3` → `telegram.me/silentvpn3`)
- Промо на время теста: текст «3 дня trial бесплатно» в hero — зачёркнут (`.promo-old`, `text-decoration: line-through`), рядом — чёрный пульсирующий бейдж `.promo-badge` «Бесплатно 2 месяца — идёт тестирование» (монохромно, в стиле сайта, без чужих цветов); обновлён и `<meta name="description">`
- `landing/` — отдельный репозиторий (`github.com/silentvpn3/silentvpn3.github.io`, GitHub Pages) — деплоя не требует, паблишится сразу после push в `main`
- **Грабля с пушем:** `gh auth setup-git` (был вызван по ошибке в этом же тёрне) подставил глобальный `credential.helper` для `github.com` на аккаунт `footballpredictions` (нет прав на `silentvpn3/silentvpn3.github.io` → `Permission denied`). Фикс: `git config --global --unset-all credential.https://github.com.helper` (и `gist.github.com` аналогично) — возвращает обычный `git-credential-manager.exe`, который спрашивает нужный аккаunt интерактивно. **Для этого репо push всегда должен идти под аккаунтом `silentvpn3`, не `footballpredictions`** — если GCM всплывёт с выбором аккаунта, выбирать `silentvpn3`
- После push в origin оказались новые коммиты автообновления `releases.json` (от build-agent/OTA) — понадобился `git fetch` + `git rebase origin/main` перед повторным push (конфликтов не было, т.к. трогали разные части файла)
- Push `origin/main` (репозиторий `silentvpn3.github.io`) `22e289b..173a112`

### 2026-07-14 — UI-фикс тёмной темы + отмена ожидания оплаты (клиенты, без правок бекенда)

- **Баг тёмной темы (Android):** в `MenuSubscription` кнопки тарифов имели `containerColor = fg` (светлый в тёмной теме) и жёстко закодированный `contentColor = Color.White` → белый текст на белой кнопке. Фикс — `contentColor = bg` (тот же паттерн, что уже был у кнопки «Попробовать снова»), плюс явный `color = bg` на `Text` внутри `Row`. Файл: `android/app/src/main/kotlin/com/silent/vpn/ui/screens/MainScreen.kt`. `compileDebugKotlin` — `BUILD SUCCESSFUL`
- **Вопрос пользователя:** платёж с неверным CVC — ЮMoney показал отказ в браузере, а клиент продолжал крутить спиннер «ждём оплаты». Разобрано: это **не баг бекенда** — ЮMoney по своей архитектуре шлёт HTTP-уведомление (`/yumoney/notify`) **только при реальном зачислении денег**; отказы/отклонения банком/неверный CVC/3-D Secure fail — вообще не долетают до нашего вебхука, серверу физически нечего проверять и не о чём сообщать клиенту. Это структурное ограничение выбранного подхода «без API ЮMoney», а не то, что можно починить в `payment_service.py`
- **Смягчение UX (PC + Android, единый флоу):** раньше во время `waiting` не было способа выйти из ожидания — только 10 мин клиентского поллинга до `timeout`, либо 30 мин сервер-side TTL (`YUMONEY_PAYMENT_TTL_MINUTES`) до `expired`. Добавлена кнопка **«Отмена»** (`payment_cancel_button_text` — уже было в `ThemeResponse`/`ClientTheme`/`ThemeData`, но не использовалось в UI) прямо под спиннером `waiting` — сбрасывает `paymentState`→`idle` немедленно, без ожидания таймаута. Файлы: `android/.../ui/screens/MainScreen.kt`, `pc/src/renderer/pages/MainScreen.tsx`
- Изменения только клиентские (UI), бекенд не трогали — деплой backend не требуется. Пуш клиентов — по отдельному запросу пользователя

### 2026-07-14 — Баг-фикс: реальные платежи зависали на «ждём подтверждения» (YuMoney `sign` vs `sha1_hash`)

- Пользователь протестировал реальный платёж (15₽ на тестовых ценах) — деньги пришли (14.55₽ с учётом комиссии), но подписка осталась в статусе `pending`
- Причина: ЮMoney с **18.05.2026** перестали присылать `sha1_hash` вообще — теперь подписывают уведомления только новым параметром `sign` (HMAC-SHA256 по параметрам, отсортированным по алфавиту, URL-encoded RFC 3986, объединённым через `&`, секрет — ключ HMAC). Наш `payment_service.py` проверял только старый `sha1_hash` → все реальные нотификации получали `invalid_signature` → 400, хотя секреты кошельков были верными (пользователь их перепроверил — совпадали)
- Диагностика: логи `backend-nginx-1` показали реальные попытки доставки от ЮMoney (`77.75.157.43`/`77.75.155.211`/`77.75.155.213` — их IP уведомлений) с кодом 400; в логах `backend-api-1` — `WARNING payment notify: invalid signature`. ЮMoney делает 3 попытки: сразу, +10 мин, +1 час
- Фикс: `_verify_yumoney_sign()` (новый, основной) + `_verify_yumoney_sha1()` (legacy fallback) в `payment_service.py`; `_verify_yumoney_signature()` пробует оба. +6 юнит-тестов, воспроизводящих реальную форму нотификации (`sign` без `sha1_hash`) — **43/43 OK**
- **Грабля при деплое:** первый `docker cp` скопировал файл с сервера (устаревшую версию) в контейнер, а не свежий локальный — нужно **сначала `sftp upload_file`, потом `docker cp`** (обычный `deploy_api.py`/`deploy_stable.py` делают это правильно; при ручном точечном деплое через `docker_cp_and_restart()` — не забывать грузить файл на хост первым шагом)
- Живая проверка на проде после фикса: симулированное `sign`-уведомление реальным секретом на **обоих** кошельках → `status: completed`
- Push `origin/main` (`52c159c`); Android bump `1.0.155` → `1.0.156` + push `origin/android` (`6b99389`); PC — без изменений (уже актуален)
- Зависшие тестовые платежи пользователя (`silent_6b5e9e4feb0c38d77069b2fa07e2e011` и др.) должны закрыться сами через штатный ретрай ЮMoney (~1 час после первой попытки) теперь, когда фикс живёт на проде

### 2026-07-14 — Оплата YuMoney реализована (до 10 кошельков, единый флоу клиентов)

- Реализация по плану **`.cursor/PLAN_PAYMENTS_YUMONEY.md`** — подробности в разделе «Подписки и оплата» выше
- Backend: `config.py` (10 кошельков + секреты + tolerance + TTL), `models/payment.py` (`operation_id`/`paid_amount`/`promo_code`/`expired`), `payment_service.py` переписан целиком (кошельки, подпись, весь webhook-чеклист, идемпотентность), `api/payments.py` (`GET /status/{label}`, `GET /success-page`)
- Admin UI: `ThemePage.tsx` + `ClientPreview.tsx` — группа «Оплата» с превью состояний (тарифы/ожидание/успех/ошибка)
- **Единый флоу PC + Android:** `/init` → системный браузер (не WebView, не проксируем) → poll `/status/{label}` → состояния из theme-полей
- Тесты: `scripts/test_payment_unit.py` **37/37 OK** (venv создан/удалён локально для прогона — deps не в репо), `scripts/smoke_payments.py` готов для прод-проверки
- Push `origin/main` (backend), `origin/pc`, `origin/android` — все три ветки
- **Деплой на прод выполнен и проверен живыми кошельками (2026-07-14):**
  - `.env` на VPS: `YUMONEY_WALLET_1=410016158181311` (15 цифр — старый кошелёк, подтверждён пользователем как рабочий), `YUMONEY_WALLET_2=4100116281560655`, оба с реальными `YUMONEY_SECRET_1/2` из личных кабинетов
  - Т.к. `env_file: .env` в `docker-compose.yml` требует recreate контейнера для новых переменных — `docker compose up -d api` (recreate) → сразу `python scripts/deploy_stable.py` (restore кода из стабильного image + `fix_tunnel_dnat`), как предписано в разделе «Docker: код в контейнере»
  - Проверено после деплоя: `\d payments` — все новые колонки на месте; Улей/`admin/stats`/`users/me` продолжают отвечать 200 без регрессии
  - **Живой прогон обоих кошельков на проде:** 12 инициаций `/payments/init` (оба кошелька случайно выпадали), подпись каждого нотификейшена — секретом именно того кошелька → верно распознаётся; `sum=1`-атака (сумма 1₽ вместо 199₽) на обоих кошельках → `status=failed`, подписка не активируется; полный успешный платёж с реалистичной комиссией (~5%) → `status=completed`, повторная (replay) нотификация → `already_processed` (идемпотентность подтверждена)
- Публичный URL для HTTP-уведомлений (уже указан в обоих кошельках): `https://132-243-234-162.nip.io/api/payments/yumoney/notify`
- **Осталось:** релизы PC/Android с новым UI оплаты (код запушен в ветки `pc`/`android`, но `assembleRelease`/`build-installer` + OTA публикация не выполнялись)

### 2026-07-14 — VPS 502: deploy_api recreate без httpx/hive

- Не новый скрипт: штатный `deploy_api.py` сделал `compose up -d api` → старый image без `hive_cell`/`httpx` → админка 502
- Починка: `restore_api_container.py` + `pip install httpx paramiko` → health OK, `/admin/` 200
- В `restore_api_container.py` добавлен `pip install httpx paramiko` (как в deploy_stable)
- Push `origin/main` `e383cf8` (MSK + restore httpx); WIP github_release не пушил
- Дальше для правок админки/API: **`deploy_stable.py`**, не `deploy_api.py`

- Push `origin/pc` `6245433` — версия **1.0.156** (без bump)
- Перед установкой (`customInit`): kill процессов, снятие WG-службы, удаление папок `SilentVPN` / `Silent VPN` в Program Files, ProgramData, AppData всех Users
- Деинсталляция (`customUnInstall` + `customRemoveFiles`): то же + `$INSTDIR`; `deleteAppDataOnUninstall: true`
- Скрипт: `pc/build/silent-vpn-wipe.ps1`; Program Files\WireGuard (системный драйвер) не трогаем
- После очистки установка заново кладёт `ProgramData\SilentVPN\wireguard` (WG 1.1)

- Push `origin/pc` `ab99080` — версия остаётся **1.0.156**
- Реальный bypass: platform packs (Steam SDR CIDR) + learning remote IP → маршрут через физ. шлюз
- Список приложений: Desktop / Steam library / BlueStacks
- Dota «не удалось вычислить задержку» — закрыто live `GetSDRConfig` + refresh после WG

### 2026-07-12 — Android: убран кастомный DNS (LTE lookup timeout)

- Лог LTE: `lookup api.vk.me: i/o timeout` → `context canceled`
- Кастомный PreferGo/8.8.8.8 на мобильном DNS ломает резолв
- Фикс: `newVkDirectDialer` без Resolver (system DNS); ротация хостов VK остаётся
- Подтверждено LTE+Wi‑Fi; push `origin/android` `b7e2201` (без bump версии)

### 2026-07-12 — Android: LTE снова (DNS оператора first)


- Симптом после DPI-фикса: Wi‑Fi OK, мобильный интернет не коннектится
- Причина: форс только `8.8.8.8/1.1.1.1` — на LTE часто режут/sinkhole
- Фикс: DNS **сначала system (оператор)**, публичные — fallback; без LocalAddr

### 2026-07-12 — Android: откат LAN-bind (ломал connect)


- После Wi‑Fi DPI патча `LocalAddr` bind в dialer/TURN на Android → полный fail connect
- Фикс: публичный DNS **без** LocalAddr; TURN снова `defaultLocalUDPAddr`; flood не ротирует хосты
- Размер APK после `clean` меньше из‑за упаковки dex/кэша — не признак потери libclient (все ABI на месте)

### 2026-07-12 — Telegram MTProto «недоступен»: mtg IPv6


- Причина: `mtg` default `prefer-ipv6`, на VPS IPv6 unreachable → FakeTLS `cloudflare.com` fail (`cannot dial to the fronting domain`)
- Фикс на проде: `simple-run -i prefer-ipv4 -n 1.1.1.1`; то же в `deploy_telegram_proxy.py`
- Секрет/ссылка те же — в Telegram достаточно выкл/вкл прокси или подождать

### 2026-07-12 — VK Calls Flood control (error 9) → без legacy/капчи

- Лог: `kind=vk_api: error_code=9 Flood control, falling back to legacy` → капча (дыра как до 19c3c1e)
- Фикс PC+Android: kind=`flood`; **нет** legacy fallback **внутри Go**; retry + cooldown; PC global throttle
- **2026-07-17:** host-каскад auto→manual при `FLOOD_ESCALATE_CAPTCHA` / timeout (см. запись выше)

### 2026-07-13 — PC: исключения приложений реально работают (bypass)

- Было: меню только писало план в лог, сеть не менялась (нужен был WFP)
- Сейчас: для **любых** выбранных .exe — монитор remote IP процесса (+ детей) → host-route /32 мимо VPN
- Лог: `[Apps] bypass монитор…`, `[Apps] bypass +N IP`
- Debug: пересобрать `build-debug.bat`

### 2026-07-13 — PC: исключения — Steam / Desktop / BlueStacks


- Было: только ярлыки `Start Menu\Programs` → не видно Steam-игры (.url), Desktop, BlueStacks Android
- Фикс: Desktop + Start Menu + `.url` steam:// + Steam library (appmanifest) + BlueStacks `--package`
- Debug: `build-debug-*\win-unpacked\SilentVPN-Admin.bat`

### 2026-07-13 — Landing: PC 1.0.156 / Android 1.0.155 в index.html


- Причина «видит 150»: `releases.json` уже 156, а `INLINE_FALLBACK` в `index.html` залип на 1.0.150
- Фикс: `landing/` sync + push `22e289b` → silentvpn3.github.io

### 2026-07-13 — PC: wintun.dll + WG 1.1 → SCM 7024 (регресс)


- В `ProgramData\SilentVPN\wireguard` лежал `wintun.dll` рядом с wireguard 1.1 → служба падает
- Фикс: не копировать wintun для ≥1.0; удалять из ProgramData; installer Delete wintun.dll
- ProgramData больше не источник в pickBestWgSource

### 2026-07-13 — PC: NSIS ProgramData литералом (нет $COMMONAPPDATA)

- electron-builder makensis: нет `$COMMONPROGRAMDATA` и `$COMMONAPPDATA` → warning 6000 as error
- Фикс: `!define SILENT_WG_DIR "C:\ProgramData\SilentVPN\wireguard"`

### 2026-07-13 — PC: NSIS fix `$COMMONAPPDATA` (сборка Linux)


- Ошибка CI: `unknown variable/constant "COMMONPROGRAMDATA\…"` → warning as error
- В NSIS нет `$COMMONPROGRAMDATA`; нужен `$COMMONAPPDATA` (= `C:\ProgramData`)

### 2026-07-13 — PC 1.0.156: установщик чинит WG 0.5.3↔1.1 (push)

- `build/installer.nsh`: install/OTA — uninstall службы, MSI 1.1, ProgramData refresh
- Runtime `forceRefreshProgramDataFrom`; `SilentVPN-Admin.bat` в extraFiles
- Push `origin/pc` `1.0.156`

### 2026-07-13 — PC: установщик сам чинит WG 0.5.3↔1.1 (без Admin.bat)

- Проблема у пользователей на релизе: служба SCM 7024, залипший ProgramData 0.5.3
- `build/installer.nsh` (`nsis.include`): при install/OTA — uninstall службы, MSI 1.1 если нет PF, копия 1.1 → ProgramData
- Runtime: `forceRefreshProgramDataFrom` при elevated, если ProgramData старше бандла/system
- `SilentVPN-Admin.bat` кладётся рядом с exe (`extraFiles`) как запасной вариант
- Следующий `build-installer.bat` / OTA подхватит; версию не бампил — ждать «релиз»

### 2026-07-12 — PC 1.0.155: WireGuard 1.1 + Wi‑Fi VK Calls (проверено + push)



- WG: бандл/рантайм **1.1** (был 0.5.3 → SCM 7024); prefer Program Files; wintun optional; SilentVPN-Admin.bat
- VK Calls Wi‑Fi: public DNS + host failover (как Android 1.0.155)
- Alert WG: убран мёртвый «1.0.51+»
- Version **1.0.155** → `origin/pc`

### 2026-07-12 — PC: WG служба падает — бандл 0.5.3 vs системный 1.1


- С админом: install OK, но SCM **7024** «ошибка в среде» — служба сразу умирает
- Причина: Silent ставил `ProgramData\…\wireguard.exe` **0.5.3** при установленном драйвере **WireGuardNT 1.1**; код ещё требовал `wintun.dll` и игнорировал Program Files
- Фикс: prefer newest (bundled/system) ≥1.1; wintun опционален; `reuse` не залипает на старой версии; бандл/MSI → 1.1; `SilentVPN-Admin.bat` чистит службу и копирует 1.1 в ProgramData

### 2026-07-12 — PC: WG «служба не поднялась» = без админа (не DPI)


- Лог: `Success via VK Calls` ✓, но `WireGuardTunnel$wg-turn` 1060 / Access is denied
- Причина: debug exe реально **не elevated** (`TokenElevation=0`); служба WG ставится только с админом
- ConfigSync Network Error — следствие (нет туннеля к `10.66.66.1`)
- Фикс UX: явный лог elevation, Access Denied, fallback UAC; `Silent VPN (Admin).bat` копируется в win-unpacked; bat убивает старые процессы перед RunAs

### 2026-07-12 — Android 1.0.155: VK Calls Wi‑Fi DPI (проверено + push)


- Симптом: на Wi‑Fi → капча/connect timeout; на LTE OK. Лог: legacy `6287487` + `CAPTCHA_WAIT_REQUIRED` + WBV timeout
- Причина: ISP DNS poison / DPI на `api.vk.me` → VK Calls network fail → legacy → шторм капчи
- Фикс: публичный DNS `8.8.8.8`/`77.88.8.8`/`1.1.1.1`; ротация `api.vk.me`→`api.vk.ru`→`api.vk.com`; LAN dialer + WithDialer; network fail без legacy/капчи
- QA: Wi‑Fi OK на debug. Version **1.0.155** → `origin/android`. PC патч локально, bump отдельно

### 2026-07-12 — PC: устаревший текст ошибки WG «1.0.51»


- Alert при timeout: больше не «установите 1.0.51+» — это был мёртвый текст
- Реальная причина: служба `WireGuardTunnel$wg-turn` не поднялась (права/UAC)
- Лаунчер: `pc/Silent VPN (Admin).bat`

### 2026-07-12 — Android: убран «Обновить канал Telegram»

- Пункт меню удалён (старый TURN-refresh); в debug остаётся только «Ускорить Telegram» (proxy)
- `refreshTelegramChannel` из ViewModel убран

### 2026-07-12 — Android: Telegram debug-меню только в DEBUG

- «Ускорить Telegram» — **только** `BuildConfig.DEBUG`
- В release Telegram debug-пунктов нет

### 2026-07-12 — Telegram MTProto proxy (ускорение поверх VPN)

- VPS: `silent-tg-proxy` (mtg) на `:8443`, `python scripts/deploy_telegram_proxy.py`
- Theme: `telegram_proxy_url`, `telegram_proxy_menu_label`
- Меню «Ускорить Telegram» — **только debug** (Android/PC/iOS); в release скрыто
- Открытие: `tg://proxy?…` (не `https://t.me/proxy` — на PC иначе сайт скачивания)
- Не исключение приложения: VPN обязателен; proxy — режим Telegram через наш exit
- **server в ссылке = `10.66.66.1` (tunnel GW)**, не публичный IP — иначе hairpin через VPN даёт «прокси недоступен» (фикс 2026-07-14)
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
