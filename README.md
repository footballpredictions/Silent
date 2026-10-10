# Silent VPN для OpenWrt

Свой клиент для роутера: агент совместим с тем же backend, что PC / Android / iOS, веб-панель в стиле клиентов, вход по `{lan-ip}.silent.vpn`.

Код **не** форк LuCI, AmneziaWG и Passwall. Заметки по чужим проектам: [RESEARCH.md](RESEARCH.md). Установка: [INSTALL.md](INSTALL.md).

## Установка на роутер

OpenWrt 23.05+. aarch64, arm, mipsel, x86_64. [Инструкция](INSTALL.md).

В SSH-сессии роутера проверьте свободное место:

```sh
df -h /tmp /overlay
```

Нужно свободно: 50 МБ в `/tmp` и 35 МБ в `/overlay`.

Установите (роутеру нужен интернет):

```sh
wget -O /tmp/sv.sh https://silentvpn3.github.io/openwrt-install.sh && sh /tmp/sv.sh
```

Откройте `http://<LAN-IP>.silent.vpn` или IP роутера. Войдите, включите
«Российские сервисы мимо VPN» в «Исключениях», затем включите VPN.

Удаление:

```sh
sh /usr/sbin/silent-vpn-uninstall
```

## Локальный просмотр веба

На Windows из этой папки:

```powershell
python scripts/preview.py
```

Откроется `http://127.0.0.1:7788/` — макет телефона и адресная строка `http://192.168.1.1.silent.vpn`.

Другой LAN для проверки строки:

```powershell
$env:SILENT_PREVIEW_LAN="10.0.0.1"
python scripts/preview.py
```

Вход в preview: любой email и пароль от 8 символов. Тема тянется с живого `GET /api/vpn/theme` (если Улей отвечает).

Тесты:

```powershell
python -m unittest discover -s tests -v
```

## Состав

| Путь | Зачем |
|------|--------|
| `web/` | Панель (HTML/CSS/JS), server-driven theme |
| `files/` | То, что попадает на роутер (init, CGI, агент) |
| `lib/` | Hostname и палитра — preview + тесты |
| `scripts/preview.py` | Локальный сервер панели |
| `Makefile` | Пакет OpenWrt `silent-vpn` |
| `install.sh` | Копирование на живой роутер без SDK |

Интерфейс агента один: `silent-vpn-ctl`. Веб ходит только в локальный CGI.

«Российские сервисы мимо VPN» направляет через WAN домены `.ru`, `.su`, `.рф`
и отдельные домены российских сервисов/CDN в других зонах. Список DNS-суффиксов:
`files/usr/lib/silent-vpn/ru-direct.domains`; MAX и ресурсы Ozon/Wildberries включены.

## Пуш

Это отдельная папка проекта, как `pc/` / `android/`. Коммит и remote — только по команде «пуш».
