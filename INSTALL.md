# Установка Silent VPN на OpenWrt

OpenWrt **23.05+** (opkg на 23/24, apk на 25+). aarch64, arm, mipsel, x86_64. Панель: `http://<LAN-IP>.silent.vpn`

## На роутере

Команду вставляют в консоль роутера, не в Windows.

Откройте админку в браузере по адресу роутера (у каждого свой, часто `http://192.168.1.1`). Дальше: **Сервисы → Терминал**.

Скрипт ставит зависимости и панель VPN под архитектуру роутера:

```sh
if command -v apk >/dev/null 2>&1; then apk update && apk add wget ca-bundle; else opkg update && opkg install wget ca-bundle; fi && wget -O /tmp/sv.sh https://silentvpn3.github.io/openwrt-install.sh && sh /tmp/sv.sh
```

Что ставит: WireGuard, wget/ca-bundle, страница Silent в браузере (вход и тумблер), обход блокировок под CPU.

Вход: в той же Wi‑Fi откройте `http://192.168.1.1.silent.vpn` (вместо 192.168.1.1 — IP админки роутера). Свой логин и пароль, «Войти». VPN — тумблером. Российские сайты мимо VPN: в «Исключениях» тумблер «Российские сервисы мимо VPN».

## Сборка пакета (на компьютере)

```powershell
python scripts/build_wdtt.py
python scripts/build_release.py
```

`dist/silent-vpn-openwrt-1.0.165.tar.gz` — его кладут на `https://silentvpn3.github.io/silent-vpn-openwrt.tgz`. Скрипт `remote-install.sh` = `landing/openwrt-install.sh`. Удаление: `uninstall.sh` = `landing/openwrt-uninstall.sh`.

## Удалить

```sh
wget -O /tmp/sv-rm.sh https://silentvpn3.github.io/openwrt-uninstall.sh && sh /tmp/sv-rm.sh
```
