# MEMORY BANK — Silent VPN Project

## О проекте
**Silent** — коммерческий VPN-сервис на базе WireGuard-туннелирования через VK TURN/DTLS серверы.
Технология маскирует трафик под зашифрованный медиатрафик WebRTC звонков ВКонтакте.

Репозиторий: https://github.com/footballpredictions/Silent.git
- `main` → backend + AI ассистент
- `android` → Android клиент (Kotlin + Jetpack Compose)
- `pc` → PC клиент (Electron)
- `ios` → iOS клиент (Swift + SwiftUI)

## Архитектура

### Стек технологий
| Компонент | Технология |
|-----------|-----------|
| Backend API | Python 3.11 + FastAPI |
| База данных | PostgreSQL 16 + Redis 7 |
| Миграции | Alembic |
| AI Ассистент | Python asyncio (VK call manager) |
| Admin UI | React 18 + TypeScript + Vite + Tailwind |
| PC Клиент | Electron 28 + React |
| Android | Kotlin + Jetpack Compose + WireGuard GoBackend |
| iOS | Swift + SwiftUI + NetworkExtension |
| VPN Core | wdtt-server (WireGuard over VK TURN/DTLS) |
| Деплой | Docker Compose + bash (одна команда) |
| TLS | Self-signed на IP (OpenSSL) |
| Почта | SMTP (smtplib) с HTML шаблонами |
| Платежи | YuMoney (2 кошелька, случайный выбор) |

### Принцип работы VPN
```
Клиент → WireGuard → Go WDTT-клиент → VK TURN/DTLS → wdtt-server на VPS → Интернет
```
- Трафик маскируется под WebRTC audio (RTP/ChaCha20-Poly1305 AEAD)
- AI создаёт 3 VK-хеша (групповые звонки) и следит за ними 24/7
- При сбое — все 3 хеша пересоздаются

### VPN Flow для пользователя
1. Регистрация → подтверждение email
2. Оплата YuMoney → активация подписки (email с лого)
3. Клиент получает WireGuard-конфиг + VK-хеши от API
4. Нажимает тумблер → подключается
5. Максимум 3 устройства на аккаунт

## Ключевые решения

### Мультипользовательский wdtt-server
- Один экземпляр wdtt-server на VPS
- Наш backend генерирует пароли (до 10 активных)
- При масштабировании — несколько инстансов сервера

### Дизайн
- Чёрно-белый, единый для всех клиентов
- Хранится на backend (API endpoint `/api/theme`)
- Клиенты только рендерят данные

### Устройства
- Учёт по: user_id + device_fingerprint + IP
- Максимум 3 устройства на аккаунт
- 4-е устройство получает ошибку

### AI Ассистент VK
- Хранит VK-логин/пароль в зашифрованном виде (backend)
- Создаёт 3 групповых звонка → 3 хеша
- Проверяет хеши каждые 5 минут
- При сбое: выключает/включает (reconnect) → если не помогло: пересоздаёт

## Структура файлов
```
Silent/
├── .cursor/MEMORY_BANK.md
├── backend/                    ← ветка main
│   ├── app/                    FastAPI приложение
│   │   ├── api/                роуты
│   │   ├── models/             SQLAlchemy модели
│   │   ├── schemas/            Pydantic схемы
│   │   ├── services/           бизнес-логика
│   │   └── core/               конфиг, безопасность
│   ├── ai/                     VK-ассистент
│   ├── admin-ui/               React дашборд
│   ├── docker/                 Dockerfile'ы
│   ├── scripts/install.sh      одна команда деплоя
│   └── docker-compose.yml
├── android/                    ← ветка android
├── pc/                         ← ветка pc
└── ios/                        ← ветка ios
```

## Последние изменения
- 2026-05-25: Создан проект Silent, базовая структура, все ветки, бекенд, клиенты
