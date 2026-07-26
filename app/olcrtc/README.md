# Debug olcrtc binaries (variant 2)

Android **нельзя** запускать бинарь из `filesDir` (error=13 Permission denied на Android 10+).

Нужен `libolcrtc.so` в jniLibs (как `libclient.so`):

```
app/src/main/jniLibs/arm64-v8a/libolcrtc.so
app/src/main/jniLibs/armeabi-v7a/libolcrtc.so   # опционально
```

## Сборка — обязательно CGO + NDK

На Android 11+ `net.Interfaces()` → `netlinkrib: permission denied`.  
Нужен `getifaddrs` через cgo (`pionnet_android.go`).

```bat
cd android\app\olcrtc
build_olcrtc_android.bat
```

Скрипт берёт NDK из `ANDROID_HOME` / `local.properties` (как `build_android_go.bat` для libclient).

`CGO_ENABLED=0` **не использовать** для Telemost/WB — ICE упадёт на `load interfaces`.

`jniLibs/` в `.gitignore` — бинарь локальный / CI.
