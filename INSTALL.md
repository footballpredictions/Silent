# Установка Silent VPN на OpenWrt

Один файл на **все архитектуры** (aarch64, arm, mipsel, x86_64…): внутри только скрипты и веб, без бинарника под процессор.

Панель: **`http://<LAN-IP>.silent.vpn`** (LuCI на голом IP не трогаем).

| LAN роутера | Адрес панели |
|-------------|--------------|
| `192.168.1.1` | http://192.168.1.1.silent.vpn |
| `192.168.0.1` | http://192.168.0.1.silent.vpn |
| `10.0.0.1` | http://10.0.0.1.silent.vpn |

Нужен OpenWrt **23.05** или **24.10** и интернет на WAN.

---

## Сборка файла (на компьютере)

Из папки `openwrt/`:

```powershell
python scripts/build_release.py
```

Появится `dist/silent-vpn-openwrt-1.0.165.tar.gz`. Его потом кладут в GitHub Release / копируют на роутер.

---

## На роутере (две команды)

Скопируйте архив в `/tmp` (WinSCP, scp или wget, когда файл уже на GitHub).

```sh
cd /tmp
tar -xzf silent-vpn-openwrt-1.0.165.tar.gz
cd silent-vpn

sh install.sh deps
sh install.sh install
```

`deps` ставит: `kmod-wireguard wireguard-tools wget ca-bundle uhttpd jsonfilter`.  
`install` копирует панель и агент.

Всё сразу одной командой:

```sh
sh install.sh
```

---

## После установки

1. С телефона или ПК в той же Wi‑Fi откройте `http://<LAN-IP>.silent.vpn`.
2. Войдите **тем же email и паролем**, что в приложении Silent.
3. Включите тумблер — дом идёт в VPN. Роутер занимает одну из трёх сессий (`device_type=pc`).

Cloak `wdtt-client` не обязателен для первого включения на обычной сети. Если Улей режут без обхода — бинарь под arch роутера кладут в `/usr/bin/wdtt-client` отдельно.

---

## Снять

```sh
/etc/init.d/silent-vpn stop
rm -rf /usr/lib/silent-vpn /usr/sbin/silent-vpn-ctl /www/silent-vpn \
  /www/cgi-bin/silent-entry /www/cgi-bin/silent-api /etc/silent-vpn \
  /etc/init.d/silent-vpn /etc/config/silent-vpn \
  /etc/hotplug.d/iface/99-silent-vpn
```
