# Установка Silent VPN на OpenWrt

Панель после установки: **`http://<LAN-IP>.silent.vpn`**

Примеры (у каждого роутера свой LAN):

| LAN роутера | Адрес панели |
|-------------|--------------|
| `192.168.1.1` | http://192.168.1.1.silent.vpn |
| `192.168.0.1` | http://192.168.0.1.silent.vpn |
| `10.0.0.1` | http://10.0.0.1.silent.vpn |

Голый IP (`http://192.168.1.1`) остаётся **LuCI**. Мы его не подменяем.

## Что нужно на роутере

- OpenWrt **23.05** или **24.10**
- Свободно ~2 МБ flash + `kmod-wireguard` под ваше ядро
- Выход в интернет на WAN (хотя бы до первого логина)

Пакеты:

```
kmod-wireguard wireguard-tools wget ca-bundle uhttpd jsonfilter
```

## Быстрая установка с компьютера в LAN

1. Скопируйте папку `openwrt/` на роутер (scp / WinSCP), например в `/tmp/silent-openwrt`.
2. По SSH:

```sh
opkg update
opkg install kmod-wireguard wireguard-tools wget ca-bundle uhttpd jsonfilter
sh /tmp/silent-openwrt/install.sh
```

3. С телефона или ПК в той же Wi‑Fi/LAN откройте адрес из таблицы выше.
4. Войдите тем же аккаунтом Silent, что на телефоне/PC. Роутер занимает одну из **трёх** сессий (`device_type=pc`, как Linux/Mac).

Скрипт пишет файлы, включает `silent-vpn`, прописывает dnsmasq `*.silent.vpn` и печатает ваш URL.

## Сборка ipk (SDK / buildroot)

Из дерева OpenWrt SDK:

```sh
ln -s /path/to/Silent-Project/openwrt package/silent-vpn
make package/silent-vpn/compile
```

Готовый `silent-vpn_1.0.165-1_*.ipk` ставьте через `opkg install` или System → Software → Upload.

## Первый вход

1. Логин / регистрация — те же API, что у клиентов (`/api/auth/*`, тема с `/api/vpn/theme`).
2. Тумблер поднимает WG-интерфейс `svpath` и (если лежит бинарь) `wdtt-client`.
3. LAN-клиенты идут в туннель, сама подсеть LAN не уезжает — панель не отваливается.

Если Улей по HTTPS недоступен без обхода — нужен cloak-бинарь (тот же `wdtt-client`, что у Linux-клиента) в `/usr/bin/wdtt-client` под архитектуру роутера (`aarch64`, `arm_cortex-a7`, `mipsel_24kc`, `x86_64`). Без него агент всё равно пишет WG-конфиг с Улья — на чистой сети этого достаточно.

## Снять

```sh
/etc/init.d/silent-vpn stop
rm -rf /usr/lib/silent-vpn /usr/sbin/silent-vpn-ctl /www/silent-vpn \
  /www/cgi-bin/silent-entry /www/cgi-bin/silent-api /etc/silent-vpn \
  /etc/init.d/silent-vpn /etc/config/silent-vpn \
  /etc/hotplug.d/iface/99-silent-vpn
```

LuCI index верните вручную, если меняли: `uci show uhttpd.main.index_page`.

## Совместимость с backend

Не требует деплоя API. Старые клиенты 1.0.160/1.0.161 не затрагиваются.

| Поле | Значение |
|------|----------|
| `device_type` | `pc` |
| `X-App-Version` | `1.0.165` |
| Тема | `GET /api/vpn/theme` |
| Логин | `POST /api/auth/login` |
| Устройство | `POST /api/vpn/device/register` |
| Конфиг | `GET /api/vpn/config` |
| Тумблер | `POST /api/vpn/connect` / `disconnect` |
| Туннель API | `http://10.66.66.1:8000` когда `svpath` поднят |
