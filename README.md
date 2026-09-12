# Silent VPN для OpenWrt

Свой клиент для роутера: агент совместим с тем же backend, что PC / Android / iOS, веб-панель в стиле клиентов, вход по `{lan-ip}.silent.vpn`.

Код **не** форк LuCI, AmneziaWG и Passwall. Заметки по чужим проектам: [RESEARCH.md](RESEARCH.md). Установка: [INSTALL.md](INSTALL.md).

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

## Пуш

Это отдельная папка проекта, как `pc/` / `android/`. Коммит и remote — только по команде «пуш».
