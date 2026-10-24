# Автоматическое определение операторского whitelist

Снимок: **24 октября 2026, Europe/Moscow**. Исследованы только публичные README/исходники указанных проектов. Ничьи VPS, подписки и пользовательские соединения не тестировались; production-политика не менялась. `backend/AGENTS.md` и вложенный `backend/research/AGENTS.md` при проверке отсутствовали.

## Главный вывод

Нужно разделять **membership в опубликованном наборе** и **наблюдаемую доступность конкретного сервиса из ограниченной мобильной сети**. Сам WLChecker предупреждает, что совпадение с базой не гарантирует доступность у оператора/региона/SIM. Regstar2 намеренно измеряет отдельный cellular transport и отдельно предупреждает, что даже такие измерения не раскрывают внутренние правила оператора. [WLChecker README](https://github.com/xorleesBit/WLChecker#readme), [WhiteListChecker README](https://github.com/Regstar2/white-list-checker#readme).

Инженерный вывод: зарубежный VPS, Check-Host и обычный российский проводной сервер могут проверять DNS/работоспособность сайта, но не устанавливают его доступность на мобильном операторе при ограничениях. Для второго необходимы доверенные probes на соответствующей физической сети с привязкой к оператору, укрупнённому региону, времени и состоянию ограничений.

## Что можно взять из существующих решений

### xorleesBit/WLChecker: хороший индекс происхождения, не детектор сети

Apache-2.0; последний commit `72f4b975d60a0e81f84d202af705875324d93bf1`, 17 сентября 2026. [LICENSE](https://github.com/xorleesBit/WLChecker/blob/72f4b975d60a0e81f84d202af705875324d93bf1/LICENSE), [история](https://api.github.com/repos/xorleesBit/WLChecker/commits?per_page=1).

[README](https://github.com/xorleesBit/WLChecker#readme) различает `strict` (точные verified IP из TWL), `verified` (+ производные подсети), `balanced` (+ hxehex), опрашивает источники каждые шесть часов. Score — внутренний приоритет источника, не вероятность успеха. [main.go](https://github.com/xorleesBit/WLChecker/blob/72f4b975d60a0e81f84d202af705875324d93bf1/main.go) подтверждает URL hxehex/TWL, таймер и поиск родительских доменов в SQLite: семантика доменов фактически suffix. Самостоятельного доказательства доступности через cellular здесь нет. Лицензия программы не перелицензирует входные данные.

Полезно перенять: provenance, раздельные типы свидетельств, cached last-good, видимый статус источников. Нельзя превращать `verified subnet` в утверждение, что проверен каждый адрес сети.

### LL33ch/dpi-checker: браузерная диагностика плюс тот же membership

Последний commit `b2398f2dbaeae67bccc25ad273e2b62fcda8fd72`, 28 мая 2026; GitHub license отсутствует, LICENSE в проверенном дереве не найден — не копировать реализацию без установления условий. [метаданные](https://api.github.com/repos/LL33ch/dpi-checker), [история](https://api.github.com/repos/LL33ch/dpi-checker/commits?per_page=1).

[check-site.ts](https://github.com/LL33ch/dpi-checker/blob/b2398f2dbaeae67bccc25ad273e2b62fcda8fd72/src/shared/api/check-site.ts) делает браузерный HTTPS `fetch` с `no-cors`, таймаутом и повторами. Успех такого fetch не доказывает нормальную работу приложения/всех HTTP-ответов. Маршрут следует браузеру, то есть может проходить VPN.

[useWlIpChecker.ts](https://github.com/LL33ch/dpi-checker/blob/b2398f2dbaeae67bccc25ad273e2b62fcda8fd72/src/widgets/wl-ip-checker/model/useWlIpChecker.ts) загружает TWL verified.txt и два списка подсетей; exact IP сравнивает через Set, прочие — CIDR membership с эвристическим score. Это не независимый источник подтверждения. [README](https://github.com/LL33ch/dpi-checker/blob/b2398f2dbaeae67bccc25ad273e2b62fcda8fd72/README.ru.md) описывает дополнительные DPI-тесты; числовые пороги и проценты нельзя считать универсальной гарантией.

### Regstar2/white-list-checker: полезный образец настоящих cellular probes

MIT; последний commit `49563138db2ac03c8ec40f569b5bd6948d2f0fd1`, 6 сентября 2026. [LICENSE](https://github.com/Regstar2/white-list-checker/blob/49563138db2ac03c8ec40f569b5bd6948d2f0fd1/LICENSE), [история](https://api.github.com/repos/Regstar2/white-list-checker/commits?per_page=1).

[CellularNetworkProvider.kt](https://github.com/Regstar2/white-list-checker/blob/49563138db2ac03c8ec40f569b5bd6948d2f0fd1/app/src/main/java/com/whitelistchecker/domain/checker/CellularNetworkProvider.kt) явно запрашивает `TRANSPORT_CELLULAR` через requestNetwork. [README](https://github.com/Regstar2/white-list-checker#readme) описывает network-bound HTTPS с обычной TLS/hostname verification, DNS как вспомогательный сигнал, локальную историю; центральный публичный сервис удалён. Подходит как архитектурный образец измерителя, а не готовая постоянно обновляемая серверная база. При интеграции нужно отдельно доказать, что probe минует наш VPN, а не только получает cellular-labelled объект.

### TWL: исторические наблюдения, не поддерживаемая живая истина

[openlibrecommunity/twl](https://github.com/openlibrecommunity/twl) архивирован 30 сентября 2026; последний commit `4538b440842a8d46b653034e7623b1259a8f9256`. [README](https://github.com/openlibrecommunity/twl/blob/4538b440842a8d46b653034e7623b1259a8f9256/readme.md) сообщает об отсутствии SIM для сканирования и переезде в rewl. Новый проект в этом ограниченном исследовании не проверялся. BSD-3-Clause заявлена badge, но LICENSE-файл и GitHub license не найдены: отдельно выяснить условия данных. [метаданные](https://api.github.com/repos/openlibrecommunity/twl).

[verify.sh](https://github.com/openlibrecommunity/twl/blob/4538b440842a8d46b653034e7623b1259a8f9256/code/scan/script/verify.sh) использует интерфейс для SYN-проверки 443, затем httpx; наличие HTTP-ответа IP не доказывает работу заданного сервиса с правильным hostname. [subnet/main.go](https://github.com/openlibrecommunity/twl/blob/4538b440842a8d46b653034e7623b1259a8f9256/code/subnet/main.go) группирует обнаруженные IP в `/24` и считает заполненность: это **расширение наблюдений**, не проверка остальных адресов. Их массовый scan-подход в Silent не запускать.

[`zarazaex/TWL`](https://github.com/zarazaex/TWL) на момент проверки возвращает HTTP404; нельзя использовать URL как гарантированно действующий автоисточник. [публичный API](https://api.github.com/repos/zarazaex/TWL).

## Предлагаемый механизм для существующего Python backend

Ниже собственное инженерное предложение, не уже реализованная функция и не заявления исследованных проектов.

1. **Collector кандидатов.** Независимый от VPN dataplane worker раз в несколько часов получает только закреплённые в конфигурации HTTPS-источники. Хранит source URL, upstream commit/ETag, source-content hash, fetched_at, observed_at (если известен), license, typed `exact_domain/domain_suffix/exact_ip/cidr`. Получение свежего файла не обновляет observed_at старых измерений. Зеркала общего upstream не считать независимыми голосами.
2. **Валидатор и карантин.** IDNA/дедупликация, лимиты размеров/строк, сохранение exact-семантики, запрет всего TLD и произвольных URL, широкие CDN/облака и CIDR — ручная проверка. Не выводить родительский suffix или весь `/24` из одного успешного узла. Обрыв источника не очищает действующую политику; подозрительный diff остаётся candidate-only.
3. **Контролируемые probes.** Выделенные модемы/SIM либо добровольно включённый клиентский тест, но только каталога безопасных контрольных целей. Никакого пассивного сбора пользовательских доменов/истории, URL-path, сообщений, токенов, точного местоположения или IMEI/IMSI. Хранить минимальные оператор/укрупнённый регион/окно времени/результаты DNS-TLS-HTTP. Без probes статус `candidate`, а не `verified`.
4. **Протокол измерений.** Сервер выдаёт подписанное краткоживущее задание с allowlisted target ID, не произвольный hostname/IP. Probe проверяет direct cellular, локальные и внешние контрольные цели, DNS A/AAAA, TLS с правильным SNI и сертификатом, малый HTTP-запрос без cookies/учётных данных. Captcha/403/ошибку приложения не путать с недоступностью сети. Отсутствие отчёта — `unknown`, не `blocked`.
5. **Безопасный исходящий доступ.** На server и probe ограничить порты/методы/таймаут/трафик/частоту; после DNS и на каждом разрешённом redirect отвергать loopback, private, link-local, multicast, metadata и внутренние адреса. Лучше запрещать redirects и закреплять проверенный публичный IP при сохранении hostname/TLS, чтобы исключить DNS rebinding/SSRF. Не открывать публичную ручку «проверь любой IP». При ошибке probe не сканировать соседние адреса.
6. **Оценка и публикация.** Отдельные evidence: `source_listed`, `direct_observed`, `restricted_direct_observed`, `stale/unknown`. Срок годности и повторные наблюдения на нужном операторе; не обещать универсальность. Policy diff сохраняет VPN-overrides, проходит лимиты изменений и staged/shadow-период; выпуск атомарно с revision, last-good и rollback. Не расширять старый глобальный DIRECT по одному источнику/телефону. Старым клиентам не отдавать неподдерживаемые точные/операторские правила под видом suffix.

Практичный первый этап: source collector + provenance/карантин + административный preview без изменения active policy. Второй — один контролируемый SIM-probe и сопоставление с ручным тестом во время ограничений. Только затем ограниченная автопубликация операторских правил с возможностью выключить её без рестарта VPN. Это не решает Android app-level VPN detector MAX: для него нужен отдельный согласованный механизм исключения приложения.
