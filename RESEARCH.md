# Исследование: OpenWrt VPN-клиенты (без копирования кода)

Задача: понять, *как устроены* чужие роутерные VPN-пакеты, и сделать **свой** клиент Silent VPN. Код из перечисленных репозиториев **не переносился**.

## Что смотрели

| Проект | Зачем смотрели | Чем мы не стали |
|--------|----------------|-----------------|
| [openwrt/luci `luci-proto-wireguard`](https://github.com/openwrt/luci) | Официальный способ завести WG как UCI-интерфейс + firewall zone | LuCI-формы, QR, peer-editor |
| [IVPN OpenWrt WG guide](https://www.ivpn.net/setup/router/openwrt-wireguard/) | Минимальный набор пакетов: `kmod-wireguard`, `wireguard-tools`, `luci-proto-wireguard` | Ручной импорт `.conf` в LuCI |
| [Slava-Shchipunov/awg-openwrt](https://github.com/Slava-Shchipunov/awg-openwrt) | ipk по `target_subtarget`, one-line install, релизы под 23.05/24.10 | AmneziaWG Jc/Jmin/H1–H4, luci-i18n |
| [Alexey71/amneziawg-openwrt](https://github.com/Alexey71/amneziawg-openwrt) | Три пакета (kmod / tools / luci-proto), vermagic ядра | Форк luci-proto-wireguard |
| [Nexumi/awg-openwrt](https://github.com/Nexumi/awg-openwrt) | Скрипт ставит пакеты и сразу гонит весь LAN в туннель | Интерактивный ввод AWG-полей |
| [itdoginfo/domain-routing-openwrt](https://github.com/itdoginfo/domain-routing-openwrt) | Policy routing / списки доменов на роутере | Обход по доменам вместо нашего WDTT |
| Passwall / OpenClash (обзорно) | Тяжёлые LuCI-приложения с чужим стеком (Xray/Clash) | Другой протокол, другой UI |

Вывод по чужим проектам: почти все либо **встраиваются в LuCI**, либо просят **вставить готовый WireGuard/Amnezia-конфиг**. Silent так не работает.

## Чем Silent на роутере обязан отличаться

1. **Тот же backend**, что PC/Android/iOS: `ThemeResponse`, login/register, `device/register`, `/config`, connect/disconnect, sync-state, платежи, слоты серверов.
2. **Не AmneziaWG и не Clash.** Путь как у клиентов: WireGuard → WDTT (cloak) → VK TURN → wdtt-server. Прямой WG — запасной канал, если cloak-бинарь ещё не положили.
3. **Свой веб**, не тема LuCI. Цвета/тексты только из `GET /api/vpn/theme`.
4. **Вход по `{lan-ip}.silent.vpn`**, LuCI на голом IP не трогаем.
5. **`device_type=pc`** в API (как Linux/Mac) — старый backend не ломаем, лимит сессий тот же.

## Архитектурные решения (наши)

- Глубокий модуль `silent-vpn-ctl`: UI и CGI знают только `status / login / connect / disconnect`.
- Внутри: `hive` (HTTPS API), `path` (UCI WG + маршруты), `cloak` (wdtt-client), `lan-name` (dnsmasq).
- Второй `uhttpd` не сажаем на :80 (занято LuCI). Хост `*.silent.vpn` ловит CGI-вход `silent-entry` и отдаёт наш UI; IP остаётся LuCI.
