# Debug olcrtc binaries (variant 2)

Android **нельзя** запускать бинарь из `filesDir` (error=13 Permission denied на Android 10+).

Нужен `libolcrtc.so` в jniLibs (как `libclient.so`):

```
app/src/main/jniLibs/arm64-v8a/libolcrtc.so
app/src/main/jniLibs/armeabi-v7a/libolcrtc.so   # опционально
```

Сборка (из `Silent-Project/vendor/olcrtc`, CGO off):

```bat
build_olcrtc_android.bat
```

или вручную:

```powershell
cd vendor\olcrtc
$env:CGO_ENABLED="0"; $env:GOOS="android"; $env:GOARCH="arm64"
go build -trimpath -ldflags "-s -w -checklinkname=0" -o ..\..\android\app\src\main\jniLibs\arm64-v8a\libolcrtc.so ./cmd/olcrtc
```

`jniLibs/` в `.gitignore` — бинарь локальный / CI.

TUN→SOCKS на Android пока опционален (SOCKS-only достаточно для debug connect).

Upstream: https://github.com/openlibrecommunity/olcrtc
