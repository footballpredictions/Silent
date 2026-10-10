# Установка Silent VPN на OpenWrt

OpenWrt 23.05+. aarch64, arm, mipsel, x86_64.

1. Подключитесь по SSH (укажите IP своего роутера):

```sh
ssh root@192.168.1.1
```

2. Проверьте свободное место:

```sh
df -h /tmp /overlay
```

Нужно свободно: 50 МБ в `/tmp` и 35 МБ в `/overlay` (колонка Available).

3. Установите. Роутеру нужен интернет:

```sh
wget -O /tmp/sv.sh https://silentvpn3.github.io/openwrt-install.sh && sh /tmp/sv.sh
```

4. Откройте `http://192.168.1.1.silent.vpn` или IP своего роутера.
Войдите в аккаунт и включите тумблер.

5. Для удаления:

```sh
sh /usr/sbin/silent-vpn-uninstall
```

## Сборка и публикация

```powershell
python scripts/build_wdtt.py
python scripts/build_release.py
```

В GitHub Pages публикуются три файла: `silent-vpn-openwrt.tgz` из `dist/`,
`openwrt-install.sh` из `remote-install.sh`, `openwrt-uninstall.sh` из `uninstall.sh`.
Скрипт скачивает архив с `https://silentvpn3.github.io/silent-vpn-openwrt.tgz`.
