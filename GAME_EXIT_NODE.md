# Game exit — Сота 2 / Сервер 3 (Dota / Steam SDR, UDP)

Специальный профиль **не копирует** AI-exit. Модем + белый список → Steam через VPN.

## MTU (важно)

| Слот | MTU клиента |
|---|---|
| Сервер 1, 2, 4 | **1200** |
| **Сервер 3** (Сота 2, `78.17.74.27`) | **1420** (Steam SDR ~1300-byte UDP) |

GETCONF с wdtt часто присылает **MTU=1280** — клиент его **игнорирует** и ставит
политику по слоту (PC `resolveWgMtu`, Android `mtuForPreferredSlot`).

---

## Команды соты 2

```powershell
python scripts/deploy_game_cell.py audit --host 78.17.74.27
python scripts/deploy_game_cell.py probe --host 78.17.74.27
python scripts/deploy_game_cell.py udp-tune --host 78.17.74.27
python scripts/deploy_game_cell.py status --host 78.17.74.27
```

## Проверка на клиенте

- PC log: `MTU = 1420 (Сервер 3 / Steam SDR)` только на server3; иначе `MTU = 1200`
- Android Debug Log: `MTU=1420 (Сервер 3 / Steam SDR)` только на server3; иначе `MTU=1200`

## Инварианты

- Не рестартить `wdtt`
- Не ACCEPT UDP перед `SILENT_DENY`
- Не копировать AI TPROXY на игровую соту
