# Build Agent — ночная и ручная OTA-сборка

AI-агент VK создаёт **новый bootstrap-хеш**, клонирует ветки `pc` / `android` (Linux = та же ветка `pc` в `workspace/linux`), собирает release **без смены versionName/version** и кладёт артефакт в `backend/update/{platform}/`.

## Расписание

- **00:00 МСК** — если AI-агент подключён: один хеш → сборка включённых платформ (PC / Android / Linux).
- Linux автосборка **opt-in** (тумблер «Авто 00:00» в карточке PC (Linux)).
- Админка → **Обновления** → «Собрать релиз в update» — принудительная сборка одной платформы.

## Структура

```
build-agent/
  sync_repo.sh                     # git fetch / pull (linux → ветка pc)
  build_android.sh
  build_pc.sh                      # golang + electronuserland/builder:wine (NSIS)
  build_linux.sh                   # golang + electronuserland/builder:20 + pack_linux_deb.py
  install_linux_build_packages.sh  # apt + docker pull образов Linux-сборки
  secrets/                         # keystore (не в git)
  workspace/                       # клоны репо (не в git)
```

## Первичная настройка VPS

1. **Android SDK** на хосте (пример):

```bash
export ANDROID_HOME=/opt/android-sdk
# cmdline-tools, platform-tools, platforms;android-35, build-tools;35.0.0
apt install -y openjdk-17-jdk git bash
```

Смонтировать в `docker-compose.yml` (api):

```yaml
- /opt/android-sdk:/opt/android-sdk:ro
```

2. **Docker** на хосте (PC NSIS Wine + Linux electron-builder) — сокет уже смонтирован в api.

3. **Linux-сборка** (пакеты + образы):

```bash
bash /opt/silent-vpn/backend/build-agent/install_linux_build_packages.sh
```

Или вместе с деплоем агента:

```powershell
cd backend
python scripts/deploy_build_agent.py
```

4. Секреты с локальной машины:

```powershell
cd backend
python scripts/pack_build_secrets.py
python scripts/deploy_build_agent.py
```

5. Деплой backend + `docker compose up -d` с volume `./build-agent:/app/build-agent`.

## Переменные

| Переменная | По умолчанию |
|------------|--------------|
| `BUILD_AGENT_ROOT` | `/app/build-agent` |
| `BUILD_AGENT_GIT_URL` | GitHub Silent |
| `BUILD_AGENT_TIMEOUT_SEC` | 3600 |
| `BUILD_AGENT_HOST_ROOT` | путь хоста к `build-agent` (обязателен для Docker mount PC/Linux) |
| `PC_MIN_INSTALLER_BYTES` | 81000000 — отклонить установщик без wdtt |
| `LINUX_MIN_DEB_BYTES` | 50000000 — отклонить слишком маленький `.deb` |
| `LINUX_BUILDER_IMAGE` | `electronuserland/builder:20` |

Опционально: `build-agent/secrets/git_token` — PAT для приватного clone.

## Очистка диска

После **каждой** сборки (успех или ошибка) backend удаляет артефакты в `workspace/{pc,android,linux}/` и изолированный Gradle-кеш `build-agent/.gradle-cache/` — `git clean -fdx` + явное удаление `build/`, `node_modules`, `jniLibs` и т.д.

Перед сборкой — та же очистка (чистый workspace, без битых KSP-каталогов).

Если места или inodes мало — сборка не стартует (`BUILD_AGENT_MIN_FREE_GB`, по умолчанию 6 GB).
