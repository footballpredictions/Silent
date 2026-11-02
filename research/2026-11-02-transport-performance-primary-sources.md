# Скорость Silent при белых списках: первоисточники и границы выводов

Дата проверки: 2026-11-02. Это исследовательская часть аудита, без изменения production, деплоя, commit или push. Наблюдение владельца: обычная скорость около 40 Мбит/с, в отдельных условиях белых списков 1–10 Мбит/с, сравниваемый VLESS стабилен. Одинаковость устройства, сети, выходного сервера, транспорта и точки speedtest пока не подтверждена. Причина конкретной просадки не установлена.

## 1. Сначала разделить фактические ветки

Канон `.cursor/TECHNOLOGY.md:45–55` описывает обычный dataplane WireGuard + обфусцированный UDP к выбранному серверу. Это не общий кластерный TCP-прокси. Современный обход Telemost/WB устроен иначе.

Активные сборочные входы для olcrtc2:

- `vendor/olcrtc/cmd/olcrtc2-cnc/main.go:1,50–62`: `client.RunWithReady`, `Transport: "vp8channel"`, FPS 60, BatchSize 64.
- `vendor/olcrtc/cmd/olcrtc2-srv/main.go:1,51–61`: тот же VP8-транспорт и параметры на сервере.
- `android/app/olcrtc/build_olcrtc2_android.bat:8–10,64,73`: сборка именно из vendor, а не backend/olcrtc2.
- `pc/src/main/vpn/olcrtc2Session.js:750`: команда сборки PC указывает на тот же vendor.

**Задумано:** VP8 здесь несёт данные через медиапуть SFU; это не DataChannel. Само наличие зависимости pion/sctp не доказывает, что её congestion window ограничивает активный обход.

**Ложная зацепка:** `backend/olcrtc2/edge/link.go:23–35` оставляет smux MaxStreamBuffer по умолчанию, но entrypoints `backend/olcrtc2/cmd/olcrtc2-{cnc,srv}/main.go:1` явно deprecated. Нельзя объяснять современный установленный клиент этим старым окном 64 KiB.

## 2. Подтверждённая цепочка активного VP8

`cmd/olcrtc2-cnc` → `internal/client/client.go:309–317`, `buildSmuxClient` → `runtime.SmuxConfigFor` → `muxconn` с шифрованием → `vp8channel.Send` → KCP → очередь → writer по таймеру → `TrackLocalStaticSample.WriteSample` → SFU → сборка RTP/VP8 → KCP → smux → TCP-соединение назначения.

Факты по локальным исходникам:

- `vendor/olcrtc/internal/runtime/runtime.go:32–34,61–79,109–115`: data-plane smux v2, общий receive buffer 32 MiB, per-stream buffer 4 MiB. Сервер использует тот же выбор в `internal/server/server.go:260–268`. У control-plane отдельные маленькие буферы; переносить их на пользовательскую загрузку ошибочно.
- `vendor/olcrtc/internal/transport/vp8channel/kcp.go:76–92`: `NewConn3(...,0,0,...)` без KCP FEC, MTU 1400, окна по 4096 сегментов, `SetNoDelay(1,5,2,1)`. Последний параметр отключает стандартное loss-based congestion control KCP. Комментарий объясняет это полисером SFU; это намеренная настройка, а не автоматически найденный баг.
- `.../vp8channel/transport.go:520–533`: Send вызывает data KCP runtime. `.../kcpconn.go:130–160`: WriteTo помещает сформированный сегмент в outbound-очередь; `deliver:83–106` отбрасывает ошибочный CRC и overflow вместо передачи повреждённых данных.
- `.../vp8channel/transport.go:834–859,872–898`: writer по frameInterval формирует один bulk sample за тик, объединяя до BatchSize сегментов, с верхним размером sample 60 KiB (`:33`). Серверный per-peer pump применяет ту же схему (`:1401–1451`). Control traffic обслуживается раньше bulk.
- `.../vp8channel/transport.go:766–777`: запись sample сериализована mutex на общем video track. Это защита от перемешивания RTP sequence; удалять mutex ради скорости нельзя.
- `.../vp8channel/transport.go:1073–1113`: после невосстановленного sequence gap сборщик сбрасывает `frameValid` и собранные данные sample. Уже есть reorder buffer перед сборкой; простой повторный «фикс reorder» без замеров не обоснован.

**Неясно:** совпадают ли установленные клиентский и серверный binaries с этими исходниками; какие средние, p95 и максимальные размеры sample получаются в момент просадки. Код задаёт максимум, но не доказывает, что каждая отправка его заполняет.

В рассмотренных активных cmd/runtime/vp8-файлах нет явной фиксированной квоты именно 1–10 Мбит/с. Есть ограничение каденсом/батчами, окнами и очередями. Это не проверка отсутствия тарифных ограничений во всём продукте и не доказательство отсутствия полисера у оператора или SFU.

## 3. Наиболее применимый механизм: усиление потерь крупным sample

Pion v4.2.13 packetizer использует outbound MTU 1200, а `TrackLocalStaticSample` разбивает sample на RTP-пакеты. При заполненном sample 60 KiB получается порядка 50+ пакетов с учётом RTP/VP8 заголовков. Это **не IP-фрагментация**: речь о сборке одного VP8 sample из нескольких RTP datagrams. Источники: [Pion constants.go](https://raw.githubusercontent.com/pion/webrtc/v4.2.13/constants.go), [TrackLocalStaticSample](https://raw.githubusercontent.com/pion/webrtc/v4.2.13/track_local_static.go).

Иллюстративная модель, не полевой замер: при независимой вероятности потери RTP-пакета p и N пакетах в sample вероятность целого sample равна `(1−p)^N`. Для N=50 и p=1% это около 60.5%; при p=2% — около 36.4%. Реальные потери коррелированы, retransmission/reordering изменяют результат. Формула показывает, почему небольшая доля **невосстановленных** RTP-потерь способна вызвать гораздо больше потерянных batch/sample, KCP retransmissions и задержку smux-потоков. Она не предсказывает конкретные 1–10 Мбит/с.

Отдельная арифметическая оценка для одной writer-ветки: `60 ticks/s × 60 KiB/sample × 8 ≈ 29.49 Мбит/с` сырых данных sample. Это не универсальный end-to-end потолок Silent: другая ветка VK/TURN имеет другую передачу, установленный binary может отличаться, sample включает служебные данные, retransmissions и control, таймер и SFU тоже влияют. Из этой оценки нельзя объяснять обычные 40 Мбит/с без идентификации активного пути.

## 4. Что подтверждают стандарты, но нельзя безусловно переносить на VP8

### DataChannel/SCTP — только для реально выбранного datachannel

WebRTC DataChannel использует SCTP/DTLS/ICE; все SCTP streams одной association делят congestion window. Упорядоченная надёжная доставка и большие сообщения могут задерживать другие данные; message interleaving уменьшает часть sender-side блокировок. Источники: [RFC 8831 §5–6](https://www.rfc-editor.org/rfc/rfc8831.html#section-5), [RFC 8260](https://www.rfc-editor.org/rfc/rfc8260.html). Это условная архитектурная возможность, а не диагноз текущего VP8-транспорта.

У старого Go API Telemost `vendor/olcrtc/internal/engine/goolom/lifecycle.go:44` создаёт DataChannel с nil options. Pion по умолчанию выбирает ordered и reliable при отсутствии retransmission limits: [peerconnection.go v4.2.13](https://raw.githubusercontent.com/pion/webrtc/v4.2.13/peerconnection.go), [datachannel.go v4.2.13](https://raw.githubusercontent.com/pion/webrtc/v4.2.13/datachannel.go). WB API `internal/engine/livekit/livekit.go:61–64` публикует reliable data packets; LiveKit описывает их как in-order с повторными передачами, но best-effort при переподключениях: [официальная документация](https://docs.livekit.io/transport/data/packets/).

Нельзя просто включить unordered/lossy под существующим smux: smux рассчитывает на упорядоченный надёжный нижний поток. Придётся менять wire contract/recovery и обе стороны. [smux README](https://github.com/xtaci/smux), [pinned v1.5.57 stream flow-control](https://raw.githubusercontent.com/xtaci/smux/v1.5.57/stream.go).

### TURN, UDP и TCP

TURN допускает UDP/TCP/TLS от клиента к relay, при этом классический relay→peer остаётся UDP. Это разные пути с разными потерями/RTT; TCP — полезный fallback, но не гарантированное ускорение. RFC WebRTC отдельно предупреждает о head-of-line проблемах TCP relay. Источники: [RFC 8656 §3.1](https://www.rfc-editor.org/rfc/rfc8656.html#section-3.1), [RFC 8835 §3.4](https://www.rfc-editor.org/rfc/rfc8835.html#section-3.4).

### MTU и pacing

UDP не даёт собственного congestion control. Устойчивый tunnel должен учитывать перегрузку, размер datagrams и накладные заголовки. IP-фрагментация уменьшает надёжность: потеря одного фрагмента лишает получателя всего исходного IP-пакета. Поэтому подбирать MTU следует измерением полного пути, а не повсеместным увеличением до1420. Источники: [RFC 8085 §3.1–3.2](https://www.rfc-editor.org/rfc/rfc8085.html#section-3.2), [RFC 8899](https://www.rfc-editor.org/rfc/rfc8899.html). Настройка внутреннего TUN/WG MTU и размер VP8 sample — разные параметры.

TCP MSS относится к TCP data segment, без TCP/IP заголовков. Его clamp способен уменьшить внутренние TCP-сегменты, но сам по себе не ограничивает произвольные внутренние UDP datagrams и не отменяет overhead последующего WG/DTLS/RTP/TURN. Источник определения: [RFC 5681 §2](https://www.rfc-editor.org/rfc/rfc5681.html#section-2). Для VK/WG ветки нужен расчёт именно полного внешнего datagram; цифра MTU сама по себе не доказывает наличие либо отсутствие fragmentation.

## 5. Почему сравнение с VLESS не доказывает преимущество одного названия протокола

В документации Xray протокол проксирования, способ переноса данных и transport security — разные слои. VLESS может работать поверх разных transport methods; реальное сравнение требует знать RAW/XHTTP/gRPC/WebSocket, TLS/REALITY/Vision, сервер и маршрут. Источники: [Xray transport configuration](https://xtls.github.io/en/config/transport.html), [VLESS outbound](https://xtls.github.io/en/config/outbounds/vless.html).

Надёжный VLESS на той же SIM — сильная зацепка против объяснения только общей ёмкостью радио, но не контролируемое доказательство: SFU и VPS имеют другие адреса/маршруты и правила обработки. Возможный выигрыш даст дополнительный прямой TLS-based транспорт в тех сетях, где он проходит. Проходимость такого пути при строгом IP whitelist нельзя обещать. Шифрование/TLS не ослаблять ради теста скорости.

## 6. Приоритетные действия

1. **Без изменения dataplane: наблюдаемость и честный A/B.** На одном устройстве/операторе/месте фиксировать фактический режим Silent, provider/ICE UDP или TCP, версии binaries и выбранный выход. Одна точка загрузки, 1 и4 TCP потока, download/upload, RTT без нагрузки и под нагрузкой. Для VP8: sample size distribution, RTP gaps/recovered reorder, discarded samples, KCP retransmits/SRTT/send queue, inbound overflow, CPU одного ядра. Сопоставить с тем же VLESS тестом, не с другим случайно выбранным speedtest-сервером. Короткие bounded тесты; не создавать нагрузку на весь парк.
2. **После подтверждения потерь: канарейка адаптивного VP8 batching/pacing.** Меньше RTP-фрагментов на один sample в плохой сети, несколько равномерных отправок вместо крупного burst, с сохранением keyframe/control priority и packetization integrity. Цена — больше overhead; уменьшить batch без переработки pacing может просто уменьшить скорость. A/B по 1–2 новым сессиям, отдельная сборка/порт и rollback, без restart wdtt или сброса клиентов. KCP FEC рассматривать только после измерений: оно расходует полезную полосу.
3. **По измеренному пути: выбор carrier/выхода по качеству.** Если проблема — provider/SFU/маршрут, дать клиенту выбрать Telemost/WB/VK или дополнительный прямой транспорт по throughput+RTT/loss с hysteresis. Переключать новые сессии, не дёргать существующие. Поднять число workers/окна/BBR вслепую недостаточно: серверный TCP BBR не управляет внешним KCP/VP8/SFU.

## 7. Сопровождение зависимости

Официальный upstream `openlibrecommunity/olcrtc` архивирован владельцем 2026-10-05; README описывает старый проект как EoL и будущую переработку. Источник: [официальный репозиторий](https://github.com/openlibrecommunity/olcrtc). Это **долг сопровождения**, а не доказательство сетевой просадки. У Silent локальный vendor с собственными изменениями: массовое обновление на upstream/master или новый проект без совместимости и benchmark небезопасно.

Окончательный диагноз требует сетевого снимка именно в месте и во время просадки; текущий документ отделяет проверенные исходники от проверяемых гипотез.
