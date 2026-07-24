# Debug binaries for variant 2 (olcrtc)

Place Windows builds here (not committed):

- `olcrtc.exe` — from https://github.com/openlibrecommunity/olcrtc (`mage cross` / Windows build)
- `sing-box.exe` — TUN→SOCKS bridge (https://github.com/SagerNet/sing-box/releases)

Resolved by `src/main/vpn/olcrtcSession.js` from:
- `pc/resources/olcrtc.exe` / `pc/resources/sing-box.exe`
- or `pc/resources/olcrtc/`, `pc/resources/sing-box/`
- or `pc/olcrtc/`, `pc/vendor/`

Only used when debug build + «Варианты обхода» → вариант 2.
