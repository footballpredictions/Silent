# Деплой Android (ветка `android`)

**Репозиторий:** `Silent-Project/android/`  
**Шпаргалка Agent:** полный список deploy-файлов — **этот файл**. Индекс: `backend/.cursor/MEMORY_BANK.md` → «Деплой».

OTA: загрузка `.apk` на backend VPS → `/opt/silent-vpn/backend/update/android/` → в контейнер `/app/update/android/`.

---

## Все файлы деплоя в этом репозитории

| Файл | Запуск | Что делает |
|------|--------|------------|
| `scripts/_deploy_common.py` | *(модуль)* | SSH, чтение `Silent-Project/.env.deploy` |
| `scripts/deploy_release.py` | `python scripts/deploy_release.py "<apk>" <version>` | OTA: .apk + manifest.json на VPS |

**Не создавать** новые `deploy_*.py` вне `scripts/`.

---

## Настройка (один раз)

1. `Silent-Project/.env.deploy` с `DEPLOY_PASS` (шаблон: `backend/scripts/.env.deploy.example`)
2. `pip install paramiko`

| Переменная | Значение |
|------------|----------|
| `DEPLOY_REMOTE` | `/opt/silent-vpn/backend` |
| `DEPLOY_CONTAINER` | `backend-api-1` |
| Платформа OTA | `android` |
| Папка на VPS | `{DEPLOY_REMOTE}/update/android/` |

---

## `deploy_release.py` — что делает

1. SFTP: заливает `.apk` в `/opt/silent-vpn/backend/update/android/<filename>`
2. `docker cp` → `/app/update/android/<filename>` в `backend-api-1`
3. Пишет `manifest.json` в контейнере
4. Проверяет `GET /api/updates/check?platform=android&version=0.0.0`

Аргументы:

```powershell
python scripts/deploy_release.py "<path-to.apk>" <version>
# Пример:
python scripts/deploy_release.py "app\build\outputs\apk\release\app-release.apk" 1.0.130
```

Имя файла на сервере: `{basename}-{version}.apk` (например `app-release-1.0.130.apk`).

---

## Сборка + загрузка

```powershell
cd android\app
.\gradlew.bat assembleRelease
cd ..
python scripts\deploy_release.py "app\build\outputs\apk\release\app-release.apk" 1.0.130
```

## Keystore (локально, не в git)

```powershell
copy keystore\keystore.properties.example keystore\keystore.properties
# положить silent-release.keystore в keystore/
```

## Проверка

```text
GET https://132-243-234-162.nip.io/api/updates/check?platform=android&version=1.0.129
```

Скачивание: `https://132-243-234-162.nip.io/update/android/<filename>`

---

## Backend-деплой

OTA API (`/api/updates`) — `backend/scripts/deploy_update_backend.py`, см. `backend/DEPLOY.md`.
