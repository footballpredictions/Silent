# Game exit — Сота 2 (Dota / Steam SDR, UDP)

Специальный профиль **не копирует** AI-exit (без TPROXY/WARP/DNS-заворота).
Задача: модем + белый список → Steam/Dota **через** VPN (исключения приложений нельзя).

Симптом клиента: `Matchmaking Failed` / «ping any relay via UDP failed (firewall or MTU)».

---

## Корень (2026-09-12 вечер)

Steam Networking шлёт UDP **~1300 байт**. У нас клиентский WG MTU был **1200**
(эксперимент под Telegram), серверный `wdtt0` — **1280**. Пакеты Steam не
влезают → тихий fail, текст ошибки сам пишет «firewall or MTU».

Мелкий probe с соты давал `UDP_PATH_OK` — поэтому первый тюнинг «на соте» не
помог пользователю: дыра была в **MTU клиента**, не в «Valve режется фаерволом соты».

Референс: Tailscale #5711 — при MTU 1280 Dota/CS2 ломаются; лечится MTU **1420**.

| Слой | Было | Стало |
|---|---|---|
| PC/Android/Linux WG conf | 1200 | **1420** |
| Сота 2 `wdtt0` | 1280 | **1420** (`ip link set`, без рестарта wdtt) |
| sysctl UDP timeouts | 30/120 | 120/180 |

---

## Что сказать пользователю **прямо сейчас** (без ожидания OTA)

1. VPN ON, **Сервер 3**.
2. PowerShell **от администратора**:

```powershell
Get-NetAdapter | Where-Object { $_.Name -match 'wg-turn|WireGuard' } | Format-Table Name, ifIndex, Status
netsh interface ipv4 set subinterface "wg-turn" mtu=1420 store=persistent
```

Если имя адаптера другое — подставить из первой команды.

3. Выкл/вкл VPN → Steam → Dota.

Постоянный фикс — новый билд PC (MTU 1420 в коде).

---

## Команды (backend)

```powershell
python scripts/deploy_game_cell.py audit --host 78.17.74.27
python scripts/deploy_game_cell.py probe --host 78.17.74.27
python scripts/deploy_game_cell.py udp-tune --host 78.17.74.27
python scripts/deploy_game_cell.py status --host 78.17.74.27
python scripts/deploy_game_cell.py rollback --host 78.17.74.27
python scripts/test_game_exit_node_unit.py
```

---

## Инварианты

- Не рестартить `wdtt`
- Не ставить `ACCEPT` UDP/ICMP **перед** `SILENT_DENY`
- Не трогать 56000/56001
- Не копировать AI TPROXY на игровую соту
