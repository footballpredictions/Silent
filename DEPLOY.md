# Деплой Android (ветка `android`)

OTA: загрузка `.apk` на backend VPS (`/opt/silent-vpn/backend/update/android/`).

## Настройка (один раз)

`Silent/.env.deploy` с `DEPLOY_PASS` (см. `backend/scripts/.env.deploy.example`).

```powershell
pip install paramiko
```

## Сборка + загрузка

```powershell
cd android\app
.\gradlew.bat assembleRelease
python ..\scripts\deploy_release.py "app\build\outputs\apk\release\app-release.apk" 1.0.130
```

## Keystore (локально)

```powershell
copy keystore\keystore.properties.example keystore\keystore.properties
# положить silent-release.keystore в keystore/
```
