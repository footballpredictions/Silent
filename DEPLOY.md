# Silent VPN — Инструкция по развёртыванию

## Деплой с Windows (ветка `main`, папка `backend/`)

Секреты SSH — в `Silent-Project/.env.deploy` или `backend/.env.deploy` (см. `scripts/.env.deploy.example`).

```powershell
pip install paramiko
cd backend
```

| Скрипт | Назначение |
|--------|------------|
| `python scripts/deploy_helper.py check` | Диагностика VPS |
| `python scripts/deploy_helper.py install` | Первичная установка Docker + clone main |
| `python scripts/deploy_helper.py status` | `docker compose ps` + логи api |
| `python scripts/deploy_stable.py` | Полный деплой app/ + ai/ + admin-ui/dist |
| `python scripts/deploy_api.py` | Ключевые API-файлы + admin-ui |
| `python scripts/deploy_vk_calls.py` | VK Calls auth + admin UI |
| `python scripts/deploy_config_sync.py` | ConfigSync / sync-state |
| `python scripts/deploy_update_backend.py` | OTA API на backend |
| `python scripts/deploy_wdtt_systemd.py` | wdtt-server как systemd |

Клиентские OTA (`.exe` / `.apk`) — скрипты в `pc/scripts/` и `android/scripts/`.

Перед деплоем admin-ui:

```powershell
cd admin-ui
npm install
npm run build
```

## Быстрый старт на сервере (одна команда)

```bash
curl -sSL https://raw.githubusercontent.com/footballpredictions/Silent/main/scripts/install.sh | sudo bash
```

Или с Windows: `python scripts/deploy_helper.py install`

Скрипт автоматически:
1. Установит Docker, WireGuard
2. Склонирует ветку `main` в `/opt/silent-vpn/backend`
3. Скачает `wdtt-server` бинарник
4. Создаёт самоподписанный TLS-сертификат на IP сервера
5. Генерирует `.env` с безопасными паролями
6. Запустит все сервисы через Docker Compose

## Требования к серверу

| Параметр | Минимум |
|----------|---------|
| ОС | Ubuntu 20.04+ / Debian 11+ |
| CPU | 1 vCPU |
| RAM | 1 GB |
| Диск | 10 GB |
| Открытые порты | 80, 443, 56000/udp, 56001/udp |

## После установки

### 1. Настройте email (SMTP)

```bash
nano /opt/silent-vpn/backend/.env
```

Заполните:
```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASS=your_app_password_here
```

### 2. Настройте YuMoney

```env
YUMONEY_WALLET_1=4100111111111111
YUMONEY_WALLET_2=4100122222222222
YUMONEY_SECRET=your_notification_secret
```

В настройках YuMoney установите webhook URL:
```
https://YOUR_SERVER_IP/api/payments/yumoney/notify
```

### 3. Перезапустите сервисы

```bash
cd /opt/silent-vpn/backend
docker compose restart api
```

### 4. Войдите в Admin Panel

```
https://YOUR_SERVER_IP/
```

Логин и пароль выведены скриптом установки.

### 5. Настройте VK Credentials

1. Войдите в Admin Panel
2. Перейдите в раздел **"VK / Тоннели"**
3. Введите логин и пароль VK-аккаунта
4. Нажмите **"Сохранить"**
5. Нажмите **"Пересоздать все"** — AI создаст 3 VK-хеша

## Управление

```bash
# Логи
docker compose -f /opt/silent-vpn/backend/docker-compose.yml logs -f api

# Перезапуск
docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart

# Остановка
docker compose -f /opt/silent-vpn/backend/docker-compose.yml down

# Обновление
cd /opt/silent-vpn/backend && git pull origin main
docker compose up -d --build api
```

## Порты

| Порт | Протокол | Назначение |
|------|----------|-----------|
| 80 | TCP | HTTP → редирект на HTTPS |
| 443 | TCP | HTTPS (API + Admin UI) |
| 56000 | UDP | WDTT/DTLS VPN транспорт |
| 56001 | UDP | WireGuard |

## Смена IP / Миграция

При смене IP-адреса сервера:

1. Обновите `VPN_SERVER_IP` в `.env`
2. Перегенерируйте TLS-сертификат:
   ```bash
   cd /opt/silent-vpn/backend/scripts
   bash gen_certs.sh
   docker compose restart nginx
   ```
3. Переподключите все устройства клиентов (новый IP в настройках приложения)

## Архитектура сервисов

```
Internet → Nginx (443/80) → FastAPI (8000)
                              ├── PostgreSQL (5432)
                              └── Redis (6379)
UDP 56000 → wdtt-server → WireGuard (56001)
```
