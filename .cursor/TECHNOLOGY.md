# Silent VPN — канон для аудита и смены IP

Документ для **другого агента**. Прочитал — пишешь список «что править». **Не чинишь
код сам**, пока владелец не сказал реализующему агенту «делай». Многое, что в диффе
выглядит мёртвым/дублирующим/небезопасным, **задумано**. Ниже — как отличить.

Снимок фактов: **2026-09-17**. IP и порты ниже — текущий прод, не вечные константы.

---

## Задание аудитору (что сдать)

1. Список находок, каждая с ярлыком: **задумано** / **баг** / **долг** / **неясно**.
2. Для «баг» и «долг»: файл + символ + почему это ломает прод или старых клиентов.
3. Для смены IP: таблица «поле/хост → кто читает → что будет, если не обновить».
4. **Не предлагать** рестарт `wdtt`, TLS на `:9100` «для красоты», один `10.66.66.1`
   на все ноды, hive-first API, DNAT туннеля по одному таймауту.

Жёсткие запреты реализации: `.cursor/rules/vpn-safety.mdc`, MEMORY_BANK →
«Инвариант: не ломать старых клиентов».

---

## Репозитории

Папка `Silent-Project/` **не git**. Git живёт внутри:

| Папка | Ветка | Что это |
|-------|--------|---------|
| `backend/` | `main` | Улей: FastAPI, admin-ui, cell-agent исходник, деплой |
| `android/` | `android` | Клиент |
| `pc/` | `pc` | Windows + Linux, один Electron |
| `ios/` | `ios` | Клиент (тонкий UI, тот же API) |
| `openwrt/` | `openwrt` | Роутер, WAN API как Android |

Секреты SSH деплоя и OneDash API: `Silent-Project/.env.deploy` (не в git).
Ключ хостера не логировать и не коммитить. Сота 3 — HOSTKEY, не OneDash.

Деплой Улья: `cd backend` → `python scripts/deploy_stable.py`. Не invent новых
`deploy_*.py` в корне.

---

## Две плоскости (не путать)

### 1. Dataplane — VPN

Клиент поднимает **WDTT** (обфускация UDP, порт **56000**) + **WireGuard** на
**публичный IP выбранного сервера**. `/api/vpn/config` отдаёт **один** `Endpoint`
= IP этой ноды. Это **не кольцо и не mesh**.

У каждой ноды свой `wdtt.service`, свой интерфейс `wdtt0`, свой шлюз
**`10.66.66.1`**. Это адрес **этой** ноды в туннеле клиентов, которые на неё
подключены. Не «IP Улья», не «общий кластерный VIP».

| Слот в UI | Нода | Публичный IP (сейчас) | Заметка |
|-----------|------|------------------------|---------|
| Сервер 1 | Улей (queen) | `89.125.188.100` | UDP `:56000`. С РФ часто режут TCP 22/443, ICMP может жить |
| Сервер 2 | Сота 1 | `87.58.213.193` | Обычный выход |
| Сервер 3 | Сота 2 | `78.17.74.27` | Игры / Steam SDR, MTU клиента **1420**, остальные слоты **1200** |
| Сервер 4 | Сота 3 ИИ | `192.177.26.38` | `ai_exit`. `:9100` **не** для клиентов; гигиена в `backend/AI_EXIT_NODE.md` |

Подменить Endpoint на Соту 1, ожидая выход Соты 3 = выход Соты 1. Туннеля
сота→сота для пользовательского VPN нет.

### 2. Control plane — API

Логин, тема, `/config`, оплата, письма. Путь клиента (новые сборки 2026-09-17):

1. `http://<сота>:9100` — **сначала** Сота 1, потом Сота 2 (запечено + тема
   `hive_standby_api_urls`).
2. `https://89-125-188-100.nip.io` и `https://89.125.188.100` — **последними**.
   С РФ `:443` Улья часто таймаут. Это не «мертвый сервер», это ТСПУ/фильтр порта.

`cell-agent` на соте (`silent-cell-agent`, uvicorn `:9100`) **проксирует** на Улей:
`http://{HIVE_QUEEN_IP}:8000` → `:80` → HTTPS nip.io. Снимок theme/hive-meta
(офлайн-режим соты) — только после **3** фейлов queen (~45 с). Один рестарт API
Улья не должен объявлять Улей мёртвым (инцидент 2026-08-18: DNAT на localhost).

Старые клиенты **1.0.160 / 1.0.161** ходят HTTP на `:9100` и часто **hive-first**.
Ломать это = отвал части парка без обновления.

---

## Карта `10.66.66.1:8000`

| Где клиент / скрипт | Куда реально попадает |
|---------------------|------------------------|
| VPN на Улей | Docker API Улья через DNAT `WDTT_API` |
| VPN на Соту 1 | Шлюз **Соты 1**, не SSH Улья |
| `ssh root@10.66.66.1` с ПК, если Silent VPN на слоте соты | SSH **соты**. Пароль Улья не подойдёт |
| `ssh root@10.66.66.1` если туннель на слоте Улья | SSH Улья |

Деплой с РФ: публичный `Улей:22` часто Timeout. Обход: ПК → Сота `:22` → Улей `:22`
(`DEPLOY_JUMP_PASS`). `:9100` — HTTP, **не** деплой.

На Улье после деплоя проверять: `wdtt` **active**, DNAT туннеля на API, health 200
за <1.5 с, `queen_wg_kick_20s` ≲ 40 (лучше 0). `wdtt.service` **не рестартить**.

---

## Временный интернет (bootstrap / overlay)

Нужен на экране входа: РФ режет nip.io/Улей, без туннеля нет логина, почты, оплаты.

Как устроено (Android/PC debug+release bootstrap):

1. В клиент зашит VK bootstrap-хеш (debug — константа в gradle/`BOOTSTRAP_VK_HASH`).
2. Клиент поднимает WDTT+WG **до** логина Silent, `device_id` вида `boot:<fingerprint>`.
3. **Endpoint overlay** — живая **сота** (первая из `:9100` URL), не Улей. UDP Улья
   `:56000` с РФ флапает: полный `0.0.0.0/0` на мёртвый handshake = blackhole почты
   и API сот.
4. Если overlay всё же Улей: AllowedIPs узкие (`10.66.66.0/24` + `/32` Улья), чтобы
   не сожрать Серверы 2/3.
5. Overlay на соту: полный IPv4-туннель, из туннеля только VK (Android
   `excludeApplications`, не `includeApplications` — на vivo include часто no-op).
6. IPv6: в WG `::/0` нельзя. Android `VpnService.setBlocking` на полном bootstrap,
   иначе Gmail уходит AAAA мимо туннеля на LTE (ТСПУ).
7. API в overlay: `http://10.66.66.1:8000`. **Host: nip.io на этот IP ставить
   нельзя** — nginx :80 делал 301 POST→GET, регистрация 404. Host nip.io только
   на публичный IPv4 Улья. Политика: Android `ApiHostHeaderPolicy`.

PC: `bootstrapOverlay.js` + `subnetOnly` только если overlay = Улей.

Это **не** основной VPN после тумблера. Основной VPN берёт Endpoint из `/config`
выбранного слота. Overlay на логине и main VPN — разные сессии.

OpenWrt: отдельный bootstrap-WG как у телефона нет; WAN бьёт в те же `:9100`.

---

## Почта

Улей (`smtp.mail.ru:465`) с Сервера 1 часто `ENETUNREACH`. Улей POST
`/v1/smtp-send` на публичный `:9100` соты (секрет агента). Сота шлёт SMTP сама.

Handshake: сначала баннер **220**, потом EHLO. Иначе `SMTPNotSupportedError` /
«AUTH not supported» — это баг, **уже чинили** 2026-09-17 (`handshake_smtp`).

From = домен SMTP-ящика (`bk.ru`), не `noreply@silent-vpn.ru` (SPF/DMARC).

Ссылка в письме: кнопка на `http://сота:9100/api/auth/verify-email` (прокси на
Улей). Skip подтверждения — тумблер Extra Settings, дефолт **выкл**.

---

## Что выглядит сломанным и является каноном

| Находка аудита | Канон |
|----------------|--------|
| Два/три одинаковых `10.66.66.1` | По одному на ноду. Так задумано |
| HTTP `:9100` без TLS | Старые клиенты. TLS сломает 1.0.160/161 |
| Улей ping ок, TCP 22/443 нет | ТСПУ. Не «сервер выключен» |
| Hive-first в git истории, cell-first в HEAD | Новые клиенты — соты первые. Старые — как есть |
| `:9100` Соты 3 закрыт из РФ | ИИ-гигиена, соты нет в standby URL |
| cell-agent 401 без секрета | Норма. SMTP/status с секретом |
| `admin: 404` в хвосте deploy_stable | Часто проверочный путь, не падение админки |
| WDTT master в bootstrap-конфиге клиента | Pre-login канал. Секрет, не «забытый пароль в git для удаления ради чистоты» без плана замены |
| `includeApplications` рядом с `excludeApplications` | Старый OEM-путь vs новый полный туннель. Смотри текущий bootstrap, не мёртвые комментарии |
| Снимок на соте, login 503 | Улей мёртв для агента. Оплата/регистрация без queen не живут. Полный Postgres на каждую соту **не копируем** |
| GETCONF extras / GC peer’ов | Мусор extras снимать; ключи `devices` и live handshake не трогать |
| Kick unpaid iptables по IP, не `wg set` на каждый peer | Инцидент 2026-08-28. Тест `test_vpn_kick_storm_unit.py` |
| `GOPROXY=off` в `pc/build-debug.bat` | Локальный кэш Go. Если кэша нет — сборка wdtt падает; это скрипт, не архитектура VPN |
| Два applicationId Android `.debug` / release | Две установки. Зombie VPN между ними — отдельная история, не «дубль пакета удалить» |

---

## Реальные классы багов (чинить можно)

- Handshake SMTP без чтения 220 (уже фикс).
- Host nip.io на `10.66.66.1` (уже фикс).
- Overlay `0.0.0.0/0` на **Улей** при флапающем UDP (уже: узкий AllowedIPs на hive overlay).
- DNAT `10.66.66.1:8000` → localhost по одному health (уже: 3 фейла).
- Публикация мёртвых `:2083` в теме (убрали из standby).
- Per-peer `wg set` шторм / Postgres pool на тысячи.

Новое «упростить failover / слить шлюзы / закрыть 22» без карты клиентов = регресс.

---

## Блокировки: как отличать

Не один «сервер в бане».

| Симптом | Типичная причина |
|---------|------------------|
| ICMP есть, TCP 22/443 нет, источник Wi‑Fi РФ | ТСПУ по порту/IP. Соты `:22`/`:9100` часто живы |
| С соты Улей `:22`/`:443` открывается | Блок на пути клиент→Улей, не «Улей выключен» |
| SMTP с Улья ENETUNREACH, с соты 220+AUTH ок | Egress Улья до mail.ru |
| Gmail на overlay, IMAP нет | IPv6 leak или AllowedIPs слишком узкие |
| VPN слота соты жив, логин только через `:9100` | Control plane Улья режут, dataplane соты нет |
| Репутация HOSTKEY / hosting:true на ИИ | Не лечится сменой порта; смена IP/ASN — отдельный смысл (см. `AI_EXIT_NODE.md`) |

Смена IP **не** лечит ТСПУ «любой IP этой АС на :443». Лечит конкретный забаненный
адрес или репутацию. Сначала проба с РФ и с соты: ICMP, TCP 22, 443, 9100, UDP 56000.

---

## Смена IP (хостер платно снимает со счёта)

Улей и соты 1–2: **OneDash** ([API 2.0](https://github.com/OneDashRDP/api-docs)).
Сота 3 тоже в том же кабинете OneDash (NYC); ASN мог отображаться как HOSTKEY.

Клиент: `backend/ai/onedash_client.py` — только GET (health/auth/balance/VPS).
В публичном API 2.0 **нет** change-ip; POST не вызывать, пока владелец не задаст
`ONEDASH_CHANGE_IP_PATH` и `ONEDASH_PAID_ENABLED`. Дефолт dry-run, `executed=False`.

Ключ: `ONEDASH_API_KEY` в `.env.deploy`. Автоматизация после реальной смены должна
обновить **все читатели**, не только панель VPS.

### A. Смена IP одной обычной соты (1 или 2)

Другие ноды **не** требуют пересборки клиентов. VPN на Улье и второй соте живёт.

Обновить:

- `hive_cells.public_ip` (+ `api_url` если хранится)
- тема `hive_standby_api_urls`
- `CELL_PUBLIC_IP` в systemd `silent-cell-agent` на этой соте
- firewall/ufw/хостер security group
- rDNS/PTR если смотрите репутацию
- запечённые списки в клиентах (`BAKED_STANDBY`, OpenWrt `sv_api_bases`, iOS
  `PublicApiFailover.cells`, Android standby) — **иначе холодный старт** не знает
  новый `:9100`. Клиенты, которые уже скачали тему, подхватят URL без релиза.

Не трогать: `wdtt` на других нодах, DNAT Улья, слоты 1/3/4, ключи WG пользователей
(переедет Endpoint из `/config` после смены IP в БД).

### B. Смена IP Улья (Сервер 1)

Соты как VPN-выходы живут. Control plane:

- `HIVE_QUEEN_IP` / `HIVE_API_URL` на **каждой** соте (прокси и health queen)
- `DEPLOY_HOST`, nip.io (`<a-b-c-d>.nip.io` привязан к IP)
- nginx/сертификаты если не только nip.io
- DNAT сот на API queen (не на localhost)
- SMTP с Улья по-прежнему может быть мёртв — письма идут через соты
- запечённый hive HTTPS в клиентах — иначе последний fallback в failover тупой

Bootstrap overlay **не** должен снова целиться в новый Улей, пока UDP 56000 с РФ
не проверен. Дефолт — сота.

### C. Сота 3 / ИИ

Читать `backend/AI_EXIT_NODE.md` целиком. `:9100` не для клиентского standby.
Смена IP = репутация/ASN, не «оживить регистрацию».

---

## Где в коде смотреть (якоря)

| Тема | Где |
|------|-----|
| Failover API Android | `PublicApiFailoverPolicy` |
| Overlay сота | `BootstrapOverlayPolicy`, `AllowedIpsHelper.patchAllowedIPsForBootstrapAuth` |
| Host header | `ApiHostHeaderPolicy` |
| PC failover / overlay | `pc/src/main/vpn/apiFailover.js`, `bootstrapOverlay.js` |
| OpenWrt базы | `openwrt/files/usr/lib/silent-vpn/common.sh` `sv_api_bases` |
| Прокси соты | `backend/cell-agent/standby_runtime.py` (`QUEEN_FAIL_BEFORE_STANDBY = 3`) |
| SMTP релей | `app/services/email_service.py`, `cell-agent` `POST /v1/smtp-send` |
| Handshake SMTP | `app/services/email_smtp.py` `handshake_smtp` |
| Слоты | `app/services/hive_slots.py` |
| ИИ-сота | `backend/AI_EXIT_NODE.md` |
| Игры/MTU | `backend/GAME_EXIT_NODE.md` |
| Деплой jump | `backend/scripts/_deploy_common.py` |
| Инвариант VPN | `.cursor/rules/vpn-safety.mdc` |

---

## После аудита

Список правок отдать **реализующему** агенту этого репозитория. Он сверяет с
инвариантом и Memory Bank. Владелец говорит «делай» / «пуш» / «деплой» отдельно.

Не коммитить этот файл в чужие PR как «рефактор всей сети».
