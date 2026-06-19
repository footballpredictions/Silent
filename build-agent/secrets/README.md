# Секреты сборки (не в git)

Сюда кладутся файлы для release-сборки на VPS:

```
secrets/
  android/keystore/
    keystore.properties
    silent-release.keystore
```

Заполнить локально и отправить на сервер:

```powershell
cd backend
python scripts/pack_build_secrets.py
python scripts/deploy_build_agent.py
```

Опционально: `secrets/git_token` — PAT для `git clone` приватного репо.
