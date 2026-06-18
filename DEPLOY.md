# Деплой PC-клиента (ветка `pc`)

**Репозиторий:** `Silent-Project/pc/`  
**Шпаргалка Agent:** полный список deploy-файлов — **этот файл**. Индекс: `backend/.cursor/MEMORY_BANK.md` → «Деплой».

OTA: загрузка `.exe` на backend VPS → `/opt/silent-vpn/backend/update/pc/` → в контейнер `/app/update/pc/`.

---

## Все файлы деплоя в этом репозитории

| Файл | Запуск | Что делает |
|------|--------|------------|
| `scripts/_deploy_common.py` | *(модуль)* | SSH, чтение `Silent-Project/.env.deploy` |
| `scripts/deploy_release.py` | `python scripts/deploy_release.py "<exe>" <version>` | OTA: .exe + manifest.json на VPS |

### Не деплой (утилита)

| Файл | Назначение |
|------|------------|
| `scripts/generate-brand-icon.py` | Генерация иконки бренда — **не** загружает на сервер |

**Не создавать** новые `deploy_*.py` вне `scripts/`.

---

## Настройка (один раз)

1. Скопировать `../backend/scripts/.env.deploy.example` → `Silent-Project/.env.deploy`
2. Задать `DEPLOY_PASS` (и при необходимости `DEPLOY_HOST`, `DEPLOY_REMOTE`)
3. `pip install paramiko`

Переменные по умолчанию:

| Переменная | Значение |
|------------|----------|
| `DEPLOY_REMOTE` | `/opt/silent-vpn/backend` |
| `DEPLOY_CONTAINER` | `backend-api-1` |
| Платформа OTA | `pc` |
| Папка на VPS | `{DEPLOY_REMOTE}/update/pc/` |

---

## `deploy_release.py` — что делает

1. SFTP: заливает `.exe` в `/opt/silent-vpn/backend/update/pc/<filename>`
2. `docker cp` → `/app/update/pc/<filename>` в `backend-api-1`
3. Пишет `manifest.json` (version, filename, size) в контейнере
4. Проверяет `GET /api/updates/check?platform=pc&version=0.0.0`

Аргументы:

```powershell
python scripts/deploy_release.py "<path-to-setup.exe>" <version>
# Пример:
python scripts/deploy_release.py "build-release-v141-XXXX\Silent VPN Setup 1.0.142.exe" 1.0.142
```

---

## Сборка + загрузка

```powershell
cd pc
.\build-installer.bat
python scripts\deploy_release.py "build-release-v141-XXXX\Silent VPN Setup 1.0.142.exe" 1.0.142
```

## Проверка

```text
GET https://132-243-234-162.nip.io/api/updates/check?platform=pc&version=1.0.141
```

Скачивание: `https://132-243-234-162.nip.io/update/pc/<filename>`

---

## Backend-деплой

API, admin-ui, VK — только из `backend/DEPLOY.md` (ветка `main`).
