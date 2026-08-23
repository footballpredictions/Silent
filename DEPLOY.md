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
| `scripts/deploy_stable.py` | `python scripts/deploy_stable.py` | **Единственный** деплой backend на прод: все `app/**/*.py`, `ai/**/*.py`, `admin-ui/dist`, `docker-compose.yml` (volume app/ai) |
| `scripts/deploy_api.py` | `python scripts/deploy_api.py` | Алиас → `deploy_stable.py` (FILES-список больше не используется) |
| `scripts/restore_api_container.py` | `python scripts/restore_api_container.py` | Алиас → `deploy_stable.py` |
| `scripts/deploy_vk_calls.py` | `python scripts/deploy_vk_calls.py` | VK Calls, VK ID, агент + admin-ui/dist |
| `scripts/deploy_config_sync.py` | `python scripts/deploy_config_sync.py` | ConfigSync / sync-state |
| `scripts/deploy_update_backend.py` | `python scripts/deploy_update_backend.py` | OTA API (без .exe/.apk) + admin-ui/dist |
| `scripts/deploy_wdtt_systemd.py` | `python scripts/deploy_wdtt_systemd.py` | wdtt-server как systemd на VPS |
| `scripts/deploy_threat_dns.py` | `python scripts/deploy_threat_dns.py` | DNS-фильтр угроз (dnsmasq + HaGeZi TIF) на Улье |
| `scripts/deploy_vps_cleanup.py` | `python scripts/deploy_vps_cleanup.py` | Автоочистка Улья (journal/Docker/tmp) + timer |
| `scripts/deploy_telegram_proxy.py` | `python scripts/deploy_telegram_proxy.py` | MTProto (mtg) для Telegram + theme URL |
| `scripts/deploy_hive.py` | `python scripts/deploy_hive.py` | Улей: Hive API, cell-agent, admin-ui/dist |
| `scripts/deploy_olcrtc2_cell.py` | `python scripts/deploy_olcrtc2_cell.py [cell_ip]` | olcrtc2-srv на соту (дефолт Сота 1 `87.58.213.193`); **не** на Улей |
| `scripts/deploy_olcrtc.py` | `python scripts/deploy_olcrtc.py` | olcrtc srv (systemd) + API/админка «Варианты обхода» |
| `scripts/deploy_olcrtc_host_provision.py` | `python scripts/deploy_olcrtc_host_provision.py` | Host Playwright `:9101` — автосоздание комнат Telemost/WB для room-agent |
| `scripts/deploy_cell_agent.py` | `python scripts/deploy_cell_agent.py <cell_ip>` | cell-agent на отдельной VPS-соте |
| `scripts/apply_security_phase1.py` | `python scripts/apply_security_phase1.py` | UFW, fail2ban, bind API `127.0.0.1:8000` (+ sync кода) |
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

### `deploy_stable.py` — всё Python backend (**единственный деплой на прод**)

- **Все** `app/**/*.py`
- **Все** `ai/**/*.py`
- `admin-ui/dist/**` (нужен `npm run build`)
- `docker-compose.yml` (volume `./app`, `./ai`)
- `cell-agent/*.py`, bash `fix_tunnel_dnat`

`python scripts/deploy_api.py` и `restore_api_container.py` вызывают `deploy_stable.py`.

`docker compose build` в этот цикл **не** входит. Образ — только при смене `Dockerfile.api` / `requirements.txt`.

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
# Единственный деплой backend на прод (все .py в контейнер)
cd admin-ui; npm run build; cd ..
python scripts/deploy_stable.py

# Диагностика
python scripts/deploy_helper.py check
python scripts/deploy_helper.py status
```

`deploy_api.py` = `deploy_stable.py`. Тематические `deploy_vk_calls.py` / `deploy_hive.py` / `deploy_config_sync.py` по-прежнему со своими FILES — для прода-фиксов не использовать.

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

## Docker: код на volume, не overlay образа

`./app` и `./ai` смонтированы в контейнер **:ro** (как `admin-ui/dist`). Recreate `api` не откатывает Python. Канон: `python scripts/deploy_stable.py`. `restore_api_container.py` — алиас полного деплоя.

| Команда | Риск |
|---------|------|
| `deploy_stable.py` | ✅ Безопасно |
| `docker compose restart api` | ✅ Безопасно |
| `docker compose up -d api --no-deps` | ⚠️ Recreate меняет IP — скрипт чинит DNAT. Не трогать `wdtt` |
| Тематические `deploy_*.py` с FILES | ❌ Не для прода-фиксов |

См. `MEMORY_BANK.md` → «Docker: код в контейнере».

### Пересборка образа — не при каждом деплое

`docker compose build api` в обычный деплой **не входит**. Python и админка — volume с хоста.

Пересобирать образ только если менялись `docker/Dockerfile.api` или `requirements.txt` (системные пакеты, pip в image). Тогда на VPS: `docker compose build api`, сразу `python scripts/deploy_stable.py` с Windows (DNAT + health). `wdtt` не рестартить.

## Безопасность (скрипты)

| Скрипт | Назначение |
|--------|------------|
| `apply_security_phase1.py` | UFW, fail2ban, `127.0.0.1:8000` в compose |
| `restore_api_container.py` | Алиас `deploy_stable.py` |

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
| 8000 | TCP | FastAPI — **только 127.0.0.1** на хосте (не с интернета) |
| 56000 | UDP | WDTT/DTLS |
| 56001 | UDP | WireGuard |

## Архитектура

```
Internet → Nginx (443/80) → FastAPI (8000)
                              ├── PostgreSQL
                              └── Redis
UDP 56000 → wdtt-server (systemd) → WireGuard (56001)
```
