# TASKS — Silent VPN

Формат: `[ ]` — не выполнено, `[x]` — выполнено.  
Agent приступает к **первой невыполненной** задаче.  
Статус сверен с коммитами `origin/main`, `origin/pc`, `origin/android` (2026-06-20).

---

### Пуш стабилизации ПК (2026-10-08)

- [x] По явному запросу пользователя закоммитить18 source/test/README файлов без BOM/CRLF-only шума и сборок: pc7c0504ac234ffb0d32d101e6f1bae33439683695
- [x] Push origin/pc выполнен, remote SHA совпадает с local HEAD; Android/iOS и серверный код не менялись
- [x] Зафиксировать накопленный Memory/TASKS журнал отдельным docs-коммитом main, не включая app.zip/logs и не выполняя деплой

### ПК: public API ошибки при запуске VPN и границы правил сайтов (2026-10-08)

- [x] Объяснить: поддомены общие, отдельные CDN пока только по связкам сервисов; YouTube bundle не универсальная browser dependency policy
- [x] Разобрать новый лог: EHOSTUNREACH/ConfigSync, DNS ENOTFOUND отсутствует; runtime health tunnel/public443/2083 сейчас200, точных времён API в агрегированном логе нет
- [x] RED→GREEN real IPC: in-flight public GET→готовый VPN и refused latch+publicfailure; отмена obsolete public chain, fallback to tunnel, POSTno replay, OLCRTC2 прежний, реальные dual failures видимы
- [x] npm149PASS/1SKIP, syntax/diff и упаковка integrityOK; debug build-debug-api-transition-20261008-135506/win-unpacked; без push
- [ ] Пользователь: новая debug, cold start/подключение и ConfigSync sync-state; проверить отсутствие повторных ошибок и полную работу сайтов/оплаты

### ПК: YouTube не полностью загружается в БС (2026-10-08)

- [x] Пользователь принял исчезновение API ENOTFOUND; Chrome воспроизвёл ERR_CONNECTION_CLOSED для yt3.ggpht.com при youtube.com/БС, сравнение через VPN дало200/картинка загружена
- [x] RED→GREEN расширение browser initial/live YouTube на googlevideo/ytimg/ggpht, static DNS seeds без вечного pendingDNS; сохранённый список/описание и приложения прежние
- [x] npm144 PASS/1 SKIP, Go test/vet PASS, JS→native DNS policy integration с обеими модами и удалением; debug build-debug-youtube-sites-20261008-134347/win-unpacked, ASAR/native/integrity checksOK; без push
- [ ] Пользователь: новая debug, БС youtube.com, открыть ролик заново — превью/аватар/видео/перемотка; проверить ЧС и независимые приложения. Ручной DoH/dynamic video cache остаются ограничением DNS/IP политики

### ПК: public API nip.io ENOTFOUND (2026-10-08)

- [x] Отличить DNS отказ отдельного public hop от общего VPN/API failure: actual DNS сейчасOK, tunnelhealth200
- [x] RED→GREEN real publicDirectRequest: fixed hostname подключается к известному hiveIP, сохраняет443/HTTPS Host/SNI, standby не подменять
- [x] Настоящий HTTPShealth поIP сoriginal Host/SNI200; npm143 PASS/1 SKIP, scopedAPI4/4
- [x] Debug build-debug-api-ip-20261008-133353/win-unpacked, package/source/native/Wintun/WDTT integrity; без push/deploy
- [ ] Приёмка нового запуска: отсутствует ENOTFOUND fixed public API; реальную авторизованную синхронизацию профиля проверить отдельно отhealth

### ПК: предупреждения профиля и восстановление tunnel API (2026-10-08)

- [x] Пользователь предварительно подтвердил работу сайтов; отделить штатный запуск от ConfigSync/public API warnings
- [x] Read-only tunnel HTTP: health200, users/me401 без auth; не объявлять общий VPN сломанным и не скрывать реальные warnings
- [x] RED→GREEN real main IPC: ECONNRESET transient, startup ECONNREFUSED retry, stable cell fallback30с затем tunnel recheck; focused3/3, полныйнабор141 PASS/1 SKIP до добавления третьего теста
- [x] Debug build-debug-api-recovery-20261008-132926/win-unpacked, package/source/native/Wintun/WDTT integrity; без push/deploy
- [ ] Приёмка новой debug: профиль обновляется после временного сбоя API, нет постоянного ухода на public при работающем tunnel; закрытие→другая сборка без destroyed-window

### ПК: VPN только после переключения режима, ошибка закрывающегося окна (2026-10-08)

- [x] Проверить новый лог: migration11 routes выполнена; при фиксированном БС настоящий Chrome2ip даёт VPN exit, другой сайт direct, итоговая политика не инвертирована
- [x] RED→GREEN startup JS+Go: pendingDNS не даёт выбранным сайтам уходить direct до IP snapshot; app exclusions сохраняются, unresolved retry15с
- [x] RED→GREEN real encrypted WG/TCP idle connection при SetTcpEntry failure: reverse RST в TUN по последнему ACK только изменённого flow; GREEN5/5, native22/22+vet
- [x] RED→GREEN second-instance destroyed window: пропуск при выходе/уничтоженном окне; npm139 PASS/1 SKIP
- [x] Debug build-debug-startup-live-20261008-132130/win-unpacked, package/source/native/Wintun/WDTT integrity; без push/deploy
- [ ] Приёмка: cold start без нажатия режима сайтов, live ЧС/БС/добавление/удаление при открытых вкладках, закрытие клиента→открытие другой сборки без JavaScript exception

### ПК: выбранный 2ip обходит VPN из-за старого global /32 (2026-10-08)

- [x] Получить симптом: сайты открываются, VPN выход неверен; проверить запуск native/UAC (child elevated клиента, отдельной службы нет)
- [x] Настоящий Chrome RED: выбранный2ip показывает тот же РФ IP, что сайт вне БС; найти physical188.40.167.81/32 metric1 ActiveStore, который обходит native
- [x] RED→GREEN policy seam: удалить совпадающие legacy site routes перед ACK, ограничить gateway/metric/ActiveStore/NetMgmt, сохранить PersistentStore и current API/peer/VK protected targets
- [x] Read-only реальный cleanup selection:11 кандидатов включая2ip; npm138 PASS/1 SKIP, syntax, debug build-debug-legacy-routes-20261008-130609 и package/integrity проверки; без push
- [x] Приёмка migration: elevated клиент удалил11 старых routes по присланному логу, при фиксированном БС новый Chrome2ip даёт VPN exit; дефект перехода/старта исправлен отдельно выше, его приёмка ещё нужна

### ПК: уточнить реальное поведение Chrome при рабочих DNS/HTTPS (2026-10-08)

- [x] Проверить сохранённые tunnel DNS и /1 маршруты, actual native ACK БС7/12IP/1app, DNS reply/internal API/HTTPS ordinary process200 и public egress IPv4
- [x] Проверить настоящий browser direct stack HTTPS через physical47 под активными /1:200; удалить диагностическую пробу, системную сеть не менять
- [x] Не считать SetTcpEntry warning установленной причиной: injection317 encrypted TCP test и на старом коде PASS; тестовый рефактор откатить. Actual site-router token elevated1
- [x] Получить точный симптом Chrome и воспроизвести нарушение: выбранный2ip показывает российский выход; причина stale physical /32, исправление и приёмка выше

### ПК: DNS доменов через VPN, policy ACK и Wintun warning (2026-10-08)

- [x] Уточнить Chrome; по логу отделить Wintun foreign rename0x490 от фактического native startup failure, wg-turn Up/read-only состояние подтверждено
- [x] RED→GREEN live snapshot: использовать переданные VPN DNS вместо прежнего LAN resolver; startup без DNS сохранить
- [x] RED→GREEN sendLog: Sites/Apps success и native ACK/counts сохраняются в main log, recoverable rename не красный, реальные native errors остаются видимыми
- [x] PC137 PASS/1 SKIP, syntax/diff;7 реальных правил→12 IP/unresolved0 за293мс; debug build-debug-vpn-dns-20261008-123703/win-unpacked и package integrity, без push
- [ ] Приёмка Chrome/исключений сайтов и программ на последнем debug; если повторится — сопоставить Sites native ACK/counts/changedFlows из нового лога

### ПК: DNS до старта site-router блокировал VPN (2026-10-08)

- [x] Повторная жалоба после close/start; воспроизвести реальный main prepare со stalled pre-VPN DNS: RED
- [x] Удалить DNS ожидание из initial policy, сохранить домены/literal IP/app rules; GREEN
- [x] Ограничить post-tunnel browser DNS snapshot общим2с/cancel/8domain workers; сохранять cache оставшихся доменов и удалять исключённые из списка
- [x] PC135 PASS/1 SKIP, JS syntax/diff; debug build-debug-dns-startup-20261008-122348/win-unpacked + ASAR/native/Wintun/WDTT checks; без commit/push и без воздействия на активный установленный клиент
- [ ] Проверить на новой сборке cold start и повторный запуск после полного выхода, затем live site/app исключения

### ПК: старт после подтверждения Windows (2026-10-08)

- [x] Проверить присланный workers63/traffic0/timeout лог; пользователь уточнил, что после подтверждения окна site-router всё заработало
- [x] Read-only подтвердить native process, wg-turn Up, адрес и /1 маршруты, successful main log; firewall path-specific rules присутствуют, точный тип окна пока не подтверждён
- [ ] Проверить именно live-редактирование списков из последней сборки — восстановление подключения после разрешения Windows не подтверждает этот сценарий

### ЧС/БС сайтов, live-исключения ПК, debug и push (2026-10-08)

- [x] Переименовать только кнопки сайтов в ЧС/БС на Android/ПК/iOS; описания сохранить, OpenWrt без таких кнопок не менять
- [x] Windows: RED→GREEN существующих site/app flows; пересчитать только изменившиеся маршруты, закрыть соответствующие direct-сокеты/TCP TCB без WG restart; сохранить DNS/CDN оставшихся доменов при редактировании списка
- [x] Android295/295 + assembleDebug, PC132 PASS/1 POSIX SKIP, native20/20 + go vet, renderer/package/integrity/diff проверки
- [x] Debug Android: android/app/build/outputs/apk/debug/SilentVPN-debug.apk; Windows: pc/build-debug-sites-20261008-120425/win-unpacked, SilentVPN-Admin.bat
- [x] По разрешению пользователя push только Android324ce5a / PCf8014a1; origin HEAD проверены, iOS переделку оставить локально до Mac
- [ ] Пользовательская проверка нового Windows live-обновления сайтов/программ при активном VPN; предыдущая сборка и оплата с main VPN уже приняты
- [ ] Проверить iOS переделку на Mac до отдельной публикации; browser-only Linux/macOS/экспериментальные PC olcrtc пути отдельно не перенесены

### Windows PC: сайты отдельно от программ, debug без push (2026-10-08)

- [x] Воспроизвести общий bypass от сайта регрессом RED; заменить Windows site/app host-routes на native per-process WG routing, GREEN
- [x] Сохранить приоритет программ, browser-only домены/IP, DNS/CDN и live policy без WG restart; owner PID/path/children, direct physical interface, startup/disconnect/exit guards
- [x] Проверить npm132 PASS + 1 POSIX SKIP, native15 PASS, go vet/JS syntax/renderer debug; собрать Windows x64 `pc/build-debug-sites-20261008-114204/win-unpacked` и проверить содержимое
- [x] Пользователь принял сайты/программы и оплату при main VPN; отдельно сообщил о необходимости ручного reconnect после редактирования исключений. Разрешил новый debug и push Android/ПК (см. следующую запись)
- [ ] Browser-only Linux/macOS и экспериментальные olcrtc пути отдельно не перенесены; в этой сборке исправлен Windows WG/WDTT

### Раздельный commit/push исправлений (2026-10-08)

- [x] По явной команде пользователя разделить Android сайты (`32445cc`) и оплату (`4e3f3f4`), backend trial — отдельный commit с 6 тестами и API-документацией
- [x] Обеспечить native build из чистого checkout для 4 ABI/API24/Go1.26.3 через Gradle; testDebugUnitTest+assembleDebug успешны, backend6/6 и kick-storm ok, staged diff без whitespace ошибок
- [x] Публикуются только origin/android и origin/main; PC переключатель уже запушен ранее, iOS/OpenWrt/архивы/логи не включать; release/OTA/deploy не выполнять

### Приоритет исключений сайтов и приложений (2026-10-08)

- [x] Проверить Android: режим сайтов ограничивает общие AllowedIPs всех участвующих приложений; трафик остальных назначений выходит напрямую, что на ограниченной сети выглядит как потеря доступа
- [x] Пользователь подтвердил: список сайтов только для браузеров, прочие программы по отдельному списку приложений
- [x] Пользователь подтвердил: после исправления crash вылетов нет; жалобу на все приложения уточнил — приложения работают
- [x] Исправить обнаруженное исключение при закрытии status stream: RED 1/2→GREEN 2/2, Android295/295, assembleDebug; старый reader не отключает замену, неожиданный выход текущего native очищает VPN
- [x] Пользователь установил crash исправление: вылетов при смене режима/удалении больше нет
- [ ] При повторной жалобе на город mail.ru сверить фактический внешний IP/соединения; отдельное сопоставление города с IP пока не проведено
- [x] Воспроизвести CSS/JS static.2ip.io ERR_CONNECTION_REFUSED через CDP; подтвердить carrier/VPN DNS mismatch (172.67.x /188.114.x), CSS через VPN IPv4 HTTP200; простое добавление static пользователь проверил без эффекта
- [x] Обрабатывать фактические WG DNS-ответы выбранных доменов/поддоменов только для browser UID; TTL/cap/boundary, VPN DNS warm-up и отдельный кэш сети; RED→GREEN, native9/9 на телефоне, Android295/295, assembleDebug
- [x] Пользователь установил APK с DNS исправлением и подтвердил полное оформление 2ip.io: «да теперь все хорошо»; обычные приложения работают, crash отсутствует. Native9/9 и Android295/295, без push
- [ ] Ручной DoH/DoT и прямые браузерные сайты отдельно не проверены; удаление временного static.2ip.io просили сделать, отдельного подтверждения нет
- [ ] Дополнительные сценарии browser-only и PC/iOS: там пока общие IP-маршруты. Пользователь принял Android и разрешил scoped commit/push, release/OTA не запрошены

### Проверка trial после верификации и реального VPN-трафика (2026-10-08)

- [x] Подтвердить по БД и реальному обработчику verify_email: 3 дня от подтверждения 8 октября, регистрация 17 сентября не сокращает срок; тесты 6/6
- [x] Проверить server5: GETCONF/handshake, manifest allowed, нет deny по IP, NAT/egress и DNS ответ исправны
- [x] Сопоставить Android с целевым device-id: сначала маршруты только списка сайтов, затем полный туннель; после переключения счётчики выросли до 3.7МБ ответов, HTTPS пакеты идут в обе стороны
- [ ] Получить от пользователя подтверждение открытия сайтов; вопрос о статусе подключения и всех/одном сервере пока без ответа. Production-код/даты/настройки не менять без установленной причины; push по-прежнему запрещён

### Критический trial: доступ одного аккаунта не зависит от других на устройстве (2026-10-08)

- [x] Воспроизвести профиль с активным trial и отказ VPN402; подтвердить причину в межаккаунтном fingerprint guard
- [x] По решению пользователя оставить один trial на аккаунт; убрать guard из config/register без изменения сроков, формата API, собственных проверок подписок и лимитов
- [x] Регресс RED→GREEN 5/5; проверить просроченную/отменённую историю и неизменность срока при повторном входе; пройти kick-storm и остальные preflight
- [x] Scoped stable deploy двух Python-файлов; DNAT/health/alt2083 OK, kick0/20с, wdtt PID764 сохранён; живые профиль и конфиг проблемного аккаунта HTTP200 и trial до 11 октября 09:28 МСК
- [x] Пользователь разрешил отдельный commit/push backend trial; стабильный деплой выполнен ранее, повторно не требуется

### Оплата при включённом основном VPN (2026-10-08)

- [x] Проверить Android init/preview/poll и остальные клиенты; выявить direct API из исключённого приложения при main/LTE и отсутствие рабочего браузерного канала в пользовательском сценарии
- [x] Использовать рабочий held-bootstrap при main, сохранить прежний сервер и восстановить после оплаты/возврата, отмены, ошибки или таймаута; ручное отключение отменяет восстановление, сохранение переживает пересоздание процесса
- [x] Ограничить подготовку оплаты общим дедлайном, не повторять init после отмены, сериализовать очистку/новую попытку и сохранить poll/cancel для созданного label
- [x] Регресс RED→GREEN, Android293/293 + assembleDebug, PC126/126; остальные клиенты/сервер/wdtt без изменений; commit/push не выполнять без новой команды
- [ ] Установить APK и проверить живые сценарии VPN выкл / main вкл → ЮMoney → отмена или подтверждение → прежний сервер; adb-установка не состоялась, телефон отключён

### Сайты: «Мимо VPN / Через VPN» (2026-10-08)

- [x] Android: переключатель режима для общего списка сайтов/JSON, сохранение и маршрутизация только выбранных сайтов через VPN, API/DNS/TURN и TV-focus сохранены
- [x] PC Windows/Linux/macOS: тот же UI и сохранение, live-маршруты, отмена/очистка при отключении и возврат прежних маршрутов при ошибке
- [x] Оставить описание прежним, меняя только «мимо VPN» на «через VPN»; добавить настройку и маршрутизацию в исходники iOS, OpenWrt без пользовательского списка не трогать
- [x] Android 282/282 + assembleDebug, PC126/126 + renderer build + типы изменённых файлов, browser mock режимов/reload/JSON/320px; без установки, сервера, commit/push
- [x] По команде пользователя запушить только эту задачу: Android `eaa9c06` → origin/android, PC `f4d7f27` → origin/pc, удалённые SHA совпали; iOS с зависимостями от прежнего WIP остаётся локально, версии/OTA без изменений
- [ ] Проверить новое поведение на физическом Android и PC; собрать и проверить iOS через Xcode на Mac

### Админка: скорость «Пользователей» и дашборда (2026-09-30)

- [x] Замерить действующие API против быстрых «Подписок»: Users 1232/815 КБ; dashboard 1232/2,28 МБ; холодное обновление онлайн ~2 с
- [x] Добавить совместимый постраничный API/поиск/сортировку Users и быстрый первый ответ дашборда, не блокируемый онлайн и VK-списком
- [x] Убрать дублирование плоских VK-хешей только в opt-in `compact=1`, сохранить старый формат; проверить браузером, unit и сборкой
- [x] Применить через неизменённый `deploy_stable.py`: preflight 5/5, health 47–49 мс, kick 0/20 с, wdtt PID 764 и DNAT стабильны; на живой базе Users 33,8 КБ/50, fast dashboard 1,5 КБ/173–247 мс, compact 1,20 МБ

### Админка «Пользователи»: тариф 3/5 и ручной лимит (2026-09-30)

- [x] Воспроизвести постоянное `/3` на платном тарифе `monthly_5` браузерным регрессом; найти жёсткое значение в UI и отсутствие поля в API списка
- [x] Показать тариф 3/5 и фактический лимит; добавить выбор 3/5/«По тарифу» в колонке без открытия сессий
- [x] Сохранить персональный nullable override через админский PUT и общий сервисный расчёт клиента/VPN, не меняя оплаченный срок/цену и действующие сессии
- [x] Проверить браузерный сценарий, серверный список/API, тарифные тесты, kick-storm и сборку админки
- [x] Применить через существующий `deploy_stable.py`: preflight/postflight, health200/41мс, kick0/20с, schema добавлена, SHA7 совпали, wdtt PID764 и DNAT прежние, админка200; живой активный `*_5` отображается как 5 (1/1). Реальные лимиты не переключались


### HTTPS по IP: диагностика и stable deploy (2026-09-30)

- [x] Считать живой отчёт и логи: доменный HTTPS 1/3 RU при TCP/DNS/ping 3/3, мир 2/2; московские ru1/ru2 timeout, SNI-блокировка не подтверждена
- [x] Воспроизвести ложный обрыв raw-IP `/api/health` после TLS из-за nginx `return 444`; разрешить только точный health, сохранить закрытие остальных raw-IP URL
- [x] Проверить контракт nginx 4/4, availability 58/58, admin-ui build и diff; применить неизменённый `scripts/deploy_stable.py` с 5 preflight, health200, kick0, сохранёнными wdtt PID/DNAT
- [x] После deploy проверить raw-IP health200, закрытые admin/прочий API по IP, доменные health/admin200; Check-host ru3/de1/de2 HTTP200, ru1/ru2 timeout; штатный отчёт 05:22:26 UTC теперь IP 1/3 и domain 1/3; 2083 даёт такой же результат
- [ ] Установить сетевую причину таймаутов двух московских точек; это отдельная реальная причина статуса `https_degraded`, кодом контроля она не устраняется


### Админка: снятие подписки с предоплатой (2026-09-29)

- [x] В профиле меню «Подписки» добавить «Снять подписку · N дн.» с остатком по expires_at, включая предоплату и тарифы 3/5
- [x] Подключить штатный revoke, обновлять профиль после снятия, показать ошибку и блокировать повторный запрос
- [x] Воспроизвести отсутствие кнопки; проверить 9 браузерных сценариев с подменённым API, сборку, kick-storm и diff; реальные подписки не снимать
- [x] По явному возобновлению выполнить существующий deploy_stable.py без изменений: 5 preflight, health200/45мс, kick0/20с, wdttPID764 со стартом19.09, HTTP200 и совпадение SHA опубликованных index/JS/CSS, nginx200
- При первой подготовке пользователь остановил ненужное расширение deploy_stable.py; оно полностью откатано. Реальные отзывы подписок, commit/push не выполнялись.

### Лендинг: обновление оплаты (2026-09-29)

- [x] Сверить действующие тарифы 3/5 и правила предоплаты; обновить текст, демо, RU/EN и описание лимита устройств
- [x] Проверить JS, diff/CRLF и RU/EN на широком/320px экране; устранить переполнение таблицы
- [x] Запушить только три файла лендинга в silentvpn3/silentvpn3.github.io main (8c79098); Windows Git/GCM silentvpn3, OpenWrt-коммит/stash не публиковать

### Mac-инструкция: пуш правки пользователя (2026-09-29)

- [x] Закоммитить и запушить только правку `index.html` с описанием Mac (`f4f7bd6`); OpenWrt не включать

### Mac-инструкция без воды, пользователь пушит сам (2026-09-29)

- [x] Уточнить пять шагов, подписи скачивания и пароль службы; синхронизировать RU/EN, проверить inline JS и diff без шума
- [x] Сохранить original main/e2ac6c4 и локальные OpenWrt/API-правки в stash; текущую свободную Mac-ветку довести до origin/main25af37f, оставить только index.html изменённым; commit/push не выполнять

### Лендинг: текст установки Mac (2026-09-29)

- [x] Переписать пять шагов установки Mac простым языком: кнопки Intel / Apple Silicon вместо меню Apple и «Об этом Mac»
- [x] Запушить `25af37f` в landing main, только index.html; OpenWrt не менялся

### Лендинг: карточка Mac напротив Linux (2026-09-28)

- [x] Убрать растягивание Linux на всю строку, чтобы Mac стоял справа от Linux в сетке 2×2; на узком экране карточки столбиком
- [x] Проверить позиции локально и запушить `b801c04` в landing main; OpenWrt не менялся

### Лендинг: только Mac (2026-09-28)

- [x] Запушить в `landing` только Mac-страницу (`455f247`: guide.css, guide.js, index.html, mac-applications-folder.png); OpenWrt-коммит и скрипты не пушить
- [x] На живой странице открывается «Установка на Mac», ссылки x64/arm64 на DMG 1.0.168; страницы OpenWrt в этом коммите нет

### Встроенный лог Mac release (2026-09-28)

- [x] Добавить явные debug-условия кнопки/панели в MainScreen; проверить отсутствие панели в release renderer и сохранение в debug, Mac-контракт21/21; версия1.0.168 без commit/push, Mac DMG требует сборки пользователем.

### Предрелизная проверка и push1.0.168 (2026-09-28)

- [x] Перепроверить Android278/PC121/OpenWrt45, payment+renewal56/checkout3/relay7, compatibility/kick-storm; версии/подпись/ресурсы/nativepins/GitHubOTA/права/SHA
- [x] Сохранить исходный OpenWrt API-priority diff отдельно, вернуть рабочий cell-first и проверить фактический failover/tunnel shell loop
- [x] Воспроизвести CRLF shell-archive регрессию, нормализовать только shell при упаковке без изменения бинарников, пересобрать OpenWrt и проверить все packagedfiles
- [x] Подготовить4GitHubReleaseassets и4Pagesфайла с manifest168/install/uninstall/OpenWrt.tgz, обновитьSHA и передать releases/PUBLISH-1.0.168.md; публикацию выполняет пользователь
- [x] Сохранить активный VPN, версии168, весь iOSWIP локально; Mac сборка отдельно, DMG/IPA здесь не строились
- [x] Выполнить разрешённые scoped commit/push PC2e9a60e/OpenWrt8734ae9/backend main530297e и сверить удалённыеHEAD; Android не требует новогоcommit, итоговаядокументационнаяфиксация без измененияисполняемогокода

### Повторная сборка всех релизов без повышения версии (2026-09-28)

- [x] Сохранить Android/PC/OpenWrt1.0.168, iOS1.0.1/build2; использовать принятый bootstrap и прежний APK release-сертификат
- [x] Без taskkill/очистки старых PC-build папок запустить Windows NSIS/Linux DEB в новых каталогах; native Windows/Linux пересобраны, pins сверены, PC121 тест успешен
- [x] Пересобрать OpenWrt Go для aarch64/ARMv7/mipsel/x86_64 и архив1.0.168; OpenWrt41 тест успешен
- [x] Android assembleRelease --rerun-tasks52 задачи, freshAPK168/24libs/4ABI, прежний сертификат/подпись; готовый APK скопирован и SHA сверены
- [x] Windows NSIS/Linux DEB готовы; app.asar168/release flags/pins/GitHub OTA и DEB ELF/права проверены; canonical SHA256/BUILD обновлены, debug сохранён
- [x] Активные wdtt-client PID5288/wireguard2676 прежние; установки/деплоя/публикации/push не было
- [x] macOS/iOS release в Windows недоступны: DMG требует Mac, iOS Xcode/подпись; ранее пользователь собирает Mac сам, исходники Apple остаются локально

### Проверка GitHub-обновлений всех клиентов (2026-09-28)

- [x] Проследить реальные проверки/скачивание Android/TV и Windows/Linux/macOS: metadata GitHub Pages, download GitHub; legacy backend fallback только при отсутствии ссылки, обычный OTA его не использует
- [x] Проверить OpenWrt/iOS: OpenWrt без встроенного OTA, iOS собственного OTA нет; Mac код настроен, но нет опубликованной записи в manifest
- [x] Live manifest/latest Release1.0.167; APK/EXE/DEB HEAD200 и размеры совпали, OpenWrt tgz200; README installer URL404, GitHub tree подтвердил отсутствие скрипта
- [x] 19 Android и6 PC OTA тестов успешны; клиентский код, VPN и публикации не менялись.1.0.168 пока локальная сборка, не публичный OTA

### HTTPS 1/3 и неверный TLS-контроль (2026-09-28)

- [x] Прочитать live-отчёт 16:51:59UTC: TCP3/3, domain HTTPS1/3 (Москва timeout×2, Санкт-Петербург200), world2/2; IP HTTPS даёт Broken pipe также вне РФ, nginx default возвращает444
- [x] Воспроизвести ложный KIND_OK при domain1/3 регрессионным тестом; исправить на https_degraded без утверждения SNI/DPI, пояснить различие локального TLS и внешнего HTTPS
- [x] 58 classifier/10 port-plan тестов и admin-ui build прошли
- [x] Production diff: только classifier/knowledge+UI, backup /tmp/silent-before-https-observation-20260928.tar.gz; canonical stable deploy health69мс/kick0; checksum158+UI совпали, wdtt PID764/DNAT прежние
- [x] Production replay старого отчёта ok→degraded; свежий ручной отчёт17:11:36UTC/62.36с/pending=false: HTTPS1/3, https_degraded без SNI-block
- [x] По команде «пуш и пересобери релизы если нужно» оценить сборки: только backend/админка, клиентские исходники текущим фиксом не менялись; админка уже пересобрана/развёрнута, релизы1.0.168 остаются актуальными
- [x] Push main3f181f3 выполнен и удалённый HEAD проверен; backend после push чистый

### Отдельный сервер уведомлений ЮMoney (2026-09-28)

- [x] Проверить новый сервер 153.52.117.159 (чистый Ubuntu 24.04, без VPN); отдельный подписанный приёмник с SQLite WAL/FULL и повторной HTTPS-доставкой в Улей
- [x] Проверить недоступный upstream, рестарт очереди, конкурентные повторы/подписи: 7 тестов локально и на Ubuntu; backend/renewal/выборочный deploy 58 проверок + kick-storm OK
- [x] HTTPS Let's Encrypt, certbot.timer/deploy hook, nginx и защищённый systemd; отдельный сервер не участвует в VPN
- [x] Подлинные поздние платежи могут завершать expired intent; stable --python-only одного payment_service.py, backup сохранён, health 54 мс, kick 0/20с, wdtt PID 764 прежний
- [x] Пользователь сообщил «уже всё сделал» в кошельках; два реальных кабинетных теста ЮMoney приняты новым сервером и доставлены в Улей с 200, pending=0

### Платежи без подписок, достоверность доступности и push (2026-09-28)

- [x] По явному разрешению пользователя восстановить две quarterly-подписки 17:33/17:36: maksimka892@gmail.com и luntiksi70@gmail.com до 28.12.2026; независимое чтение и replay подтвердили отсутствие повторного начисления
- [x] Установить причину: уведомления этих оплат не достигли nginx/API, исходные заявки pending; пересчёт срока не причина
- [x] Доставку уведомлений вынести на независимый сервер 153.52.117.159; пользователь переключил кошельки, два теста доставлены в Улей с 200
- [x] Воспроизвести недоказанный SNI-вывод, длительность 654.93 с и уменьшение числа проб; подготовить локальный фикс классификации/параллельности/отображения missing nodes
- [x] Проверки: classifier 55, refresh 9, polling 4, port-plan 10, kick-storm OK; admin-ui build
- [x] По явной команде пользователя stable deploy диагностики выполнен: health44мс/kick0, checksum158+UI совпали, wdtt PID764/старт и WDTT_API/CELL_API DNAT прежние
- [x] Прочитать свежий отчёт после deploy/заявки c2e7f0628fce460da04ff82646c32332: 16:51:59UTC, 64.54с, три российские ноды во всех основных пробах, pending=false; ложного SNI-вывода нет, SSH снова доступен
- [x] Повторный явный push: main 717aedd, android 857f3a2, pc a62a074, openwrt 3c36ca9; origin HEAD проверены. Пустые Android CRLF-diff сняты. iOS оставлен локально по выбору пользователя, несвязанные OpenWrt API-priority/timeout + test сохранены вне коммита

### Версии и локальные сборки после приёмки (2026-09-28)

- [x] Поднять Android/PC/OpenWrt 1.0.167 → 1.0.168; iOS 1.0.0/build 1 → 1.0.1/build 2
- [x] Сначала Android debug и Windows debug: версия 1.0.168, Android 278 JVM/PC 121 проверка успешны
- [x] Затем release Android, Windows x64, Linux amd64 DEB и OpenWrt (4 архитектуры)
- [x] Проверить версии/подпись/упаковку, сохранить артефакты и SHA-256; Mac собирает пользователь, push отдельно. Android 278 / PC 121 / OpenWrt 41 тест прошёл

### Исправление задержки предоплаты и проверка ЮMoney (2026-09-28)

- [x] Проверить квартальное сложение на сервере; дата 10.12 относится к monthly_5
- [x] Явно показать выбранный тариф и сумму сроков; подготовить quotes в профиле для всех клиентов
- [x] Android: заменить общий preview API платёжным каналом; удерживать bridge при старой active подписке
- [x] Unit/HTTP/browser проверки, PC build, Android debug 278 JVM tests
- [x] Stable: 162 checksum, health 44 мс, kick 0, wdtt/DNAT всех сот прежние
- [x] Целые дни в тексте/preview JSON, 57 backend checks, stable одного renewal-файла; точный остаток сохранён
- [x] Android: ограничить Wi-Fi public probe, локальный запуск оплаты, защита от cleanup стартового prefetch; debug 16:15 / 278 JVM OK
- [x] Установить debug и повторить реальное открытие ЮMoney на LTE и Wi-Fi; не отправлять деньги. Bootstrap MTU 1200 исправил ERR_TIMED_OUT; пользователь подтвердил обе сети и ручную приёмку

### Предоплата подписки 3/5 устройств (2026-09-28)

- [x] Backend: единый расчёт preview/activation, перенос стоимости остатка в дни, сохранение цены покупки
- [x] Сохранение ставки после повторных продлений; сериализация платежей и webhook replay
- [x] Android / PC (Windows/Linux/macOS) / iOS / OpenWrt: «Оплатить заранее», тарифы, предупреждение
- [x] Подтверждение по платежу вместо старой active подписки; TV focus
- [x] 53 backend tests + 41 OpenWrt + браузерный сценарий + Android JVM tests; PC/admin-ui build
- [x] Android debug собран; исходники iOS обновлены (Xcode build на Mac отдельно)
- [x] Stable backend: health 200/37 мс, kick 0/20 с, schema/preview/theme OK, 162 checksum совпали, wdtt/DNAT всех сот прежние
- [x] Пользовательская приёмка Android: пользователь проверил вручную, «всё вроде хорошо» (2026-09-28)

### Нулевые внешние измерения (2026-09-28)

- [x] Воспроизвести 0/0 на живом отчёте и добавить проверку total>0
- [x] Регрессии поздних/частичных ответов; сохранить результаты и ждать до 45 с
- [x] Корректный summary и UI для отсутствующих измерений; тесты VPN прошли
- [x] Живые результаты проверены чтением штатного отчёта и логов; дополнительная контрольная проба не запускалась
- [x] Stable deploy: Соты 1/2/4 RU TCP+ping 3/3, сота3 ping 2/3; total=0 нет, unknown=0, WDTT/DNAT сохранены, kick 0/20 с

### Пробы сот (2026-09-28)

- [x] Воспроизвести отсутствие ru/world у Соты 4 и ложные UDP timeout
- [x] Проверять все активные узлы; сначала базовые ping/TCP каждой соты
- [x] Запускать пробы после успешного auto-provision через общую очередь воркеров
- [x] Убрать зависимость UDP от executor и нейтрально отображать отсутствие ответа
- [x] Регрессии очереди, provision и UDP + существующие проверки; сборка админки
- [x] Stable deploy: Сота 4 agent_tcp РФ 3/3 + мир 2/2, нет ложных UDP timeout; очередь обработана лидером, WDTT/DNAT сохранены, kick 0/20 с

### QR-вход (2026-09-12)

Быстрый вход: ТВ показывает QR, телефон сканирует (и наоборот — уникальный код пользователя).

- [x] Backend `QrLoginService` + `/api/auth/qr/*` + unit-тесты
- [x] ThemeResponse / админка Оформление
- [x] Android: вкладка QR + сканер + меню (TV focus)
- [x] PC / OpenWrt / iOS
- [x] Деплой backend (`deploy_stable.py`); live `/api/auth/qr/start` 200
- [x] QR убран из меню; сканер у темы / лога; декодер YUV + approve API
- [x] Кнопка сканера — иконка; полный экран + полоска; без дыры SurfaceView
- [x] Debug: Android `SilentVPN-debug.apk`, PC `build-debug-14557`
- [x] Корень «скан ничего не делает»: самодельный QR PC/OpenWrt не декодировался; encoder → `qrcode`
- [x] QR только Smart TV; внешний сканер → deep link → кнопка подтверждения; VPN не рвём
- [x] ТВ не входил после confirm: poll одноразовый + пересоздание QR; retry poll + reuse сессии; деплой stable
- [x] Poll QR на ТВ через bootstrap overlay (приложение было вне туннеля)
- [x] Симуляция: nested skip-if-active overlay роняет poll; lease + poll после qrStart
- [x] ТВ poll на public API (как телефон) + не cancel своей poll-job до goToMain
- [x] publicHiveApi в обход getServerUrl; 403 poll не молчит; JWT даже без слота устройства
- [x] Приёмка: QR → confirm с телефона → ТВ входит
- [x] Хвосты QR на ПК/OpenWrt удалены (вкладки уже не было)
- [x] Хвосты QR на ПК/OpenWrt удалены (вкладки уже не было)

## Открытые задачи

### Тарифы 3/5 устройств (2026-09-20)

- [x] Backend: планы `*_5` (330/594/792), `max_devices` из активной подписки, `/payments/plans` с devices
- [x] Theme: подписи «3 устройства» / «5 устройств»
- [x] PC / Android / OpenWrt / iOS: выбор тира + тарифы; бейдж Сессии N/M
- [x] Оформление ClientPreview; тесты; `deploy_stable.py` (health 0.040с, wdtt active, kick 0)
- [ ] Приёмка: магазин 3/5, после оплаты `max_devices` и Сессии N/5; Ctrl+F5 админки
- [x] Пуш: `main` `b34e359`, `pc` `f40f5b6`, `android` `fdd26fe`, `ios` `564cbbe`, `openwrt` `6d18834`
- [x] Hotfix: `/plans` без *_5 по умолчанию; bootstrap оплаты игнорит БС (YuMoney на LTE)
- [x] Hotfix: bootstrap не сужает AllowedIPs при apiOverlay (YuMoney ERR_TIMED_OUT); revoke clamp expires_at; деплой + debug APK
- [x] Откат YuMoney-пути к релизу 1.0.167 (`WireGuardHelper` = `dd9dc03`, без BootstrapAppExcludeDecision); debug APK
- [x] Сверка с `dd9dc03`: оплата/WG/libclient как в релизе; отличия только UI тарифов 3/5; debug APK 13:19
- [x] Откат android: hard `33e70a3` + cherry-pick только магазин 3/5; VPN как релиз; debug APK
- [x] Подключение откатил к релизу (`2870627`); сняты все YuMoney AllowedIPs-эксперименты; debug APK
- [x] Patch оплаты 3/5: SemanticKey+PaymentTunnelPolicy+prepareBootstrapInternet; тесты ok; debug APK
- [x] Приёмка YuMoney на LTE: пользователь подтвердил «всё отлично»
- [x] Пуш android `0ddf0bc` (force-with-lease, вместо `f0401d0`)

### Админка: Оформление как текущий клиент (2026-09-20)

- [x] Превью меню: Подписка, Исключения, DNS, Выбор сервера, Бонусы, Сессии — без QR и без Telegram в release
- [x] Экраны DNS / Выбор сервера / Исключения (Сайты·Приложения, ЧС·БС); QR только Smart TV
- [x] Деплой admin-ui

### Админка: OpenWrt в Обновлениях (2026-09-20)

- [x] `PLATFORMS` + upload `.tar.gz`/`.tgz`; GitHub `silent-vpn-openwrt-{ver}.tar.gz` + Pages `silent-vpn-openwrt.tgz`
- [x] Карточка OpenWrt как Mac (загрузка + GitHub, без VPS-сборки и nightly)
- [x] Деплой `deploy_stable.py` + Ctrl+F5 админки

### Доступность: pending в деталях (2026-09-20)

- [x] check-host `pending` больше не 1/3 и не `pending×N` в «Ошибки»; деплой `deploy_stable.py`

### Регресс ACK-lane: предзагрузка и видео на ПК (2026-09-19)

- [x] Корень: prio-ветка (`n≤128`) не двигает `rrIndex` → все ACK загрузки на одном воркере/релее; chunk 32 на границе anti-replay WG
- [x] Откат диспетчера к `chunkSize=8`, снят `dispatcher_policy.go` и `PrioCh`; Allocate-gate / quota-wait / DTLS 30 с оставлены
- [x] `go vet` + тесты PC и Android ok; debug ПК `build-debug-555393`, APK `android/SilentVPN-debug.apk`
- [x] Push `pc` `7893df2`, `android` `33e70a3`
- [x] Релизы 1.0.167 на откате: NSIS `build-release-v141-639012`, `.deb`, APK, OpenWrt tarball (20.09 утро)
- [x] Залить 1.0.167 на GitHub Releases + `releases.json` на Pages (exe/apk/deb/openwrt, размеры = откат ACK-lane)
- [ ] Приёмка: предзагрузка и видео на Сервере 1, 4PDA-приложение
- [ ] Потолок 53/55 воркеров: нужен лог рампа с ПК (есть ли «Квота relay, ждём без refresh» / 486)
- [ ] Улей: жёсткий ребут хостера 18:47 UTC 19.09 + `silent-vps-cleanup.service` failed — разобрать отдельно

### Дашборд: краткие провалы метрик сот (2026-09-28)

- [x] Диагностика: несовпадение build_id и рестарты агентов каждые 45–50 с
- [x] Upgrade/provision копируют весь SHIPPED; регрессионный тест и preflight stable
- [x] `deploy_stable.py`; все 4 версии совпали, 96 опросов без провалов, wdtt PID прежние, kick 0

### Дашборд: онлайн всех нод (2026-09-20)

- [x] Корень: `wg_live=0` затирал людей на соте; standby глотал `/internal/online`
- [x] `node_online_shown` = max(БД, WG); прокси online на Улей + `X-Hive-Cell-Id`
- [x] Тесты hive_slots + cell_standby_online; `deploy_stable.py` health 0.041с, wdtt active, kick 0
- [x] VK-хеши по пользователям: зелёные были только `is_connected` (9), шапка — WG (67). Теперь тот же live-ключ (+ GETCONF extra)
- [ ] Приёмка: шапка = сумма карточек; в «Серверные VK-хеши» онлайн ≈ шапка, не 9 vs 67
- [ ] Ctrl+F5 админки после деплоя

### DNS в туннеле и 53 воркера на Сервере 1 (2026-09-19)

Разбор лога: `[Основной] Потоков=63`, `[READY] (x53)`, `DNS: Как на сервере`.

- [x] Клиентский DNS приложений — в WG на **всех** слотах (`DNS=` + `AllowedIPs 0.0.0.0/0`), не только 2/3
- [x] Воркеры libclient на основном VPN **вне** туннеля (ЧС приложения) — иначе TURN/DTLS замирает на 2–3, не на 53
- [x] «Свой DNS» — тот же WG DNS для **всех приложений в VPN**, не только браузера; воркеры его не используют
- [x] Улей: фильтр выкл → DNAT `:53` на `1.1.1.1` (как Сервер 4), без рестарта wdtt
- [x] На Улье 149 WG peer: live 12, never-hs 121 — хвосты GETCONF; «капча группы 2+» в логе — сторож через 75с, не VK
- [x] GC: known только `wg_public_key` (live-ключ больше не защищает never-hs)
- [x] Снял extras пачкой: drop 125, after peers 24 live3m 11 never 0, wdtt active
- [x] 53/63 на Сервере 1: хвосты WG не причина; DTLS/UDP тюнинг на Улье
- [x] UDP/TURN до Улья `:56000`: путь живой (20/20 с соты 1, VK TURN WRAP OK, фаервол ACCEPT). Не дыра после смены IP. check-host UDP timeout на всех трёх — wdtt не echo
- [x] outdated token STREAM 700: refresh с attempt 2 работает (лог 21:20); лог 21:37 — Success attempt 1
- [ ] Воркеры 55/53 на Улье: Сервер 1 пока оставляем (возможен IP). Allocate gate / quota wait / ACK-lane в 1.0.167. Приёмка 63 — позже
- [x] YouTube серые превью: убран 20 мс dwell mid-flow; ACK-lane+chunk остались
- [x] OTA: github.io `releases.json`, hive check skip. Релиз 1.0.167 на Pages + GitHub Releases (откат ACK-lane)

### Удаление сессии с клиента при VPN (2026-09-19)

- [x] Корень: overlay no-op → HTTP к `10.66.66.1:8000` с LTE IP, таймаут 12 с
- [x] `withUserBackendApi` → TunnelApiProxy; `UserApiRoute.TUNNEL_PROXY`
- [x] Unit `ApiRoutePolicyTest` / `TunnelHttpPolicyTest` (DELETE без body)
- [x] 502 Upstream error: HttpURLConnection DELETE; OkHttp bindSocket; LTE без public failover
- [x] Откат short-bootstrap (stopVpn): промокод и удаление сессии → includeAppOverlay, VPN не рвём
- [x] 10.66.66.1:8000 с `10.66.13.3` таймаут (шлюз соты) → failover на :9100 внутри WG
- [x] Overlay+nip.io ломал VPN — полный откат на origin, схема 1.0.165 (`runPromoShortBootstrap`)
- [x] Удаление сессии при VPN — тот же short bootstrap, что промокод до смены IP
- [x] Приёмка: VPN выкл — промокод и удаление через временный bootstrap; схему оставить; push `origin/android`

### Egress Улей / сота 3 как соты 1–2 (2026-09-19)

- [x] Срез: Улей без TCPMSS/TTL/IPv6-drop/`mtu_probing`; сота 2 с clamp; сота 1 с probing+TTL
- [x] `hive_egress_tune.py` + apply Улей и сота 3; wdtt active; unit `test_hive_egress_tune_unit.py`
- [x] Приёмка Сервер 1: сайты летают; 4PDA — корень DNS Яндекса, Cloudflare DNS лечит (оставили как есть)
- [ ] Сервер 4: страницы тугие из‑за US HOSTKEY (RTT), не MSS; TPROXY выключен

### Админка: сессии устройств (2026-09-19)

- [x] Правая панель в «Пользователи» как история в подписках
- [x] `GET/DELETE /api/admin/users/{id}/devices` (+ delete all)
- [x] Unit `test_admin_user_devices_unit.py` (без секретов в JSON)
- [x] Приёмка + push `origin/main`

### Пробный период: оплата сразу (2026-09-18)

Пользователи хотели оплатить, не дожидаясь 3 дней. Trial и «3 дня» не связывали.

- [x] `can_buy_paid_plan` / `end_trial_subscription` + `POST /api/admin/users/{id}/end-trial`
- [x] Админка: чип «Пробный» только снимает trial, без kick VPN
- [x] Android / PC / iOS / OpenWrt: магазин на пробном — **откатил 19.09** (force-push)
- [x] Тесты `test_subscription_filters_unit.py`, `ShopOfferPolicyTest`, OpenWrt dock
- [x] Деплой backend (`deploy_stable.py`): health 0.044с, wdtt active, kick 0
- [x] Push `main` `416d4ce`, `pc` `b675b04`, `android` `630481c`, `ios` `fa5e59a`, `openwrt` `53f029b`

### Android ложный «Перезапуск транспорта» на лежащем телефоне (2026-09-15)

vivo V2520A: сеть не терялась, звонка не было, в логе `[СЕТЬ] Перезапуск транспорта`.

- [x] Корень: OEM INTERNET-blip ≥400 мс → `lastBlackoutAtMs` → `cell_gap_restored` / `validated`+blackout 60 с → kill libclient
- [x] Gap того же wifi/cell только ≥3.5 с; короткий blip DISCARD (метку сбрасываем)
- [x] `wasRealPauseOrBlackout`: пауза 8 с или дыра ≥3.5 с; Wi‑Fi↔LTE / RAT / handover / звонок без этой метки
- [x] Короткое VALIDATED-мигание больше не планирует recover
- [x] `NetworkRecoveryPolicyTest`; Debug `android/SilentVPN-debug.apk`
- [x] Приёмка 18:47/18:50: порог 3.5 с не хватил — gap/handover всё равно forceFull kill при живых 54–63 воркерах
- [x] `shouldKeepHealthyTransport`: живой libclient не убиваем на gap/handover/validated; Wi‑Fi↔LTE / RAT / звонок / пауза 8 с — как были
- [x] В логе restart теперь с причиной в скобках
- [x] Приёмка idle 2026-09-15: на лежащем vivo рестартов нет
- [ ] Приёмка переподключения: Wi‑Fi↔LTE / вышка / звонок — VPN сам встаёт (ещё не гоняли)

### Админка доступности: ложный «блокировок нет» (2026-09-15)

Скрин Улья: локально API/TLS ok, из РФ TCP+TLS 0/2 timeout, ping 1/2, DNS 2/2,
онлайн 54 — баннер «Блокировок не обнаружено».

- [x] Это не внутренний сбой: сервис жив (локальные пробы + онлайн). TCP к Улью из РФ/этой сети таймаут (22/80/443/8443) — вмешательство/whitelist на TCP, UDP WG жив
- [x] Классификатор: port_block если TCP all_failed, а ping не all_failed (дырка all_ok vs blackhole)
- [x] Тест `test_hive_https_timeout_from_rf_is_port_block_even_if_ping_partial`; `python scripts/test_availability_unit.py` 41 ok
- [x] Деплой `ai/availability_classifier.py` на Улей (`deploy_stable.py` 16.09 и 17.09)

### Улей: публичный TCP из РФ (2026-09-15)

Не падение сервиса. **2026-09-16:** из этой сети Улей `:80` открыт, `:443`/`:22`/`:8443`
timeout (это уже **порт**, не полный blackhole). API жив в туннеле и через соты `:9100`.
15.09 весь TCP к `89.125.188.100` таймаутил. Не SNI. Похоже на ТСПУ/whitelist по порту
(443 и 22), UDP WG и HTTP :80 с IP сот живы.

- [x] Не чинить 443 DNAT на том же IP (пакеты не доходят; клиенты без обновления бьют в :443)
- [x] Деплой 16.09 `deploy_stable.py`: классификатор (DNAT не советуем + `tls_entrance_broken`), письма с резервными ссылками, dry-run `port_plan`. wdtt active, kick 0, DNAT туннеля ok
- [x] SSH-деплой не падает на плавающем блоке: повторы + `SSHException` в `connect()`, env `DEPLOY_SSH_ATTEMPTS`
- [x] Регресс писем 16.09: `HIVE_API_ALT_PORTS` пустой, в standby сначала соты `:9100`, не мёртвые `:2083`
- [x] Сота→Улей: к `:8000` добавлен `:80` (тот же nginx allow); nip.io по-прежнему последний
- [x] Dry-run кольца серверов: `ai/cell_relay_policy.py` — если Сервер 4 режут, предлагает вход через живую соту. Туннеля нет, `executed=False`, wdtt не трогаем
- [ ] Хоп сота→Улей внутри WG: WG-связи сота↔Улей сейчас нет (у соты `10.66.66.1` — свой шлюз). Нужен отдельный wg-интерфейс (не `wdtt0`, чтобы не задеть peer GC) либо промежуточно HTTPS-first с проверкой сертификата
- [ ] Датаплейн кольца (`silent-mesh0` сота↔сота, fail-open watchdog как у AI-exit): без него «войти через Соту 1» даст выход Соты 1, не ИИ-выход. Клиентов не меняем, пока туннеля нет
- [x] Подтверждение email/сброс пароля мимо 443: резервные ссылки на соты в письме (`email_links.py`); один хост — одна ссылка, IP Улья в резерв не берём
- [x] SMTP с Улья: IPv4+timeout 12с; если mail.ru unreachable — сота `/v1/smtp-send`. Деплой 17.09, wdtt active, kick 0
- [x] Аудит Улья: вторжения нет (ufw inactive, DROP на 443/22 нет, лишних ключей нет, входы только админ-ПК и Сота 1, контейнеры штатные). Блок внешний и плавающий
- [x] Вход Улья цел: TLS 1.3, сертификат до 28.11.2026, `api8000:200`. `000` на `https://127.0.0.1` — это `return 444` для чужого Host, не поломка
- [x] Классификатор: локально TCP 443 open + TLS/HTTPS мертвы → `service_down`, а не «блокировок нет» (`tls_entrance_broken`, 44 теста)
- [x] Dry-run запасного порта: `availability_port_plan.py`, `port_plan` в отчёте, карточка в админке. Портов не открывает
- [x] Исполнитель автосмены: nginx `listen 2083`; публикация в тему. 1/2 check-host тоже открывает `:2083`, 443 не закрываем. Кандидатов зовём при любой резке с РФ
- [x] Register «API endpoint not found» при живом overlay: Host nip.io на 10.66.66.1 → 301 POST→GET. Nginx :80 `/api/` без 301; Android не rewrite Host туннеля
- [x] Temp VPN не давал интернет почтовым клиентам: includeApplications на OEM no-op. Bootstrap = полный туннель minus VK
- [x] Gmail на temp VPN: IPv6 leak мимо WG. Bootstrap `setBlocking` underlay
- [x] Письма не доходят даже на Wi‑Fi: From не домен SMTP + Улей первым. Соты first, envelope = SMTP_USER
- [ ] Маскировать секреты в любом новом shell-аудите (`ps aux` светил `-password` wdtt)
- [x] 443 никогда не закрывать автоматом; закрывать только ранее открытый alt-порт после grace (`hive_api_port_exec`, KEEP_FOREVER)
- [ ] `verification_token` без TTL (в письме «24 часа») — добавить срок
- [ ] Клиент→сота `:9100` и сота→Улей `:8000` plaintext: пароли/JWT открытым текстом, пока вход идёт через соты. Нужен TLS или хоп по WG
- [x] Сота `:9100` и standby `10.66.66.1` сами ходят на Улей `IP:8000` (не nip.io) и отдают вход/оплату/подписку/sync; снимок только если Улей с соты реально мёртв. Сота 1/2 залиты, Сота 3 агент обновлён 2026-09-15 (`silent-cell-agent`, `:9100` снаружи закрыт, sync-state 401)
- [x] Сервер 4 `10.66.66.1:8000 FAIL`: Сота 3 слала на Улей `:8000` (RST) и не была в nginx allow (403). DNAT → Улей `:80`, nginx `allow 192.177.26.38`, CELL_API `:8000→:80`. wdtt/api не рестартили. Приёмка: reconnect ПК
- [ ] Публичный API/админка — через туннель `10.66.66.1` и `standby` сот `:9100`, не nip.io
- [x] ПК: на соте IP Улья не в Bypass; админка `10.66.66.1:8000`; SSH fallback `10.66.66.1:22`
- [ ] Прятать Улей: 443/22 с интернета только с IP сот + WG; nip.io не светить как основной вход
- [x] Новый IP Улья `89.125.188.100` / `89-125-188-100.nip.io` (кабинет OneDash 2026-09-18): код + LE + соты socat/`HIVE_QUEEN_IP` + `deploy_stable.py` (wdtt не рестартили). Пересборка PC/Android/OpenWrt 1.0.166. iOS не пересобирали. **ЮMoney notify:** тест кабинета 19.09 17:08 — sign ok, 200.
- [x] Аудит HEAD 2026-09-18: классификатор pending/probe_error, не port_block при живом HTTPS, без REDIRECT 8443→wdtt
- [x] Запасной порт: публиковать только `open`, 8443 forbidden, stale из reach; автосмен по-прежнему выкл
- [x] Deny unique tmp; read_failed не снимает SILENT_DENY; unpaid cursor + offline только своих ключей
- [x] nginx `:80` allow `172.16.0.0/12` (403 /health с 172.18.0.1)
- [x] Dry-run смена IP: `ai/ip_rotate_policy.py`, чеклист читателей, без покупки
- [x] OneDash адаптер: GET inventory + карта IP→vps, change-ip в API 2.0 нет, POST заблокирован
- [x] ПК nip.io timeout: с соты Улей не в bypass; слот Улья → 10.66.66.1; debug `pc/build-debug-167309`
- [ ] Android: после OTA 165→166 Сервер 1 не крутит кеш старого IP Улья (нужен новый APK 1.0.166; приёмка)

### PC Wi‑Fi + ISP whitelist (2026-09-15)

ПК на Wi‑Fi: конфиг/тема/хеши/подписка раньше шли напрямую на Улей. Overlay-правки
и 8с escalate на капчу откатили к `origin/pc` (git restore) по просьбе 2026-09-15.

- [x] Откат всех локальных PC-правок к HEAD (`be89f2c`): connectPolicy/overlay удалены
- [x] На соте IP Улья больше не в Bypass — админка/SSH через туннель (как Android)
- [x] Кнопка админки при VPN: `http://10.66.66.1:8000/dashboard`, без fallback на nip.io
- [x] Debug: `pc/build-debug-hiveadmin/win-unpacked/SilentVPN-Admin.bat`
- [x] На слоте Улья syncconf оставлял мёртвый `10.66.66.1` — после syncconf проба :8000, иначе полная переустановка WG
- [x] Все клиенты: Улей HTTPS → соты `:9100` (PC/Android/iOS/OpenWrt). Debug APK `android/SilentVPN-debug.apk`
- [x] OpenWrt пакет пересобран (`dist/silent-vpn-openwrt-1.0.165.tar.gz` + wdtt). На лендинге локально `e2ac6c4`; Pages 403 — пуш `silentvpn3.github.io` нужен аккаунт `silentvpn3`, не `footballpredictions`
- [x] Debug: `pc/build-debug-69815/win-unpacked/SilentVPN-Admin.bat`
- [ ] Приёмка: VPN вкл → в логе `tunnel API 10.66.66.1:8000 ok`, админка открывается

### Android БС исключений (2026-09-14)

ЧС работал, БС на теле не применялся (no-op full tunnel). На сервере 2 маскировалось.

- [x] Корень: `resolveAppTunnelPolicy` всегда `whitelist=false`
- [x] `AppTunnelRouting` + тесты; БС = includeApplications без Silent/VK
- [x] Приёмка на сервере 2 маскирует баг (IP соты не в блоклисте Ozon/WB)
- [x] БС через exclude complement (как рабочий ЧС); пустой БС ≠ full tunnel
- [x] Приёмка: БС без галочек на Ozon/WB — магазины не видят VPN

### Game exit — Сота 2 / Dota UDP (2026-09-12)

Мodem + белый список: исключения Steam нельзя. Нужен UDP путь через VPN к SDR Valve.
Сота 2 (`78.17.74.27`). Runbook: `backend/GAME_EXIT_NODE.md`.

- [x] Ф0 audit + probe Steam SDR (host + netns) — **UDP_PATH_OK** с соты (мелкие пакеты)
- [x] Ф1 udp-tune (sysctl UDP + TCPMSS, без обхода SILENT_DENY); wdtt active
- [x] Корень: клиентский MTU 1200 < Steam ~1300 → PC/Android MTU **1420**, сота2 wdtt0 **1420**
- [ ] Приёмка: пользователь — `netsh mtu=1420` на wg-turn **или** новый PC-билд; Dota ping/matchmaking
- [ ] Флаг `game_exit` + слот «для игр» — только если понадобится изоляция после приёмки

### OpenWrt-клиент (2026-09-12)

Папка `openwrt/` — свой агент + веб, совместим с тем же backend. Не LuCI/Amnezia-форк.

- [x] Каркас: агент `silent-vpn-ctl`, CGI, dnsmasq `{lan-ip}.silent.vpn`, web UI из ThemeResponse
- [x] INSTALL.md + локальный preview `python scripts/preview.py`
- [x] Веб на весь экран, не phone-frame; контролы как у клиентов (2026-09-12)
- [x] Поддержка = иконки Telegram; сессии OpenWrt+имя; 4 сервера; змейка на бегунке; DNS; RU-direct в исключениях
- [x] Тумблер = Android/PC (тень, змейка по краю); preview — живой вход на Улей
- [x] Док как у клиентов: Бессрочно / Оформить подписку; без 9999 дн. у админа
- [x] Оплата YuMoney без Referer (как Android), не с 127.0.0.1
- [x] Универсальный `silent-vpn-openwrt-*.tar.gz` (все arch) + `install.sh deps` / `install`
- [x] Кнопка «Роутер» на лендинге → страница `#openwrt` (без скачивания с главной)
- [x] Одна команда wget|sh; пакет сам ставит wdtt под arch (aarch64/arm/mipsel/x86_64)
- [x] opkg (23/24) или apk (25+): скрипт сам выбирает по версии OpenWrt
- [x] Удаление одной командой (`openwrt-uninstall.sh`): файлы, UCI WG/firewall/DNS, пакеты
- [x] Вход в веб Silent только по LAN-кабелю, не с Wi‑Fi (LuCI по IP с Wi‑Fi ок)
- [ ] Приёмка на живом OpenWrt 23.05+ (команда, логин, тумблер, LAN в туннеле)
- [ ] Слот в админке «Обновления» / OTA ipk, когда появится пакет

### Admin-debug quality monitor (Android, 2026-09-11) — СНЯТО

- [x] **Полностью вырезано 2026-09-11:** клиент + API + админка Hive Quality. Не возвращать без рабочего канала на LTE без reapply WG.

### AI exit node — Сота 3 / Сервер 4 (2026-09-06)

Runbook: `backend/AI_EXIT_NODE.md`. Выход = WDTT + гигиена ноды. WARP/TPROXY сейчас **выкл** (Gemini на HOSTKEY).

- [x] Ф0–Ф5 AI-exit (гигиена, DNS, fail-open proxy, egress-check)
- [x] **Приёмка 2026-09-08:** веб и приложения нейросетей ок на прямом IP соты; ChatGPT app на HOSTKEY не входил. WARP включали — Google/Gemini отвалился, снова **выкл**.
- [x] **Открыть всем + 1.0.165:** `admin_only` снят; слот только у клиентов 1.0.165+ (`X-App-Version`). 1.0.164 слот не видит. WDTT-spill на `ai_exit` не льёт.
- [x] **Harden сот 1–2** (2026-09-09): ufw active, TTL 64, IPv6 forward DROP, `silent-cell-hardening` enabled; wdtt/9100/tunnel не трогали
- [x] **Профиль для ИИ из админки** (2026-09-09): тумблер ставит/снимает hygiene+dns на соте; без WARP; rename «ИИ-выход»→«Профиль для ИИ»
- [x] **PTR / geofeed / План Б ASN — отложено** (2026-09-09): пока Сервер 4 работает — смысла нет; вернуться при капчах/бане IP или смене провайдера
- [x] **Админ-выдача года не плюсует хвост** (2026-09-09): grant от now; починен `my@silent27-99.ru` 2028-03→2027-09
- [ ] При необходимости резидентный SOCKS (`proxy --chain socks5://…`), не WARP — только если снова капчи

### Debug↔release VPN залипание (Android, 2026-09-11)

- [x] Диагноз: два UID; после свайпа sibling оставляет зомби-TUN; `findOurVpnNetwork` чужой не видит
- [x] Sibling teardown broadcast + ожидание перед WG UP + `force` clean slate; tunnel name `silent`/`silent_dbg`
- [ ] Проверить на телефоне: VPN в release → свайп → debug connect (и наоборот) без airplane/ребута

### Ложные / пропущенные переподключения VPN (Android, 2026-09-11)

- [x] Диагноз ложных: чужая сота при Wi‑Fi → blackout/VALIDATED → лишний restart
- [x] Фикс чужой сети: `isOurUnderlyingNetwork` (2026-09-06)
- [x] **Регресс «не переподключает»:** handover blackout, очередь recover на звонке, full restart после pause — 2026-09-11
- [ ] Проверить на телефоне: Wi‑Fi↔LTE, airplane, звонок, потеря сети — без рубильника; на месте без самопроизвольных рестартов

### Linux-клиент (2026-08-29)

- [ ] **Linux-клиент = тот же PC Electron, UI и включение VPN 1:1:** не отдельная ветка/репозиторий. Тот же React renderer, тот же тумблер (bootstrap 2 мин → login → полный `0.0.0.0/1+128/1` + bypass), `device_type=pc`. Платформенный слой: WireGuard (wireguard-go / kernel + pkexec), `wdtt-client` linux/amd64, исключения приложений через `/proc`, OTA AppImage (`platform=linux`). Сборка: `pc/build-linux.ps1` / `pc/build-linux.sh`
  - [x] Код: `wireguardLinux.js` + helper, wdtt path, exclusions `.desktop`/`/proc`, OTA `linux`, тесты
  - [x] Кросс-компиляция `wdtt-client` linux/amd64 с Windows (~12 МБ)
  - [x] Собрать установщик `.deb` (`Silent VPN Setup 1.0.163.deb`) — двойной клик открывает установку
  - [x] Деплой backend (`platform=linux` в updates) — 2026-08-29 `deploy_stable.py`: health 200 (~42 мс), `wdtt` active, kick 0; админка «PC (Linux)»
  - [x] **Права как Windows:** пароль один раз при установке `.deb`, тумблер без pkexec (systemd helper + socket). Новый `Silent VPN Setup 1.0.163.deb` — переустановить
  - [x] **Админка Обновления = PC/Android:** скачать / собрать / стоп / авто 00:00 / удалить + `build_linux.sh` + Docker-образы на Улье — 2026-09-10
  - [x] **Лендинг кнопка Linux** + publish GitHub `.deb` → `releases.json`/`index.html` — 2026-09-10

### Mac-клиент (2026-09-10)

- [ ] **Mac = тот же PC Electron:** `wireguardDarwin.js` + LaunchDaemon helper, `wdtt`/`wireguard-go` darwin-arm64, OTA `platform=mac`, админка «PC (Mac)»
  - [x] Код helper + Darwin WG + wiring main/ota/preload + тесты
  - [x] Кросс-сборка бинарников с Windows (`build-mac.ps1`) → `resources/mac/`
  - [x] Backend upload/check `platform=mac` + админка (загрузка .dmg; сборка на Улье — нет)
  - [ ] **Собрать `.dmg` на MacBook:** `./build-mac.sh` → `build-mac/Silent VPN Setup 1.0.165.dmg`
  - [ ] Приёмка VPN на Mac (helper password once, тумблер, bootstrap)
  - [ ] Лендинг кнопка Mac (по желанию)

### Чистка olcrtc и установка на ТВ (2026-08-23)

- [x] **Вычистить olcrtc до конца (код + деплой Улья):** 2026-08-23 `deploy_stable.py` — агенты no-op, settings всегда off, cell-agent apply/create 410. На проде: `wdtt` active, DNAT на API, health 200, `olcrtc2_disabled True`, живых `olcrtc*` нет. Соты подтянут cell-agent автоапгрейдом. Релиз APK/EXE без .so — отдельно
- [ ] **OTA на Android TV / Smart TV:** причина — жирный fat-APK 90 МБ (`1.0.161` на проде) с мёртвыми `libolcrtc.so`/`libolcrtc2.so` (~190 МБ uncompressed на 4 ABI). ТВ не ставит (часто `INSUFFICIENT_STORAGE` / «приложение не установлено»). Gradle уже исключает эти .so; нужен новый OTA-релиз. Manifest/leanback не ломали

### olcrtc стабильность (план 2026-08-14)

Полный план: `.cursor/PLAN_OLCRTC_STABILITY.md`.

- [x] **Фаза A — PC меню обхода как 1.0.160:** диалог «Применить?» + `VK → olcrtc` (не футер Было/Будет)
- [x] **Фаза B — 1 комната на клиента:** Telemost `max_clients=1`; assign empty; heal БД на проде; скрипты max=3/25 исправлены
- [x] **Фаза C — доставка конфигов:** LTE/БС без public fallback при живом tunnel; dual-cache изоляция; PC timeout olcrtc 90с
- [x] **Фаза D — устойчивость (код):** HB через SOCKS/tunnel; failure после liveness streak; lastFailed не стартуем
- [x] **Сота 1 CPU:** warm TM cap=2 (агент больше не ставит 20); prune 73→11 — 2026-08-14
- [x] **Сота 1 idle 20–50% без клиентов:** idle `olcrtc2-srv` warm; TM warm=0, units сняты, CPU≈0% — 2026-08-14
- [x] **PC SOCKS miss после warm=0:** warm TM=1 + retry новой комнаты; debug `build-debug-144543` — 2026-08-14
- [x] **TM Wi‑Fi старт >30с:** без carrier-probe на assign; ICE wait 8с; PC `496328` + APK — 2026-08-14
- [x] **WDTT-баланс мимо olcrtc:** Сота 1/2 не spill; только 3+ / Улей — 2026-08-14
- [x] **Android: не рвать комнату** на liveness/stream_dead — native reconnect; рестарт только process_exit
- [x] **Android: TM freeze / нет конфига WB / вылет VK** — без gstatic-проб на живом туннеле; Apply fetch пустых слотов; hardReset при уходе на VK
- [x] **Сота 1 сеть/CPU:** egress ~320 Мбит ок; снят `CPUQuota=50%` с живых olcrtc2 (без рестарта сессий)
- [x] **Сота 2 сеть/CPU:** то же (WB); egress ~540 Мбит, steal 0%; квота снята без рестарта
- [x] **Android TM reconnect + PC тумблер/лог/обход:** epoch не убивает новый SOCKS; PC статус как Android; лог чистится на connect; bypass commit/localStorage
- [x] **Первая загрузка медленная:** DNS шёл через VP8-несущую; вернули fake-ip (PC sing-box) / `mapdns` 198.19.0.0/16 (Android) — резолв на соте. APK + PC `build-debug-182837` — 2026-08-14
- [x] **olcrtc2 cache safety + меню lock:** без раннего wipe слота на room-failure (Android/PC), debounce failure, soft→hard failure на backend; переключение обхода отключено при VPN ON — 2026-08-14
- [x] **Улей: журнал инцидентов в админке:** отдельный поток только ошибок/падений (`/api/admin/hive/incidents`) с подсказками по DPI/портам/DNS/ресурсам — 2026-08-14
- [x] **Улей: security-инциденты:** фиксация подозрительных вмешательств (admin host guard, brute-force admin/MFA, burst register rate-limit) в том же `/api/admin/hive/incidents` — 2026-08-14
- [x] **Улей: авто-сброс stale online:** если `is_connected=true`, но heartbeat/`last_connected` просрочен — устройство автоматически уходит в offline (фон. maintenance loop) — 2026-08-14
- [x] **olcrtc2 burst warm:** при серии `Нет свободных комнат` временно +1 warm по провайдеру (окно 25с, hold 180с, авто-откат) — 2026-08-15
- [x] **Smart Apply Refresh (Android+PC):** после смены TM/WB — background refresh слота (TTL/dirty-aware, с тайм-бюджетом, без блокировки Apply) — 2026-08-15
- [x] **UX исключений + DNS + splash:** `Выделить все` в исключениях (Android/PC), без авто-выбора в БС; DNS упрощён до `Яндекс (как на сервере)` + `Свой DNS`; тёмный splash на Android — 2026-08-15
- [x] **DNS-регрессия 1.0.161 (YouTube на VK-обходе):** откат к семантике 1.0.160 — дефолт `Как на сервере` (`wg_dns`, в т.ч. `10.66.66.1`), в меню только сервер + `Свой DNS`, миграция сохранённых публичных пресетов; PC-модалка DNS в стиле «Смены обхода» — 2026-08-15
- [x] **Admin UI style unify + PC DNS dark modal:** единый строгий dark-стиль админки (чёрная база, синий/red/green акцент) + fix белого DNS-окна в тёмной теме PC — 2026-08-15
- [x] **VK-обход: убран лишний olcrtc-prefetch:** `prefetchOlcrtcSlotsOnVkTunnel()` снят с post-sync (как в 1.0.160) — `/olcrtc2-config` делал assign комнат на каждом VK-connect; debug APK пересобран — 2026-08-15
- [x] **Hive: видимый online для olcrtc2 по сотам:** backend считает свежие sticky по `cell_id` + админка показывает `wdtt/olcrtc/итого`, чтобы сессии не «терялись» в UI — 2026-08-15
- [x] **Android WB: анти-зависание через несколько минут:** восстановлен recovery при `peer_closed/media_timeout/stream_dead` (WB форсирует liveness-check + restart, TM поведение сохранено) — 2026-08-15
- [x] **olcrtc2: убрать фантомный online в sessions:** assign config больше не «touch» sticky; `pool_stats` считает только свежие sticky (окно heartbeat), чтобы без звонка не висели `sessions` — 2026-08-15
- [x] **Android WB: decrypt/auth desync recovery:** при повторе `decrypt failed / message authentication failed` запускается WB-recover с reassign комнаты (вместо тихой смерти канала) — 2026-08-15
- [x] **Android WB: убрать 1–2 мин подвис после peer closed:** для WB peer должен вернуться в `connected` в grace-окне, иначе сразу recover (не считаем «SOCKS жив» достаточным) — 2026-08-15
- [x] **Android WB: DNS path fix для olcrtc2:** вместо `activeNetwork DNS / 1.1.1.1` используем provider-aware DNS из меню обхода (WB→fallback first), чтобы убрать подвисы от внешнего резолва — 2026-08-15
- [x] **Android WB: fast recover по heartbeat socks-fail:** для WB после 2 подряд `HB socks CONNECT fail` сразу suspect/recover, чтобы не оставлять «зависший» канал — 2026-08-15
- [x] **Android WB: ultra-fast recover по heartbeat socks-fail:** для WB порог снижён до 1 fail (немедленный recover), чтобы убрать даже краткие зависания — 2026-08-15
- [x] **Выбор сервера 1/2/3 = Улей / Сота 1 / Сота 2:** маппинг по номеру соты (не индекс списка), persist `server1/2/3`, login не затирает слот; Android LTE как 1.0.160 (public API first) — 2026-08-15
- [x] **PC: смена сервера сразу после выкл + Android LTE без overlay-рестарта WG:** лок меню по UI, не по умирающему туннелю; LTE API через proxy — 2026-08-15
- [x] **Hive: онлайн на Сервере 2/3:** балансир больше не сбрасывает `cell_id` с Соты 1/2; счётчик по `preferred_server`; сводка считает все соты — 2026-08-16
- [ ] **Проверить VK-обход на debug APK 12:09:** пропали ли серые экраны / задержка 10–20 с; если нет — снять экран «Лог» и смотреть `AppExclusions` (`БС пуст → ЧС`)
- [ ] **Соты: кеширующий DNS** (unbound/dnsmasq) + `OLCRTC2_DNS=127.0.0.1:53` — весь резолв теперь делает `olcrtc2-srv`
- [ ] **Фаза D — endurance:** 40 мин WB+TM Wi‑Fi/LTE на PC+Android debug (ручной прогон; APK + PC `build-debug-182837`)

### Инфраструктура и репозиторий

- [x] **AI-агент доступности: детекция блокировок DPI/ТСПУ + решение в отчёте** — 2026-08-23: `ai/availability_{model,knowledge,classifier,probes,agent,cli}.py`, `app/services/availability_store.py`, admin API `/api/admin/hive/availability*`, клиентский репорт `POST /api/vpn/reachability-report`, cell-agent `POST /v1/net-probe`, раздел «Доступность и блокировки» в Улье, 28 unit-тестов (`scripts/test_availability_unit.py`), runbook `backend/AVAILABILITY.md`. Пробы только читают (не ломают VPN)
- [x] **Агент доступности на проде** — 2026-08-23: `deploy_stable.py`; таблицы созданы, 7 фоновых агентов, wdtt active, DNAT на IP Улья, 92 устройства онлайн. Живой прогон: Улей + Сота 1 + Сота 2 доступны из РФ (3 ноды), 30 с, 8 внешних проверок. Тихий режим: подтверждение 2 циклами, окно тишины 12 ч, ≤2 записи за цикл, ручной запуск в журнал не пишет; пропуск цикла при CPU ≥85 % / RAM ≥92 %
- [x] **Клиентский репорт доступности в PC / Android** — 2026-08-23: `pc/src/renderer/reachabilityReporter.ts`, `android/.../vpn/ReachabilityReporter.kt`, `ApiService.ReachabilityReportRequest`, `Repository.reportReachability` + тип сети и оператор. Хуки: ошибка VPN при подключении → `handshake`, смерть живого туннеля → `tunnel_dead` с возрастом. Очередь с debounce 5 мин, backoff и выгрузкой после поднятия туннеля / Wi‑Fi tick; не привязана к `isTunnelApiActive()`. Новое поле `age_sec`: сервер метит отказ временем самого сбоя, отложенная пачка не создаёт ложную блокировку; старше 48 ч — `stale`. 33 unit-теста
- [ ] Подключить клиентский репорт в iOS — по тому же контракту (`stage`, `transport`, `network_type`, `carrier`, `age_sec`)
- [x] **Улей: автоподключение соты по IP + SSH root (wdtt, DNAT tunnel, cell-agent)** — 2026-06-20
- [x] **Соты: локальный WG GC + snapshot слота (не копия всей БД)** — 2026-08-18: cell-agent GC как на Улье; `/v1/status` счётчики; manifest = `cell_id` ∪ `preferred_server`; Сота 1/2 апгрейд, extras сняты
- [x] **Слой 3 failover + онлайн Улья/дашборд** — 2026-08-18: клиент бьёт в cell-agent :9100 если Улей недоступен; в Улье онлайн соты по WG live; в дашборде устройство · Улей/Сота N
- [x] Улей: фоновый провижининг, удаление зависших сот, CPU/RAM (хост + cell-agent), upgrade-agent — 2026-06-20
- [x] **Вариант 2 обхода olcrtc** (debug): backend+админка «Варианты обхода», `deploy_olcrtc.py`, PC/Android UI+движок рядом с WDTT — 2026-07-24. Prod: Jitsi pool + `olcrtc@pc`/`@android`.
- [x] **olcrtc room pool MVP (PC≠Android) + Wi‑Fi OK** — 2026-07-24:
  - Разные комнаты: PC `meet.egovm.ru/SilentVpnOlcrtcHive`, Android `meet.playform.ru/SilentVpnOlcrtcHiveAndroid`
  - Разные `data-pc` / `data-android` (общий `data/` ломал одновременную работу)
  - API `GET /api/vpn/olcrtc-config?device_type=&fingerprint=`
  - PC: dial/warm/fake-ip/DNS HTTPS reject; Android: hev TUN + libolcrtc.so
  - **Проверено:** PC + Android **одновременно по Wi‑Fi** работают
  - **LTE:** Jitsi/`meet.egovm.ru` (и смена host) часто режется DPI оператора — отложено
- [x] **olcrtc WB/Telemost room pool + отдельный room-agent** — 2026-07-25: пул pc/android у всех 3 провайдеров; YAML failover в `olcrtc@pc`/`@android`; агент `ai/olcrtc_room_agent.py` (не VK); host Playwright `olcrtc_room_provision_host.py`. Android WB placeholder → заменить свежим ID.
- [x] **olcrtc LTE / мобильный интернет (сервер готов):** Android Telemost room `10347145470417` + unit `android-telemost` active, max=25; assign OK. Android WB — нет cookies аккаунта (агент не создаст). Физический LTE на телефоне: выбрать Телемост в debug. Wi‑Fi pool уже готов.
- [x] **olcrtc масштаб 1000+ (каркас):** `OlcrtcRoom`+sticky+cap+heartbeat, пул в админке (drain), agent `target_free_ratio`, yaml из БД, cell-agent `/v1/olcrtc/apply` + `deploy_olcrtc_cell.py`, клиенты 503/heartbeat — 2026-07-25. Нагрузочный прогон 1000 online — отдельно.
- [x] **olcrtc 1000+ прогрев пула на проде** — 2026-07-25: `seed_olcrtc_mass_pool.py` → capacity ≥1100 (`max_clients=25`), **47 unit’ов active**, agent `enabled` + `target_capacity=1100`, Jitsi auto без cookies; `pool_denied` только если нет ни одного провайдера.
- [x] **olcrtc 1000+ нагрузочный прогон** — 2026-07-25: `loadtest_olcrtc_1000.py` → **pass** (1000 assign, 500pc+500android, unique 22+22, denied 0, 25.5s). Spill: olcrtc бинарь+template на соты `87.58.213.193` / `78.17.74.27` (`deploy_olcrtc_to_hive_cells.py`).
- [x] Документировать YuMoney webhook flow в APIS.md (`POST /api/payments/yumoney/notify`) — 2026-07-25
- [x] **olcrtc pool redesign** — 2026-08-11: on-demand scale при deny, цикл ~2.5м, idle GC 5м, heal sticky clear, админка Обзор/Комнаты/Агент, Playwright finally, wdtt MemoryHigh/Max; задеплоено
- [x] **olcrtc session-mode («как VK»)** — 2026-08-11: create on demand / max_clients=1 / leave=teardown; агент prune+heal без autoscale; Telemost-only; host-only Playwright; wipe `olcrtc_session_reset.py`; smoke PC+Android PASS; PC/Android clear cache on leave
- [x] **olcrtc полностью снят** — 2026-08-11: прод stop units/host-provision; API always disabled; админка без секции 2; PC/Android force WDTT, меню обхода убрано из release
- [x] **olcrtc 2.0 ПРОДУКТ (session-mode + агент)** — 2026-08-11: server smoke PASS; Playwright на Соте 1; Android `libolcrtc2.so` + menu; PC `build-debug-977561`. Инструкция: `.cursor/OLCRTC2_AGENT.md`. Ручной YouTube-тест. **Не на Улей.**
- [x] **olcrtc WB session-mode** — 2026-08-11: create/delete через WB HTTP API (не Playwright; antibot 498 обход); `ai/olcrtc_wb_api.py`; smoke PC+Android PASS; провайдер включён рядом с Телемост — **отозвано** (см. «olcrtc полностью снят»)
- [x] **olcrtc agent: liveness + prune + create** — 2026-07-27: HTTP probe WB/Telemost, удаление мёртвых комнат, sync `auth.token`, create до target; цикл 15м; задеплоено на прод (9/9 alive)
- [x] **Android: fix регрессии ЧС/БС** — 2026-08-11: возвращён `bootstrap-companion` в `excludeKey` (туннель пересоздавался на каждый TURN-адрес и рвал воркеры), БС не тащит Silent в туннель, резолв правил сайтов ушёл в фон; DoH-эксперимент откатан в stash. Проверено на Wi-Fi и мобильном.
- [x] **DNS: «Как на сервере» + свой DNS в release (Android + PC)** — 2026-08-11: меню DNS открыто в release, дефолт не подменяет `wg_dns` (фильтр угроз жив), свой ввод до 3 адресов с валидацией; PC `normalizeDnsValue` больше не игнорирует серверный DNS. Тесты: `DnsPresetTest` + `pc/test/dns.test.js`
- [ ] PC: собрать debug/installer с новым меню DNS и проверить свой DNS на живом подключении

### Продукт / монетизация

- [x] **Оплата YuMoney (кастомный QuickPay) по плану `.cursor/PLAN_PAYMENTS_YUMONEY.md`** — 2026-07-14: backend (10 кошельков через `.env`, per-wallet секрет, `label` высокой энтропии, `SELECT…FOR UPDATE`, `operation_id` идемпотентность, допуск на комиссию, codepro/unaccepted/currency, promo `use_count` при завершении), `GET /payments/status/{label}`, `GET /payments/success-page`, theme-поля `payment_*` (backend + admin-ui + PC + Android). Юнит-тесты **37/37 OK**; **задеплоено на прод**, 2 реальных кошелька настроены и проверены живыми уведомлениями (signature/commission/sum=1-атака/идемпотентность — все ОК). Push во все три ветки (`main`/`pc`/`android`). **Осталось:** релизы PC/Android с новым UI оплаты (`assembleRelease`/`build-installer` + OTA публикация)
- [x] **Баг-фикс: YuMoney `sign` вместо устаревшего `sha1_hash`** — 2026-07-14: реальный тестовый платёж пользователя (15₽) зависал на «ждём подтверждения» — ЮMoney с 18.05.2026 перестали слать `sha1_hash`, шлют только `sign` (HMAC-SHA256 по отсортированным URL-encoded параметрам). Код проверял только старый `sha1_hash` → все реальные уведомления получали 400. Добавлена проверка `sign` (fallback на `sha1_hash`), +6 юнит-тестов (**43/43 OK**), задеплоено на прод и живьём подтверждено на обоих кошельках (`status: completed`). Push `main` + bump Android `1.0.156` + push `android`.
- [x] Тестирование оплаты пользователем завершено (15/20/25₽, все 3 плана, PC + Android) — цены на проде **возвращены** на 199/499/1499 (`.env` → recreate `api` → `deploy_stable.py`), проверено `/api/payments/plans`. Push не требовался (цены — только в `.env` на VPS, не в git)

- [x] Реферальные ссылки + раздел «Бонусы» (backend + PC + Android): промо/реф на регистрации, +30 дней обоим после первой оплаты invitee — 2026-07-09
- [x] Реф-политика growth: лимит 10 наград/30д на inviter + текст «условия могут измениться» — 2026-07-09
- [x] Админка «Бонусы» (бывш. Промокоды) + статистика рефералов/промо; cleanup тестовых ref.* — 2026-07-09
- [x] Тексты «Бонусы»: одно общее описание (intro), без дубля внизу — 2026-07-09
- [ ] После ~1000 пользователей: пересмотреть реф-условия (+15/+15 или бонус только inviter / только quarterly+)

### iOS-клиент

- [ ] Доработать iOS до паритета с Android/PC (bootstrap, tunnel API, ConfigSync, OTA) — на `origin/ios` только `e701e3f`
- [ ] Подключить server-driven UI (`ThemeData`) на iOS
- [ ] Рефералка / «Бонусы» на iOS (паритет с PC/Android)

### QA / ручное тестирование

- [x] Android: прогнать OTA + ConfigSync на мобильной сети vs Wi-Fi (instrumented на устройстве: Wi‑Fi/LTE/LTE+VPN, `OK (17 tests)`) — 2026-07-08
- [ ] PC: прогнать полный цикл bootstrap → login → connect → OTA через tunnel → disconnect
- [x] PC throughput baseline: ~75–78 Мбит @108, connect ≤5с (`26431a9` на `pc`) — 2026-07-09; дальше улучшать от этого профиля

### Следующие релизы

- [x] Android: bump version → `1.0.154` → push `origin/android` (Telegram parity PC) — 2026-07-11
- [x] Android: bump version → `1.0.155` → push `origin/android` (VK Calls Wi‑Fi DPI) — 2026-07-12
- [x] Android: bump version → `1.0.156` → push `origin/android` (YuMoney payment flow) — 2026-07-14
- [x] Android: bump version → `1.0.159` → push `origin/android` (theme bg + Ugoos/TOX после 158) — 2026-07-22
- [ ] Android: `assembleRelease` → `python scripts/deploy_release.py ...` (OTA 1.0.159)
- [x] PC: bump version → `1.0.154` → push `origin/pc` (Telegram latency + exclusions) — 2026-07-11
- [x] PC: bump version → `1.0.155` → push `origin/pc` (WG 1.1 + Wi‑Fi VK Calls) — 2026-07-12
- [x] PC: bump version → `1.0.156` → push `origin/pc` (installer WG repair) — 2026-07-13
- [x] PC: bump version → `1.0.159` → push `origin/pc` (theme/admin/Win10 wg-turn после 158) — 2026-07-22
- [ ] PC: `build-installer.bat` → `python scripts/deploy_release.py ...` (OTA 1.0.159)

---

## Выполнено (по коммитам)

### Memory Bank / документация

- [x] Обновить Memory Bank (MEMORY_BANK.md, APIS.md, TASKS.md) — 2026-06-20
- [x] Документировать деплой по веткам (`backend/scripts/`, `pc/scripts/`, `android/scripts/`) — 2026-06-18
- [x] SSH-секреты в `.env.deploy` через `_deploy_common.py` — 2026-06-18
- [x] Убрать старые deploy/diag-скрипты из корня и `android/scripts/inspect_*.py` — 2026-06-18

### Backend (`origin/main`)

- [x] Улей / Соты (Hive): модель HiveCell, балансировка VPN, admin «Улей», cell-agent, proc_stats, deploy_hive — 2026-06-20
- [x] `GET /api/vpn/sync-state` для ConfigSync — `d46bce3`, `de4e241`
- [x] Profile sync revision без heartbeat `last_connected` — `de4e241`
- [x] VK Calls silent_token auth для AI-агента (app 7793118) — `8ce55f1`, `cc5e1d2`, `fe61a68`
- [x] VK agent: payload auth, hash heal, flood reset — `fe61a68`
- [x] VK agent мониторит всех пользователей, heal пустых/сломанных слотов — `d71c2ee`
- [x] Ротация VK agent token без рестарта (`POST /api/admin/vk/agent/sync-env`) — `bfc7d88`
- [x] Multi-device sessions, disconnect latch, dedupe — `2562487`, `2fafa5a`, `908fc9d`, `bf693f9`
- [x] S2S keepalive `/api/vpn/internal/online` — `7cf4c8e`
- [x] Client hash failure reporting — `9e98ddf`
- [x] OTA updates API + admin page + deploy script — `bb80eb2`, `55ac8ac`
- [x] Build Agent: ночная OTA-сборка PC/Android (00:00 МСК, новый bootstrap-хеш, version без bump), `build-agent/`, кнопки в админке — 2026-06-19
- [x] Registration test mode toggle — `f687065`, `809d8e8`
- [x] Trial subscription 3 дня после верификации — `d2c5b07`
- [x] Per-user hashes, device rename API — `bfc7d88`
- [x] Password reset только через web form — `e31b843`
- [x] Two-step login theme + reset-password page — `c559b5c`, `8322114`
- [x] Theme: update bar colors/labels — `76b0df7`
- [x] Theme app_name Silent VPN — `552da54`
- [x] Email в BackgroundTasks (register/forgot) — `02bf8c5`
- [x] SMTP_SSL port 465 / STARTTLS 587 — `44d7284`
- [x] Verify-email HTML page — `1daec45`, `5d81d2c`
- [x] wdtt-server systemd + master password — `94709e5`
- [x] Manual hash management (без VK API auth) — `17e6e44`
- [x] Admin dashboard CPU freq — `e3fd34d`, `320406c`, `5fc0a76`
- [x] Admin: verify/delete user — `ebb278a`
- [x] Admin: grant subscription, 3-day/unlimited plans — `90cbda1`, `01be25e`
- [x] YuMoney payments init + notify endpoint — `payments.py` на main (`/init`, `/yumoney/notify`, `/promo/check`)

### Admin UI (`origin/main`)

- [x] Страница «Улей» — соты, SSH auto-connect, CPU/RAM, вывод/удаление, upgrade-agent — 2026-06-20
- [x] ClientPreview: все экраны меню — `c5c5d61`
- [x] ThemePage: настройки по экрану предпросмотра — `01291ba`
- [x] Updates page: кнопка скачивания билдов — `3e8c082`, `39a291b`
- [x] Updates page: «Собрать релиз в update» (PC/Android) + статус build-agent — 2026-06-19
- [x] VK Calls auth через browser callback — `7dfe326`
- [x] Mobile responsive (drawer nav, grids) — `383db65`
- [x] VK hashes grouped by user — `49abeca`, `1a2c796`
- [x] Logs UI + фильтр по уровню + поиск — `94709e5`

### PC (`origin/pc`, v1.0.142)

- [x] Релиз v1.0.142 запушен — `8847047`
- [x] ConfigSync + OTA через tunnel при VPN — `032c2cf`, `8847047`
- [x] In-app password reset удалён, web-only — `b5aa9d8`
- [x] Report broken VK hashes через tunnel — `b910eeb`
- [x] Bootstrap login flow как Android (tunnel API) — `49ff5d0`…`2603cea`
- [x] Полный туннель 0.0.0.0/0, bootstrap subnet — `bf2a7ea`
- [x] Android parity routing/DNS/AllowedIPs — `bcec5f7`, `ce91b15`
- [x] Two-step login, remember me — `3327e5d`
- [x] Update bar из server theme — `a910fcb`
- [x] In-app OTA bar (check, download, NSIS install) — `edc1173`, `89267e7`
- [x] Test subscription mode в UI — `5fdbad0`

### Android (`origin/android`, v1.0.130)

- [x] VPN recovery: Wi‑Fi↔LTE, звонок, обрыв/3G — pause + force restartTransport — 2026-06-18
- [x] Bootstrap VPN на мобильном: tunnel API для входа/регистрации/forgot (регрессия `8cbace5`) — 2026-06-18
- [x] Релиз v1.0.130 запушен — `8cbace5`
- [x] Wi-Fi ConfigSync, mobile sync off — `8cbace5`
- [x] OTA через tunnel при VPN — `2e83da5`, `7726aef`, `8cbace5`
- [x] Preserve config/hashes после OTA — `2f79f52`, `a73d0f3`
- [x] In-app password reset удалён, web-only — `29e10ac`, `4990a85`
- [x] Report broken VK hashes — `87ded2e`
- [x] Bootstrap VPN для mail/browser — `4990a85`
- [x] VPN notification fix API 12+/16 — `79052eb`, `386cea3`
- [x] Session on login + public connect/disconnect — `52a3098`
- [x] Hash failure reporting — `9576c8d`
- [x] Two-step login UI — `8112e68`

### iOS (`origin/ios`)

- [x] Начальный каркас клиента — `e701e3f` (Swift + SwiftUI + NetworkExtension)
