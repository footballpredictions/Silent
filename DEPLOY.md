# Деплой backend (ветка `main`)

**Репозиторий:** `Silent-Project/backend/`  
**Шпаргалка Agent:** полный список deploy-файлов — **этот файл**. Индекс по всем веткам: `backend/.cursor/MEMORY_BANK.md` → «Деплой».

Секреты SSH: `Silent-Project/.env.deploy` или `backend/.env.deploy` (шаблон `scripts/.env.deploy.example`).

```powershell
pip install paramiko
cd backend
```

---

## Все файлы деплоя в этом репозитории

| Файл | Запуск | Что делает |
|------|--------|------------|
| `scripts/_deploy_common.py` | *(модуль)* | SSH, `.env.deploy`, upload — импортируется скриптами |
| `scripts/.env.deploy.example` | *(шаблон)* | Пример `DEPLOY_HOST`, `DEPLOY_PASS`, … |
| `scripts/deploy_helper.py` | `python scripts/deploy_helper.py <action>` | VPS: check / install / status / creds |
| `scripts/deploy_stable.py` | `python scripts/deploy_stable.py` | Полный деплой всех `app/**/*.py`, `ai/**/*.py`, `admin-ui/dist` |
| `scripts/deploy_api.py` | `python scripts/deploy_api.py` | Точечный API + admin-ui/dist |
| `scripts/deploy_vk_calls.py` | `python scripts/deploy_vk_calls.py` | VK Calls, VK ID, агент + admin-ui/dist |
| `scripts/deploy_config_sync.py` | `python scripts/deploy_config_sync.py` | ConfigSync / sync-state |
| `scripts/deploy_update_backend.py` | `python scripts/deploy_update_backend.py` | OTA API (без .exe/.apk) + admin-ui/dist |
| `scripts/deploy_wdtt_systemd.py` | `python scripts/deploy_wdtt_systemd.py` | wdtt-server как systemd на VPS |
| `scripts/install.sh` | на сервере / через `deploy_helper install` | Первичная установка Docker + clone |
| `scripts/gen_certs.sh` | на сервере | Перегенерация TLS |

**Не создавать** новые `deploy_*.py` вне `scripts/`.

---

## Куда на VPS

| Параметр | Значение |
|----------|----------|
| Путь backend | `/opt/silent-vpn/backend` (`DEPLOY_REMOTE`) |
| Docker API | `backend-api-1` (`DEPLOY_CONTAINER`) |
| OTA (хост) | `/opt/silent-vpn/backend/update/pc/`, `…/update/android/` |
| OTA (в контейнере) | `/app/update/pc/`, `/app/update/android/` |

---

## `deploy_helper.py` — подкоманды

| Команда | Назначение |
|---------|------------|
| `check` | uname, docker, disk, RAM |
| `install` | Docker, clone `main`, `.env`, `docker compose up` |
| `status` | `docker compose ps`, логи api |
| `creds` | Admin login/password с VPS |

---

## Какие исходники заливает каждый скрипт

### `deploy_stable.py` — всё Python backend

- **Все** `app/**/*.py`
- **Все** `ai/**/*.py`
- `admin-ui/dist/**` (нужен `npm run build`)

### `deploy_api.py`

| Файл на VPS |
|-------------|
| `app/main.py` |
| `app/config.py` |
| `app/api/admin.py` |
| `app/api/vk_auth.py` |
| `app/services/vk_id_service.py` |
| `app/api/users.py` |
| `app/api/auth.py` |
| `app/api/vpn.py` |
| `app/services/vk_agent_auth.py` |
| `app/models/__init__.py` |
| `app/models/vk_link_session.py` |
| `ai/vk_manager.py` |
| `static/vk-agent-oauth.html` |
| `admin-ui/dist/**` |

### `deploy_vk_calls.py`

| Файл на VPS |
|-------------|
| `app/services/vk_calls_auth.py` |
| `app/services/vk_agent_auth.py` |
| `app/api/admin.py` |
| `app/config.py` |
| `app/services/subscription_service.py` |
| `app/api/vk_auth.py` |
| `app/services/vk_id_service.py` |
| `ai/vk_manager.py` |
| `ai/tunnel_monitor.py` |
| `app/services/user_hash_service.py` |
| `admin-ui/dist/**` |

### `deploy_config_sync.py`

| Файл на VPS |
|-------------|
| `app/services/config_sync_service.py` |
| `app/api/vpn.py` |
| `app/schemas/vpn.py` |
| `app/api/admin.py` |

### `deploy_update_backend.py`

| Файл на VPS |
|-------------|
| `app/main.py` |
| `app/api/admin.py` |
| `app/api/updates.py` |
| `app/services/update_service.py` |
| `app/services/build_agent_service.py` |
| `ai/release_build_scheduler.py` |
| `admin-ui/dist/**` |

Создаёт в контейнере `/app/update/pc`, `/app/update/android`.  
Volumes в `docker-compose.yml`: `./update`, `./build-agent`, docker.sock.

### Build Agent (OTA-сборка на VPS)

```powershell
python scripts/pack_build_secrets.py      # android/keystore → build-agent/secrets/
python scripts/deploy_build_agent.py      # скрипты + secrets на VPS
```

На VPS: Android SDK в `/opt/android-sdk` (mount в api), Docker для PC (Wine). См. `build-agent/README.md`.

### `deploy_wdtt_systemd.py`

Не копирует Python-файлы. На VPS: `/usr/local/bin/wdtt-server`, `/etc/wdtt/`, unit `wdtt.service`.  
Нужен `DEPLOY_WDTT_MASTER_PASSWORD` в `.env.deploy`.

---

## Типовые команды

```powershell
# Полный деплой после правок backend
cd admin-ui; npm run build; cd ..
python scripts/deploy_stable.py

# Только API
python scripts/deploy_api.py

# VK / агент / VK ID
python scripts/deploy_vk_calls.py

# Диагностика
python scripts/deploy_helper.py check
python scripts/deploy_helper.py status
```

Перед любым деплоем с admin-ui: `cd admin-ui && npm run build`.

---

## Клиентские OTA

Загрузка `.exe` / `.apk` — **не здесь**, а в:

- `pc/DEPLOY.md` → `pc/scripts/deploy_release.py`
- `android/DEPLOY.md` → `android/scripts/deploy_release.py`

---

## Быстрый старт на сервере

```bash
curl -sSL https://raw.githubusercontent.com/footballpredictions/Silent/main/scripts/install.sh | sudo bash
```

Или с Windows: `python scripts/deploy_helper.py install`

## После установки

SMTP, YuMoney, VK — см. разделы ниже в исторической документации или `MEMORY_BANK.md`.

```bash
cd /opt/silent-vpn/backend
docker compose restart api
docker compose logs -f api
```

## Порты

| Порт | Протокол | Назначение |
|------|----------|-----------|
| 80 | TCP | HTTP → HTTPS |
| 443 | TCP | HTTPS (API + Admin UI) |
| 56000 | UDP | WDTT/DTLS |
| 56001 | UDP | WireGuard |

## Архитектура

```
Internet → Nginx (443/80) → FastAPI (8000)
                              ├── PostgreSQL
                              └── Redis
UDP 56000 → wdtt-server (systemd) → WireGuard (56001)
```
