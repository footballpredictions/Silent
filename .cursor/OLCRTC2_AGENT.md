# olcrtc 2.0 — агент комнат (как подключить и тестировать)

## Что это

Агент держит **warm-пул** готовых комнат на **сотах**.  
Клиент при Apply/connect берёт готовую комнату (~1с). Leave → teardown.

| Нода | Роль |
|------|------|
| Улей `132.243.234.162` | только WDTT/VK + API — **olcrtc2 exit запрещён** |
| Сота 1 `87.58.213.193` | **Telemost** olcrtc2 (`cells.telemost`) + Playwright `:9101` |
| Сота 2 `78.17.74.27` | **WB Stream** olcrtc2 (`cells.wbstream`) — create через HTTP API с queen |
| Сота 3+ | запас / overflow |

Assign/create: `cell_ip_for_provider(provider)`.  
WB room create/delete: `ai/olcrtc_wb_api.py` (не Playwright).

## Админка (один раз)

1. **Варианты обхода** → блок **olcrtc 2.0**.
2. Галочки: **Включён для клиентов**, **Агент**.
3. **Warm провайдеры:** Телемост + WB Stream.
4. **Сота Telemost** = `87.58.213.193`, **Сота WB** = `78.17.74.27`.
5. **Create URL Telemost** = `http://87.58.213.193:9101`
6. **Сгенерировать** master key → **Сохранить**.

Нужны аккаунты:
- Telemost cookies в room accounts
- WB JWT (`eyJ…`) в room accounts / sync auth.token

Диагностика egress: `python scripts/probe_olcrtc2_cell_egress.py [IP]`.

## Клиенты (debug)

Меню → Варианты обхода → **olcrtc 2.0** → канал:
- **Телемост → Сота 1**
- **WB Stream → Сота 2**

### PC
Свежий `pc/resources/olcrtc2-cnc.exe` (mode=telemost|wbstream).

### Android
Свежий `libolcrtc2.so` + APK:  
`android/app/build/outputs/apk/debug/SilentVPN-debug.apk`  
В логе: `mode=wbstream` / `olcrtc2_wb_prefetch` или `mode=telemost`.

## Деплой сот

```powershell
cd backend
# linux amd64 srv из vendor/olcrtc
python scripts/deploy_olcrtc2_cell.py 87.58.213.193
python scripts/deploy_olcrtc2_cell.py 78.17.74.27
python scripts/upgrade_cell_agent_olcrtc2.py 87.58.213.193
python scripts/upgrade_cell_agent_olcrtc2.py 78.17.74.27
```

Host-provision `:9101` нужен **только** для Telemost create.  
WB create — с queen через API.

## Как понять что работает

Админка: Warm PC/Android растут по обоим провайдерам.  
Клиент Apply → room без «нет комнаты».  
На srv env: `OLCRTC2_MODE=wbstream` + `OLCRTC2_AUTH_TOKEN=eyJ…` для WB.
