# ПЛАН — Кастомная оплата YuMoney (QuickPay, без API)

> Статус: **план, не реализовано**. Реализующий агент выполняет шаги по порядку и отмечает выполненное.
> Ветка: `main` (папка `backend/`), клиенты — `pc/` и `android/` (iOS — отдельная задача).
> Контекст проекта: `.cursor/MEMORY_BANK.md`, API: `.cursor/APIS.md`.

---

## 1. Цель

Полностью рабочая и безопасная оплата подписки через **YuMoney QuickPay** (форма/кнопка с фиксированной суммой, у нас **нет** доступа к YooKassa API):

1. Пользователь в клиенте выбирает тариф → бэкенд создаёт платёж → клиент открывает ссылку QuickPay в браузере.
2. Пользователь платит. **Никакого ручного подтверждения** (в отличие от SilentShield `/payments/confirm`) — бэкенд сам принимает HTTP-уведомление от YuMoney и активирует подписку.
3. Уведомление **однозначно** привязывается к конкретному платежу конкретного пользователя (см. §4 — label). Два пользователя, платящих одновременно, не могут перепутаться.
4. Кошельки: сейчас 2, выбираются **случайно**; масштабирование **до 10** кошельков — только добавлением переменных в `.env`, **без правок кода**.
5. Клиент автоматически видит активацию (poll статуса платежа + ConfigSync profile) и показывает «Оплата получена».

Референс (что НЕ повторять): https://github.com/footballpredictions/Silentsheild — там подтверждение оплаты запускал пользователь кнопкой; у нас активация только по webhook.

---

## 2. Текущее состояние (что уже есть в `backend/`)

| Компонент | Файл | Состояние |
|---|---|---|
| API `/api/payments/init`, `/yumoney/notify`, `/promo/check`, `/plans` | `app/api/payments.py` | есть, требует доработки |
| Сервис QuickPay URL + обработка уведомления | `app/services/payment_service.py` | есть, **есть критичные баги** (§3) |
| Модель `Payment` (`yumoney_label` unique) + `PromoCode` | `app/models/payment.py` | есть, нужны поля |
| Активация подписки, отмена trial, продление от max(expires) | `payment_service.process_payment_notification` | есть |
| Реферальный бонус после первой оплаты | `app/services/referral_service.py` | есть, не трогать |
| Клиент PC: меню «Подписка», `POST /api/payments/init` → `openExternal(url)` | `pc/src/renderer/pages/MainScreen.tsx` | есть, нужен poll-статус |
| Клиент Android: `initPayment` / `checkPromo` / `getPlans` в `ApiService.kt` | `android/.../data/ApiService.kt` | есть, нужен poll-статус |
| Env | `.env` на VPS: `YUMONEY_WALLET_1`, `YUMONEY_WALLET_2`, `YUMONEY_SECRET`, `PRICE_*` | есть |

Схема БД создаётся через `Base.metadata.create_all` + `ALTER TABLE ... IF NOT EXISTS` в `app/main.py` (Alembic-миграций в репо нет) — новые колонки добавлять так же.

---

## 3. Найденные баги (исправить обязательно)

1. **Кошелёк выбирается дважды.** В `create_payment_intent` вызывается `_pick_wallet()` и результат пишется в `Payment.wallet`, но `build_payment_url` внутри вызывает `_pick_wallet()` **ещё раз** — в ссылку оплаты может попасть другой кошелёк, чем записан в БД. Передавать выбранный кошелёк в `build_payment_url` параметром.
2. **Webhook не проверяет сумму.** Злоумышленник может открыть ссылку QuickPay, поменять `sum=1`, заплатить 1₽ — уведомление придёт с нашим label и подписка активируется. Проверять сумму (§6.3).
3. **Нет проверки `codepro` / `unaccepted`.** Если перевод защищён кодом протекции или не принят — деньги фактически не получены, активировать нельзя.
4. **Гонка двух уведомлений.** YuMoney может прислать уведомление повторно; два конкурентных запроса оба прочитают `status=pending` и дважды создадут подписку. Нужен `SELECT ... FOR UPDATE` (в SQLAlchemy: `.with_for_update()`) + уникальный `operation_id`.
5. **URL не кодируется.** `build_payment_url` клеит query через f-string без urlencode — `targets` с пробелами/тире и русским текстом ломает форму. Использовать `urllib.parse.urlencode`.
6. **`successURL` невалиден:** `f"{settings.APP_NAME}://payment/success"` → `Silent VPN://payment/success` (пробел в схеме). Заменить на HTML-страницу бэкенда (§6.5).
7. **Один `YUMONEY_SECRET` на все кошельки.** У YuMoney секрет уведомлений выдаётся **на каждый кошелёк отдельно** — при 2+ кошельках подпись чужого кошелька не пройдёт. Нужны per-wallet секреты (§5).
8. **`PromoCode.use_count` не инкрементируется** ни при init, ни при завершении оплаты. Инкрементировать при **завершении** платежа (в notify), и сбрасывать `pending_promo_code` тоже только при завершении (сейчас сбрасывается при init — если оплата не прошла, промокод теряется).
9. **Label предсказуем частично** (`silent_{user_id}_{8 hex}`) — приемлемо, но лучше `silent_` + 24+ hex случайных (label ≤ 64 символа у YuMoney). user_id в label не нужен — платёж ищем по label в БД.

---

## 4. Архитектура привязки платежа (анти-гонка)

**Гарантия однозначности — уникальный `label` на каждый платёж:**

```
POST /api/payments/init (JWT user A) → Payment(label=silent_a1b2..., user_id=A, wallet=W3, amount=199, status=pending)
POST /api/payments/init (JWT user B) → Payment(label=silent_c3d4..., user_id=B, wallet=W1, amount=199, status=pending)

YuMoney notify(label=silent_a1b2...) → находит платёж A по label → активирует ТОЛЬКО пользователю A.
Платёж B остаётся pending, пока не придёт уведомление с ЕГО label.
```

`label` генерируется сервером, попадает в QuickPay URL (`&label=...`), YuMoney возвращает его в уведомлении без изменений. Сценарий «двое платят одновременно, у одного прошло, у другого нет» невозможен для путаницы: уведомление содержит label ровно того платежа, который оплачен. Совпадение сумм/времени роли не играет.

**Идемпотентность:** `operation_id` из уведомления сохраняется в `Payment.operation_id` (unique index). Повторное уведомление по завершённому платежу → ответ 200 OK без действий.

**Блокировка:** обработка уведомления в одной транзакции с `with_for_update()` на строке Payment.

**TTL pending:** платёж старше 24 ч можно помечать `failed` (lazy при обращении к статусу), но если уведомление всё же придёт по «просроченному» — деньги получены → активировать и логировать (не как SilentShield, где 3 минуты — слишком агрессивно).

---

## 5. Мульти-кошельки до 10 штук (только через .env)

### 5.1 `app/config.py` — добавить поля

```python
# YuMoney: до 10 кошельков; кошелёк N активен, если YUMONEY_WALLET_N непустой.
# У каждого кошелька СВОЙ секрет HTTP-уведомлений (настройка в кабинете YuMoney).
# YUMONEY_SECRET (без номера) — fallback, если YUMONEY_SECRET_N не задан.
YUMONEY_WALLET_1: str = ""
...
YUMONEY_WALLET_10: str = ""
YUMONEY_SECRET: str = ""
YUMONEY_SECRET_1: str = ""
...
YUMONEY_SECRET_10: str = ""
```

Да, это 20 объявленных полей — зато «добавил `YUMONEY_WALLET_3` и `YUMONEY_SECRET_3` в `.env` → работает без правок кода», как требуется. Pydantic `extra="ignore"` уже стоит.

### 5.2 `payment_service.py` — хелперы

```python
def get_wallets() -> list[tuple[str, str]]:
    """[(wallet, secret)] для всех непустых YUMONEY_WALLET_N, N=1..10."""
    out = []
    for n in range(1, 11):
        w = getattr(settings, f"YUMONEY_WALLET_{n}", "").strip()
        if not w:
            continue
        s = getattr(settings, f"YUMONEY_SECRET_{n}", "").strip() or settings.YUMONEY_SECRET
        out.append((w, s))
    return out

def _pick_wallet() -> str:
    wallets = get_wallets()
    if not wallets:
        raise RuntimeError("YuMoney wallets not configured")
    return random.choice(wallets)[0]

def secret_for_wallet(wallet: str) -> str: ...
```

Случайный выбор — как просил пользователь (равномерное распределение средств). Выбранный кошелёк передаётся в `build_payment_url(receiver=wallet)` (фикс бага №1).

### 5.3 Проверка подписи с per-wallet секретом

Уведомление YuMoney **не содержит** номер кошелька-получателя в открытом виде. Порядок:
1. Найти `Payment` по `label` → знаем `payment.wallet`.
2. Проверить sha1 с `secret_for_wallet(payment.wallet)`.
3. Если label пустой/не найден (например, тестовое уведомление из кабинета) — попробовать все секреты; при валидной подписи ответить 200 и залогировать «notification without matching payment», подписку не трогать.

Формат sha1 (не менять, это спека YuMoney):
```
notification_type&operation_id&amount&currency&datetime&sender&codepro&notification_secret&label
```

---

## 6. Изменения backend (пофайлово)

### 6.1 `app/models/payment.py`

```python
class Payment(Base):
    # существующие поля без изменений, добавить:
    operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    # withdraw_amount из уведомления (что реально списано у плательщика)
    paid_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
```

В `app/main.py` (lifespan, рядом с существующими ALTER):
```sql
ALTER TABLE payments ADD COLUMN IF NOT EXISTS operation_id VARCHAR(128);
ALTER TABLE payments ADD COLUMN IF NOT EXISTS paid_amount NUMERIC(10,2);
CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_operation_id ON payments (operation_id) WHERE operation_id IS NOT NULL;
```

### 6.2 `app/services/payment_service.py` — `create_payment_intent`

- label: `"silent_" + secrets.token_hex(16)` (39 символов < 64).
- Кошелёк выбрать **один раз**, записать в Payment и передать в `build_payment_url` (фикс №1).
- Промокод: скидку применять, но `use_count` и `pending_promo_code` **не трогать** до завершения (фикс №8). Код промо сохранить в Payment (`promo_code: str | None` — добавить колонку `ALTER ... promo_code VARCHAR(50)`).
- `build_payment_url`: `urllib.parse.urlencode`, `quickpay-form=shop`, `need-fio/need-email/need-phone/need-address=false`, `paymentType=AC` не фиксировать (пусть пользователь выбирает карту/кошелёк — убрать параметр или оставить по умолчанию), `successURL={FRONTEND_URL}/api/payments/success-page` (§6.5).
- Вернуть клиенту также `label` — по нему клиент будет опрашивать статус.

### 6.3 `payment_service.process_payment_notification` — переписать по чеклисту

Порядок проверок (каждый фейл — лог + выход без активации):
1. `label` начинается с `silent_` → `SELECT Payment WHERE yumoney_label=label` **`.with_for_update()`** (транзакция).
2. Подпись sha1 с `secret_for_wallet(payment.wallet)` (§5.3). До нахождения платежа подпись проверить нельзя — поэтому порядок: найти → проверить подпись → остальное.
3. `payment.status == "completed"` и `operation_id` совпадает → **200 OK, идемпотентный повтор**, ничего не делать.
4. `codepro == "false"` и `unaccepted != "true"` (фикс №3).
5. `currency == "643"`.
6. **Сумма:** `withdraw_amount` (что заплатил отправитель) сравнить с `payment.amount` с допуском 1 коп. Если `withdraw_amount` отсутствует — `amount` (зачислено за вычетом комиссии) должен быть `>= payment.amount * 0.93`. Несовпадение → пометить `status="failed"`, `raw_response=data`, лог WARNING «amount mismatch», **не активировать** (фикс №2).
7. Всё ок → `status="completed"`, `operation_id`, `paid_amount`, `completed_at`, `raw_response`.
8. Активация подписки — существующая логика (отмена trial, продление от max expires) без изменений.
9. Промокод платежа: `use_count += 1`, у пользователя `pending_promo_code=None` (фикс №8).
10. Реферальный бонус — существующий вызов `apply_referral_reward_after_payment`.
11. Email об активации — существующий вызов.

Ответ endpoint'а: YuMoney ретраит при не-200 → на **любую валидную по подписи** ситуацию отвечать 200; 400 только на невалидную подпись.

### 6.4 `app/api/payments.py` — новый endpoint статуса

```python
@router.get("/status/{label}")
async def payment_status(label: str, user=Depends(get_verified_user), db=...):
    # ТОЛЬКО свой платёж: WHERE yumoney_label=label AND user_id=user.id
    # → { "status": "pending"|"completed"|"failed", "plan_type": ..., "expires_at": <новый срок, если completed> }
```

Только чтение, подписку НЕ активирует (урок SilentShield: активация исключительно из webhook). Rate limit не нужен (JWT + own rows), но poll клиента — не чаще 1 раза в 3–5 сек.

### 6.5 Страница успеха `GET /api/payments/success-page`

HTML в стиле существующих (`verify-email`, `reset-password-page` в `app/api/auth.py` — переиспользовать оформление): «Оплата принята. Подписка активируется автоматически в течение минуты — вернитесь в приложение Silent VPN». Без токенов/данных в query. Это адрес `successURL` формы QuickPay.

### 6.6 Логи для админки

Через существующий буфер логов (`GET /api/admin/logs`): INFO «payment initiated user=… plan=… wallet=…» (кошелёк маскировать до последних 4 цифр), INFO «payment completed …», WARNING «amount mismatch / invalid signature / unknown label». Отдельная страница платежей в админке — **не в этом плане** (опционально позже).

---

## 7. Клиенты

### 7.1 PC (`pc/src/renderer/pages/MainScreen.tsx`, ветка `pc`)

Сейчас: кнопка тарифа → `POST /api/payments/init` → `openExternal(res.data.url)` и всё.

Добавить:
1. Сохранить `label` из ответа init.
2. Состояние «Ожидаем подтверждение оплаты…» на экране Подписка (спиннер + текст из темы, §8).
3. Poll `GET /api/payments/status/{label}` каждые 4 с, максимум 10 минут; учесть VPN: запрос через tunnel API как остальные (`api`-клиент уже это делает).
4. `completed` → toast/плашка «Оплата получена!» + `fetchProfile()`; авто-reconnect при восстановленной подписке уже реализован (`pendingConnectAfterSubscriptionRefreshRef`) — переиспользовать.
5. `failed` → показать текст ошибки из темы + кнопка «Попробовать снова».
6. Таймаут poll — «Если вы оплатили, подписка активируется автоматически в течение нескольких минут» (профиль обновится через ConfigSync).

### 7.2 Android (`android/`, ветка `android`)

`ApiService.kt`: добавить `@GET("api/payments/status/{label}")`. В `PaymentResponse` добавить `label`.
UI экрана Подписка (Compose): те же состояния, что PC (§7.1), тексты/цвета из `ThemeData`. Оплату открывать в **внешнем браузере** (Custom Tabs / `ACTION_VIEW`), не WebView. Poll во ViewModel с lifecycle-отменой.

### 7.3 iOS

Вне scope — добавить пункт в TASKS (паритет экрана подписки).

### 7.4 ConfigSync

`profile_revision` уже включает подписку — активация поднимет ревизию, клиенты подтянут профиль и без poll. Poll нужен только для мгновенного UX на открытом экране оплаты.

---

## 8. Server-driven UI (обязательный чеклист проекта)

Новые поля `ThemeResponse` (`app/schemas/vpn.py`) + дефолты + `theme_settings.normalize_theme_data`:

| Поле | Дефолт |
|---|---|
| `payment_waiting_text` | «Ожидаем подтверждение оплаты от ЮMoney…» |
| `payment_success_text` | «Оплата получена! Подписка активирована.» |
| `payment_failed_text` | «Платёж не прошёл. Попробуйте ещё раз.» |
| `payment_timeout_text` | «Если вы оплатили — подписка активируется автоматически в течение нескольких минут.» |
| `payment_success_page_title` | «Оплата принята» |
| `payment_success_page_text` | «Вернитесь в приложение Silent VPN — подписка активируется автоматически.» |

1. `backend/app/schemas/vpn.py` — поля.
2. `backend/admin-ui/src/pages/ThemePage.tsx` — группа «Оплата».
3. `backend/admin-ui/src/components/ClientPreview.tsx` — превью экрана Подписка с этими текстами.
4. PC — `clientTheme.ts` + использование в §7.1.
5. Android — `ThemeData` + использование в §7.2.
6. Никаких хардкод-текстов оплаты в клиентах (fallback-дефолт в коде клиента допустим, как в остальных полях).

Страница §6.5 берёт `payment_success_page_*` из темы.

---

## 9. Ручная настройка кошельков (делает владелец, не код)

Для **каждого** кошелька в кабинете YuMoney (https://yoomoney.ru → Настройки → Уведомления / HTTP-уведомления):
1. URL: `https://132-243-234-162.nip.io/api/payments/yumoney/notify`
2. Включить «Отправлять HTTP-уведомления».
3. Скопировать «секрет для проверки подлинности» → `.env` на VPS: `YUMONEY_SECRET_N=` (номер = номеру `YUMONEY_WALLET_N`).
4. Кнопка «Протестировать» в кабинете — бэкенд должен ответить 200 (тестовое уведомление имеет пустой label — см. §5.3).

`.env` на VPS (`/opt/silent-vpn/backend/.env`):
```
YUMONEY_WALLET_1=4100...
YUMONEY_SECRET_1=...
YUMONEY_WALLET_2=4100...
YUMONEY_SECRET_2=...
# добавление 3-го кошелька = только эти две строки + restart api:
# YUMONEY_WALLET_3=...
# YUMONEY_SECRET_3=...
```

После правки `.env`: `docker compose restart api` (env читается на старте).

---

## 10. Безопасность — итоговый чеклист

- [ ] Подпись sha1 проверяется per-wallet секретом; невалидная → 400, ничего не меняем
- [ ] Сумма уведомления сверяется с суммой платежа (`withdraw_amount`, допуск 0.01; fallback `amount >= 0.93*expected`)
- [ ] `codepro=false`, `unaccepted!=true`, `currency=643`
- [ ] label уникален per-платёж, генерируется сервером (`secrets.token_hex`), клиент его не выбирает
- [ ] `with_for_update()` + unique `operation_id` → нет двойной активации при повторных/конкурентных уведомлениях
- [ ] Активация ТОЛЬКО из webhook; `/status/{label}` — read-only и только свои платежи (`user_id` фильтр)
- [ ] Секреты только в `.env` на VPS; в git/логи не попадают (кошелёк в логах маскировать)
- [ ] Endpoint `/api/payments/yumoney/notify` без auth (это спека YuMoney), но защищён подписью; доступен только по HTTPS через nginx (существующая схема)
- [ ] Ошибки обработки уведомления не приводят к 5xx-циклу ретраев YuMoney (try/except → лог + 200, кроме невалидной подписи)

---

## 11. Тест-план — ОБЯЗАТЕЛЕН, часть реализации

> **Реализация не считается завершённой без прогона ВСЕХ тестов этого раздела.**
> Реализующий агент по окончании кода обязан: написать тесты §11.1–11.3, прогнать их (все зелёные), выполнить smoke §11.4 и приложить результаты в отчёт. Пропуск любого пункта = задача не закрыта.

### 11.1 Unit: кошельки и подпись (`backend/tests/test_payment_wallets.py`)

- `get_wallets()`: 2 кошелька / 5 / 10 / дырки в нумерации (`WALLET_1`, `WALLET_4`) / 0 кошельков (init → понятная ошибка 503, не 500-трейс)
- распределение: 200 вызовов `_pick_wallet()` при 3 кошельках → каждый выбран хотя бы 30 раз
- `secret_for_wallet`: свой `SECRET_N` / fallback на общий `YUMONEY_SECRET` / кошелёк не из списка
- подпись sha1: валидная / невалидная / пустой секрет → всегда False (не True!)
- `build_payment_url`: receiver = ровно тот кошелёк, что записан в Payment (регресс бага №1); urlencode русского текста; label в url = label в БД

### 11.2 Unit: имитация ВСЕХ сценариев уведомлений (`backend/tests/test_payment_notify.py`)

Каждый сценарий — отдельный тест, уведомление собирается как настоящая форма YuMoney (все поля + корректный/искажённый sha1_hash). После каждого негативного теста проверять **три** утверждения: платёж НЕ completed, подписка НЕ создана/не продлена, ответ не вызывает ретрай-шторм (200 для валидной подписи, 400 для невалидной).

**Успешные оплаты:**
- [ ] monthly / quarterly / yearly — точная сумма → completed, подписка на 30/90/365 дней
- [ ] оплата при активном trial → trial cancelled, новая подписка от «сейчас»
- [ ] оплата при активной платной подписке → продление от max(expires_at)
- [ ] оплата с промокодом → сумма со скидкой принята, `use_count+1`, `pending_promo_code` очищен
- [ ] `withdraw_amount` отсутствует, `amount` = сумма минус комиссия (≥93%) → completed
- [ ] первая оплата invitee → реферальный бонус +30/+30 (мок referral_service или проверка вызова)

**Ошибки и обходы (все должны быть отбиты):**
- [ ] невалидный sha1_hash → 400, платёж pending
- [ ] подпись секретом ДРУГОГО кошелька (уведомление «кошелька 2» по платежу «кошелька 1») → отказ
- [ ] сумма меньше тарифа (`sum=1` атака из §3.2) → failed, лог WARNING, подписки нет
- [ ] сумма больше тарифа (переплата) → completed (деньги получены), лог INFO
- [ ] `codepro=true` → игнор, pending
- [ ] `unaccepted=true` → игнор, pending
- [ ] `currency != 643` → игнор
- [ ] label несуществующий / пустой / чужого формата (`ss...` из SilentShield) → 200 «ignored», ничего не изменилось
- [ ] label существующего платежа, но с изменённым регистром/пробелами → не находит (точное совпадение)
- [ ] повтор того же уведомления (тот же operation_id) 3 раза подряд → одна подписка, ответы 200
- [ ] ДВА уведомления с разными operation_id по одному label → активация одна (платёж уже completed)
- [ ] уведомление по платежу со status=failed → не реанимирует
- [ ] тестовое уведомление из кабинета (пустой label, валидная подпись любого кошелька) → 200, БД не тронута

**Гонки (asyncio.gather):**
- [ ] 2 конкурентных notify по одному label → ровно одна подписка (FOR UPDATE)
- [ ] 10 конкурентных notify (5 валидных повторов + 5 мусорных) → одна подписка, ни одного 500
- [ ] два пользователя A и B: оба init, приходит notify только по label A → у A активна, у B pending (сценарий «двое платят одновременно»)

**Обходы через клиентские endpoint'ы:**
- [ ] `GET /status/{label}` чужого пользователя (JWT user B, label user A) → 404, статус не раскрыт
- [ ] `GET /status/{label}` не меняет status в БД (read-only, 3 вызова подряд)
- [ ] `POST /init` с несуществующим plan_type → 400
- [ ] `POST /init` неверифицированным пользователем → 403 (существующий `get_verified_user`)
- [ ] прямых endpoint'ов активации («confirm», «record», «activate») в роутере НЕТ — тест на 404

### 11.3 Unit: статус и TTL (`backend/tests/test_payment_status.py`)

- pending → completed после notify (тот же label)
- pending старше 24 ч → status endpoint возвращает failed (lazy-expire)
- notify по «просроченному» платежу → всё равно активирует (деньги получены) + лог

### 11.4 Smoke на проде (`backend/scripts/smoke_payments.py`, по образцу `smoke_referral.py`)

- `/plans` — 3 тарифа с ценами из .env
- `/init` × 10 — url валиден, receiver ∈ списку кошельков, label уникальны, оба кошелька встретились
- `/status/{label}` = pending; чужой label → 404
- симуляция notify на прод-эндпоинт с **заведомо неверной** подписью → 400 (проверка, что защита включена на проде)
- `/yumoney/notify` доступен без auth снаружи по HTTPS (иначе YuMoney не достучится)

### 11.5 Ручной e2e (владелец + агент)

- реальный платёж на минимальный тариф с каждого кошелька; активация БЕЗ каких-либо действий в клиенте
- кнопка «Протестировать» в кабинете YuMoney каждого кошелька → 200
- PC debug + Android debug: экран ожидания → «Оплата получена» → авто-reconnect; таймаут poll → текст из темы

### 11.6 Как запускать

- Unit: `cd backend; pytest tests/ -k payment -v` (если pytest-инфраструктуры нет — создать `backend/tests/conftest.py` с in-memory/тестовой SQLAlchemy-сессией по образцу `test_referral_unit.py`)
- Smoke: `cd backend; python scripts/smoke_payments.py`
- В отчёте реализации: вывод pytest (счётчик passed) + вывод smoke

---

## 12. Порядок работ для реализующего агента

1. Backend: config (10 кошельков) + хелперы кошельков + фикс `build_payment_url` (§5, §6.2)
2. Backend: модель/ALTER (`operation_id`, `paid_amount`, `promo_code`) (§6.1)
3. Backend: переписать `process_payment_notification` по чеклисту (§6.3)
4. Backend: `GET /payments/status/{label}` + success-page (§6.4–6.5)
5. Theme-поля + админка (ThemePage, ClientPreview) (§8)
6. **Полный прогон тестов §11.1–11.3 (unit: все имитации оплат, ошибок, обходов, гонок) — все зелёные. Без этого дальше не идти.**
7. PC-клиент (§7.1) → debug-сборка, проверка
8. Android-клиент (§7.2) → debug APK, проверка
9. `cd backend/admin-ui && npm run build` → `python scripts/deploy_stable.py`
10. **Smoke на проде §11.4 (`scripts/smoke_payments.py`) — все проверки OK**
11. Владелец: настроить HTTP-уведомления + секреты обоих кошельков (§9), «Протестировать» из кабинета
12. Ручной e2e §11.5 (реальный платёж с каждого кошелька, активация без действий в клиенте)
13. Отчёт: вывод pytest + smoke (§11.6); обновить `.cursor/APIS.md` (payments section: status endpoint, per-wallet секреты, wallet env-схема) и «Последние изменения» в `MEMORY_BANK.md`; закрыть задачу в TASKS.md про документацию YuMoney webhook flow
14. Push: `backend` → `main`, `pc` → `pc`, `android` → `android` (по явной команде пользователя)

**Не делать:** активацию из клиента; общий секрет на все кошельки; WebView для оплаты; новые deploy-скрипты; хардкод текстов оплаты в клиентах; **закрывать задачу без прогона всех тестов §11**.
