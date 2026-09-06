# AI exit node — Сота 3 (Сервер 4, 192.177.26.38)

Специализированный выход для ИИ-сервисов (ChatGPT, Gemini, Claude, Copilot). Всё
изолировано на одной соте: Улей и Соты 1–2 не затронуты, клиентские приложения
не меняются, `wdtt.service` не рестартится.

Статус на 2026-09-06: Ф0–Ф3 применены и проверены, Ф4 (резидентная цепочка)
реализована, но **выключена**. `admin_only` снят не был — сота видна только админу.

---

## 1. Что и зачем

Задача не «спрятать VPN», а перестать быть **подозрительным** датацентром.
Обфускация транспорта (REALITY / Hysteria / AmneziaWG) решает «РКН не режет путь
до США» и никак не влияет на то, доверяет ли Cloudflare перед ChatGPT нашему IP.

### Как нас палят

| Признак | Что было на соте | Что сделали |
|---|---|---|
| Открытые порты у сканеров | `22`, `9100`, `56000/udp`, `56001/udp` наружу, ufw выключен | `9100` только Улью (Ф1); `56000/56001` осознанно оставлены — от них зависят клиенты 1.0.160/1.0.161 |
| rDNS | PTR пустой | правится вручную в панели HOSTKEY (см. §6) |
| DNS-резолвер и ECS | клиент шёл на `77.88.8.8` (РФ) или в чёрную дыру `10.66.66.1` | свой резолвер на соте, DoT на US-апстрим (Ф2) |
| IPv6 / AAAA мимо туннеля | AAAA отдавались клиенту | `filter-AAAA` в dnsmasq + запрет IPv6-egress (Ф1, Ф2) |
| TCP-отпечаток | TTL клиента (Windows 128 / Android 64) и MSS туннеля уходили наружу | TTL нормализован в 64; MSS решается терминацией TCP в sing-box (Ф3) |
| Репутация IP/ASN | `AS395839 HOSTKEY`, `hosting: true`, `proxy: true` | не лечится настройкой — только Ф4 или смена провайдера |
| Поведение (много аккаунтов с одного IP) | — | актуально после снятия `admin_only`, см. §8 |

JA3/JA4 идут end-to-end от настоящего браузера — их трогать не нужно и вредно.

### Важно про MSS

Поднимать MSS правилом `iptables` (1240 → 1460) **нельзя**: MTU туннеля 1280, и
сервер начнёт слать сегменты, которые не влезают в туннель. Правильное решение —
терминация TCP на ноде (Ф3): наружу идёт обычное соединение ноды с MSS 1460, а к
клиенту — отдельное с туннельным MSS.

---

## 2. Архитектура

```mermaid
flowchart LR
    client["Клиент RU"] -->|WDTT + WireGuard| cell["Сота 3 (US)"]
    cell --> dnat["iptables: DNAT :53 + TPROXY 80/443"]
    dnat --> dnsmasq["dnsmasq :5353 (filter-AAAA, HaGeZi)"]
    dnsmasq --> unbound["unbound 127.0.0.1:53 (DoT -> US)"]
    dnat --> singbox["sing-box TPROXY :7895 (sniff SNI)"]
    singbox -->|"ИИ-домены"| aiout["ai-out: direct | WARP | SOCKS5"]
    singbox -->|"остальное"| direct["direct"]
    watchdog["watchdog каждые 20с"] -.->|"sing-box нездоров -> снять цепочку"| dnat
```

Ключевое свойство: **цепочку TPROXY вешает только watchdog** и только пока
`sing-box` активен и слушает порт. Любой сбой — трафик сам возвращается на
прежний прямой путь.

---

## 3. Файлы и где что лежит

### В репозитории

| Файл | Роль |
|---|---|
| `backend/app/services/ai_exit_node.py` | генератор всех скриптов и конфигов + `fetch_cell_egress()` |
| `backend/scripts/deploy_ai_cell.py` | CLI: заходит на Улей, запускает раннер в API-контейнере, тот идёт по SSH на соту |
| `backend/scripts/test_ai_exit_node_unit.py` | юнит-тесты инвариантов (fail-open, wdtt цел, порты старых клиентов) |
| `backend/cell-agent/main.py` | `POST /v1/egress-check` — чистота выхода глазами соты |
| `backend/app/api/hive.py` | `POST /api/admin/hive/cells/{id}/egress-check` |
| `backend/admin-ui/src/pages/HivePage.tsx` | бейдж «ИИ-выход», тумблер, карточка чистоты выхода |
| `backend/ai/availability_agent.py` | тихая проба ИИ-доменов с соты-выхода (`_run_ai_exit_probes`) |
| `backend/app/models/hive_cell.py` | флаг `ai_exit` (миграция `sota3_ai_exit_v1`) |

Пароль root от соты локально не хранится: раннер берёт его из БД
(`hive_cells.ssh_password_enc`, Fernet) — тот же путь, что у provision.

### На соте

| Путь | Что |
|---|---|
| `/opt/silent-vpn/ai-exit/10-hygiene.sh` | правила гигиены, идемпотентно |
| `/opt/silent-vpn/ai-exit/20-dns.sh` | DNAT клиентского `:53` на свой резолвер |
| `/opt/silent-vpn/ai-exit/watchdog.sh` | единственный, кто вешает/снимает TPROXY |
| `/etc/silent-ai/sing-box.json` | конфиг прокси, `chmod 600` |
| `/etc/silent-ai/proxy.enabled` | рубильник: нет файла — прокси выключен |
| `/etc/silent-ai/tif.dnsmasq` | HaGeZi TIF, только если фильтр угроз включён в админке |
| `/etc/unbound/unbound.conf.d/silent-ai.conf`, `/etc/dnsmasq.d/silent-ai.conf` | резолвер |
| systemd | `silent-ai-rules` (переигрывает правила после ребута), `sing-box`, `silent-ai-watchdog.timer`, `silent-ai-dnslist.timer` |

---

## 4. Команды

Всё запускается из папки `backend`. Скрипт работает **только** с сотой, у которой
в Улье стоит флаг `ai_exit`; для другой соты нужен явный `--host IP --force`.

```powershell
python scripts/deploy_ai_cell.py audit      # Ф0: read-only срез ноды
python scripts/deploy_ai_cell.py hygiene    # Ф1: закрыть 9100, TTL 64, IPv6 off
python scripts/deploy_ai_cell.py dns        # Ф2: unbound (DoT) + dnsmasq + заворот :53
python scripts/deploy_ai_cell.py proxy      # Ф3: sing-box TPROXY + watchdog
python scripts/deploy_ai_cell.py verify     # проверка глазами клиента (временный netns)
python scripts/deploy_ai_cell.py status     # что сейчас включено
python scripts/deploy_ai_cell.py egress     # чистота выхода (то же, что кнопка в Улье)
python scripts/deploy_ai_cell.py agent      # обновить cell-agent на этой соте
python scripts/deploy_ai_cell.py harden --host 1.2.3.4   # базовая гигиена любой соты
python scripts/deploy_ai_cell.py harden --all            # то же для всех сот
```

`harden` — единственная фаза, которой не нужен флаг `ai_exit`: это тот минимум
(ufw, TTL 64, IPv6 off, `gai.conf`), который новые соты получают сами при
подключении. На соте с AI-профилем она в конце переигрывает `10-hygiene.sh`,
чтобы `ufw` не сорвал более строгие правила.

Полезные ключи:

```powershell
python scripts/deploy_ai_cell.py hygiene --ipv6 keep            # не трогать IPv6
python scripts/deploy_ai_cell.py hygiene --ssh-allow 1.2.3.4    # сузить SSH (по умолчанию не трогаем)
python scripts/deploy_ai_cell.py proxy --off                    # поставить, но не включать
python scripts/deploy_ai_cell.py proxy --chain warp             # Ф4: WARP вторым хопом
python scripts/deploy_ai_cell.py proxy --chain socks5://user:pass@host:1080
python scripts/deploy_ai_cell.py rollback --scope proxy|dns|all
```

Все фазы идемпотентны — повторный запуск безопасен. Фаза `dns` читает флаг
«фильтр угроз» из админки: включили/выключили его — прогоните `dns` заново.

### Порядок для новой ноды

`audit` → `hygiene` → `dns` → `proxy` → `verify` → `status`. Между фазами
смотреть вывод: каждая заканчивается маркером `=== done ===`.

---

## 5. Baseline Соты 3 (снят 2026-09-06 до правок)

- `192.177.26.38`, `AS395839 HOSTKEY`, EGIHosting / InterLIR, New York, US.
- `ip-api`: `hosting: true`, `proxy: true`, `reverse: ""`.
- ufw **выключен**, `iptables INPUT` пустой, политика ACCEPT. Наружу слушают
  `22/tcp`, `9100/tcp`, `56000/udp`, `56001/udp`.
- `nat`: `DNAT 10.66.66.1:8000 → 132.243.234.162:8000`, `MASQUERADE 10.66.0.0/16 → eth0` (`WDTT_MANAGED`).
- `eth0` — только link-local IPv6, глобального IPv6 и v6-маршрута нет.
- `wdtt0` MTU 1280, адрес ноды в туннеле `10.66.0.0/16`.
- systemd-resolved занимает `127.0.0.53` и `127.0.0.54`, значит `127.0.0.1:53` свободен.
- С ноды: `gemini.google.com` 200, `api.openai.com` 401, `chatgpt.com` и
  `claude.ai` — 403 (см. §7 про то, почему это не приговор).

Полный вывод: `python scripts/deploy_ai_cell.py audit`.

---

## 6. Ручные шаги (не автоматизируются)

1. **PTR у HOSTKEY.** Заказать нейтральный rDNS для `192.177.26.38`: без слов
   `vpn`, `proxy`, `tunnel`, `wg`, `node`. Годится что-то вида
   `mail-relay-ny01.<домен>` или просто хостнейм на своём домене.
2. **Geofeed / коррекция гео** в MaxMind, IPinfo, IP2Location — чтобы город и
   страна не расходились между базами.
3. **Делистинг** в AbuseIPDB / Spamhaus, если у IP осталась история прошлого
   арендатора.
4. **Проверка реальным браузером** через VPN на Сервере 4 — единственный
   достоверный тест (см. §7).

---

## 7. Чеклист приёмки

Автоматически (`verify` + `status`):

- [x] `9100` снаружи закрыт: с не-белого адреса `curl` даёт `000`, счётчик DROP растёт.
- [x] Улей по-прежнему получает `200` с `http://192.177.26.38:9100/health`.
- [x] Клиент, настроенный на `77.88.8.8`, получает ответ от нашего резолвера.
- [x] AAAA для `chatgpt.com` не отдаётся (`filter-AAAA`).
- [x] Трафик клиента идёт через sing-box (счётчик TPROXY > 0), выходной IP — `192.177.26.38`, `loc=US`, `colo=EWR`.
- [x] `wdtt` active, health Улья 200, kick-шторма нет (`queen_wg_kick_20s=0`).

Вручную, обязательно перед снятием `admin_only`:

- [ ] Выбрать в клиенте **Сервер 4**, открыть в браузере `chatgpt.com`,
      `gemini.google.com`, `claude.ai` — без бесконечной CAPTCHA, вход в аккаунт проходит.
- [ ] `dnsleaktest.com` из-под Сервера 4 показывает американский резолвер, не Яндекс.
- [ ] `browserleaks.com/ip` — нет IPv6 и WebRTC-утечки мимо туннеля.

**Про 403 с ноды.** `curl` к `chatgpt.com` и `claude.ai` отдаёт 403 и с
браузерным User-Agent тоже. Это ожидаемо: Cloudflare смотрит на TLS-отпечаток,
а у `curl` он не браузерный. Отличить «нас забанили по IP» от «мы не браузер»
с ноды нельзя — поэтому вердикт даёт только реальный браузер через VPN. Полезный
сигнал с ноды другой: `gemini.google.com` 200 и `api.openai.com` 401 означают,
что сеть и гео в порядке.

---

## 8. Что дальше

### Ф4 — резидентная цепочка (готова, выключена)

Включать, только если после реального теста браузером остаются CAPTCHA-циклы.
Цепочка применяется **только** к доменам из `AI_DOMAIN_SUFFIXES`, остальной
трафик всегда `direct` — иначе сожжём платный трафик.

```powershell
python scripts/deploy_ai_cell.py proxy --chain warp      # бесплатная ступень
python scripts/deploy_ai_cell.py proxy --chain socks5://user:pass@host:1080
python scripts/deploy_ai_cell.py proxy                   # вернуться на direct
```

`--chain warp` ставит `wgcf`, регистрирует бесплатный аккаунт и вшивает ключи в
`ai-out` уже **на ноде** — в репозиторий ключи не попадают. Проверять после
включения: `verify` (выходной IP для ИИ-доменов сменится на адрес Cloudflare) и
что `gemini.google.com` не начал требовать капчу — у WARP своя репутация.

### Ф6 — открыть всем

1. Прогнать ручной чеклист §7.
2. **До** открытия — поставить потолок онлайна на соту, иначе сотни аккаунтов с
   одного IP сожгут репутацию поведением. Отдельный механизм не нужен, работает
   существующий `max_clients` (в карточке соты он показан как «ручной потолок»):

   ```bash
   curl -X PATCH https://<Улей>/api/admin/hive/cells/<cell_id> \
     -H "Authorization: Bearer <admin_token>" -H "Content-Type: application/json" \
     -d '{"max_clients": 40}'
   ```

   `0` = авто по нагрузке. Для ИИ-выхода начинать с небольшого числа (30–50) и
   поднимать, наблюдая за капчами.
3. Снять `admin_only` кнопкой в Улье («Открыть всем»).
4. План Б: вторая US-нода в другом ASN, чтобы увести пользователей при блокировке.
   Провижининг обычный, затем `deploy_ai_cell.py --host <новый IP> --force`
   по фазам `hygiene → dns → proxy → verify` и включение флага `ai_exit`.

### Известные ограничения

- QUIC (UDP 443) не перехватывается: HTTP/3 идёт прямым NAT, без нормализации
  TCP-отпечатка. Выходной IP тот же. Блокировать UDP 443 не стали — сломает часть
  приложений.
- `56000/56001` открыты наружу: осознанный остаточный риск ради совместимости со
  старыми клиентами.
- Флаг `hosting: true` на ASN HOSTKEY, скорее всего, останется навсегда.
- Сота с `ai_exit` исключена из `standby_api_urls`: её `9100` закрыт от интернета,
  и клиенту незачем ждать таймаута. Соты 1–2 в failover-списке остаются.

### Отклонение от исходного плана

План предлагал сузить `ufw allow {agent_port}/tcp` до IP Улья в
`hive_provision_service.py` для **всех** новых сот. Не сделано осознанно: `:9100`
у обычных сот — это третий слой failover (клиент идёт в cell-agent, когда Улей
недоступен). Закрыв порт на всех сотах, мы убрали бы этот слой целиком. Порт
закрыт только на соте с `ai_exit`, и именно она исключена из failover-списка.

---

## 11. Базовая гигиена всех сот (`cell_hardening.py`)

Аудит Соты 3 показал, что сота после подключения жила с **выключенным `ufw` и
пустым `iptables INPUT`**: наружу торчало всё, что слушало на `0.0.0.0`, TTL
наружу выдавал ОС клиента, IPv6-egress был жив, glibc предпочитал IPv6.

Теперь `app/services/cell_hardening.py` строит блок, который выполняется
**внутри провижининга** (`provision_cell_via_ssh`, до правил nat) и вручную
фазой `harden`:

| Что | Как |
|---|---|
| Фаервол | `ufw`: `22/tcp`, `56000/udp`, `56001/udp`, `9100/tcp`, всё из `10.66.0.0/16`; остальное закрыто |
| Транзит клиентов | `DEFAULT_FORWARD_POLICY="ACCEPT"` ставится **до** `ufw enable` |
| TTL | `mangle POSTROUTING -o WAN -j TTL --ttl-set 64` |
| IPv6 | `ip6tables` FORWARD DROP + OUTPUT REJECT в `2000::/3` |
| glibc | `precedence ::ffff:0:0/96 100` в `/etc/gai.conf` |
| После ребута | юнит `silent-cell-hardening` (`After=ufw.service`) прогоняет `/opt/silent-vpn/hardening/[0-9]*.sh` |

Порядок важен в двух местах: `ufw` при включении перезаливает свои цепочки, поэтому
гигиена идёт **до** правил nat и запускает скрипт **после** `ufw enable`, а на соте
с AI-профилем в конце дёргает `/opt/silent-vpn/ai-exit/10-hygiene.sh`.

Инварианты проверяет `python scripts/test_cell_hardening_unit.py` (порты старых
клиентов, FORWARD ACCEPT до enable, wdtt не трогаем, идемпотентность).

---

## 9. Откат

```powershell
python scripts/deploy_ai_cell.py rollback --scope proxy   # снять только TPROXY
python scripts/deploy_ai_cell.py rollback --scope dns     # + вернуть клиентам их DNS
python scripts/deploy_ai_cell.py rollback --scope all     # + открыть 9100 наружу
```

Экстренно, прямо на ноде (без Улья):

```bash
rm -f /etc/silent-ai/proxy.enabled && /opt/silent-vpn/ai-exit/watchdog.sh
```

Прокси снимается первым в любом сценарии: сначала трафик возвращается на прямой
путь, потом откатывается всё остальное. `wdtt` не трогается ни в одной ветке.

---

## 10. Правила для агента, который это трогает

- Ничего не менять на Улье и Сотах 1–2. Все правки — только на `192.177.26.38`.
- `wdtt.service` не рестартить. DNAT `10.66.66.1:8000` не трогать.
- Не закрывать `56000/56001` — сломает клиентов 1.0.160/1.0.161.
- Любое новое звено в разрыве трафика — только с fail-open watchdog.
- Перед деплоем: `python scripts/test_ai_exit_node_unit.py` и
  `python scripts/test_vpn_kick_storm_unit.py`.
- Правки фаз (`ai_exit_node.py`) применяются сразу: `deploy_ai_cell.py` заливает
  локальную копию модуля в контейнер. Полный `deploy_stable.py` нужен только для
  изменений API, админки и cell-agent.
