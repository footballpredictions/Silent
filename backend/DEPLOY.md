# Silent VPN — Инструкция по развёртыванию

## Быстрый старт (одна команда)

```bash
curl -sSL https://raw.githubusercontent.com/footballpredictions/Silent/main/backend/scripts/install.sh | sudo bash
```

Скрипт автоматически:
1. Установит Docker, WireGuard
2. Склонирует репозиторий в `/opt/silent-vpn`
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
cd /opt/silent-vpn && git pull origin main
docker compose -f backend/docker-compose.yml up -d --build api
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
