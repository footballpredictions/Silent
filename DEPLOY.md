# Деплой PC-клиента (ветка `pc`)

OTA: загрузка `.exe` на backend VPS (`/opt/silent-vpn/backend/update/pc/`).

## Настройка (один раз)

Скопируйте `../backend/scripts/.env.deploy.example` в `Silent/.env.deploy` (корень рабочей папки) и задайте `DEPLOY_PASS`.

Требуется: `pip install paramiko`

## Сборка + загрузка на сервер

```powershell
cd pc
.\build-installer.bat
python scripts\deploy_release.py "build-release-v141-XXXX\Silent VPN Setup 1.0.142.exe" 1.0.142
```

Скрипт: заливает файл на VPS, обновляет `manifest.json`, копирует в Docker `backend-api-1`.

## Проверка

```text
GET https://132-243-234-162.nip.io/api/updates/check?platform=pc&version=1.0.141
```
