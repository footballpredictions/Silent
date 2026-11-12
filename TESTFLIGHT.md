# Silent VPN на iPhone через TestFlight

С Windows можно запустить сборку и загрузку через GitHub Actions. Сборка выполняется на GitHub-раннере macOS с Xcode. Локальная сборка на Mac тоже поддерживается.

Версия в проекте указана в `MARKETING_VERSION` в `project.yml`. Идентификаторы приложения и расширения — `com.silent.vpn` и `com.silent.vpn.tunnel`. Группа — `group.com.silent.vpn`.

Для сборки TestFlight нужна native-библиотека. Подключение VPN можно проверить на iPhone через внутреннюю группу TestFlight.

Первый тумблер в исключениях — «Российские сервисы мимо VPN». Он действует на все приложения, использует серверную политику и кеш, а ручные списки сохраняет без применения. При выключении возвращается прежний режим сайтов. Серверные VPN-исключения имеют приоритет; неизвестные адреса остаются в VPN. Распознавание рассчитано на обычный системный DNS; собственный DoH/DoT приложения не даёт доменные ответы для классификации.

## Что умеет приложение

Те же экраны, что в Android: вход и регистрация, «Запомнить меня», восстановление пароля, главный тумблер, меню на половину экрана.

Пункты меню: Подписка (3 и 5 устройств, оплата YuMoney), Исключения сайтов, DNS, Выбор сервера 1–5, Бонусы, Сессии, Поддержка, О сервисе. Цвета и тексты берутся с сервера (`/api/vpn/theme`). Шрифт — Inter, те же размеры, что в Android (11 / 12 / 14).

Туннель — тот же канал, что на Android: локальный WireGuard на `127.0.0.1`, дальше VK. Библиотека собирается скриптом из `android/app/wdtt-go`. Пока скрипт не запускали, тумблер честно пишет, что движок не собран, и VPN не включается.

На iPhone нельзя выбрать, какие чужие приложения идут мимо VPN: так устроена система. Список сайтов работает — они уходят мимо туннеля. QR-вход на телефоне нет, он только у телевизора.

## GitHub Actions

Workflow `Silent VPN iOS` компилирует приложение и туннель при push в ветку `ios`. Push тега вида `ios-testflight-4` запускает подписанную сборку и загрузку. Тег должен указывать на коммит ветки `ios`, а число в теге — на свободный номер сборки для текущей версии приложения. Исходники Go-движка закреплены в workflow по SHA Android-коммита.

1. В [Apple Developer](https://developer.apple.com/account/resources/identifiers/list) проверьте два App ID и включите Packet Tunnel в Network Extensions. Назначьте обоим App ID группу `group.com.silent.vpn`. Создайте два профиля распространения App Store Connect для одного сертификата Apple Distribution, по одному на каждый App ID.
2. В [App Store Connect](https://appstoreconnect.apple.com/) проверьте карточку приложения с Bundle ID `com.silent.vpn`. В **Users and Access → Integrations → App Store Connect API** нужен командный API-ключ с правом загрузки сборок, например с ролью Developer. Сохраните Key ID, Issuer ID и скачанный `.p8`.
3. В **GitHub → Settings → Secrets and variables → Actions** добавьте секреты репозитория.

   | Секрет | Значение |
   | --- | --- |
   | `IOS_DISTRIBUTION_P12` | Сертификат Apple Distribution вместе с закрытым ключом в `.p12`, в Base64 |
   | `IOS_DISTRIBUTION_PASSWORD` | Пароль `.p12` |
   | `IOS_APP_PROFILE` | `.mobileprovision` для `com.silent.vpn`, в Base64 |
   | `IOS_TUNNEL_PROFILE` | `.mobileprovision` для `com.silent.vpn.tunnel`, в Base64 |
   | `ASC_KEY_ID` | Key ID |
   | `ASC_ISSUER_ID` | Issuer ID |
   | `ASC_PRIVATE_KEY` | Файл `.p8` командного API-ключа, в Base64 |

   В PowerShell файл можно преобразовать в Base64 и отправить сразу в секрет через GitHub CLI, например для `.p8`.

   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path -LiteralPath 'AuthKey_KEYID.p8').Path)) |
     gh secret set ASC_PRIVATE_KEY --repo footballpredictions/Silent
   ```

4. Когда сборка ветки прошла и секреты настроены, создайте тег на нужном коммите ветки `ios` и отправьте его в GitHub. В примере `4` — номер сборки, который следует сверить в App Store Connect.

   ```bash
   git tag ios-testflight-4 <ios-commit-sha>
   git push origin refs/tags/ios-testflight-4
   ```

5. После успешной загрузки дождитесь обработки сборки в App Store Connect. Заполните сведения об экспортном контроле для VPN и добавьте сборку во внутреннюю группу TestFlight. Для публичной ссылки добавьте её во внешнюю группу, заполните сведения для проверки Apple и отправьте сборку на TestFlight App Review. После одобрения включите **Public Link** в этой группе.

## Локальная сборка на Mac и загрузка в TestFlight

1. **Apple Developer Program**, 99 долларов в год, на сайте developer.apple.com. Без него TestFlight недоступен.
2. **Mac** с macOS, **Xcode 26** (или новее) и SDK iOS 26 или новее. При первом запуске Xcode дождитесь, пока скачается iOS.
3. **Go 1.26** — та же версия, что в `android/app/wdtt-go/go.mod`. Скачать: https://go.dev/dl/
4. На Mac в терминале:
   ```bash
   brew install xcodegen
   ```
5. Скопируйте на Mac `ios`, `android/app/wdtt-go` и `android/app/site-router`, сохраняя эти пути внутри `Silent-Project`.
6. В терминале:
   ```bash
   cd Silent-Project/ios
   bash scripts/build-libwdtt.sh &&
     test -s SilentTunnel/Native/libwdtt.a &&
     xcodegen generate &&
     open Silent.xcodeproj
   ```
   Скрипт кладёт `SilentTunnel/Native/libwdtt.a`. Без этого файла в TestFlight уйдёт приложение, которое не поднимет VPN.
7. В [developer.apple.com/account](https://developer.apple.com/account) → Identifiers создайте два App ID:
   - `com.silent.vpn`
   - `com.silent.vpn.tunnel`
   У обоих включите **Network Extensions** (Packet Tunnel) и **App Groups**. Группа одна: `group.com.silent.vpn`. Её же отметьте у обоих идентификаторов.
8. В App Store Connect создайте приложение: имя Silent VPN, bundle id `com.silent.vpn`, SKU любой, например `silent-vpn-ios`.
9. В Xcode выберите цель **Silent** → Signing & Capabilities → Team (ваша команда). То же у цели **SilentTunnel**. Если Xcode ругается на capabilities, нажмите, чтобы он сам поправил профиль. Bundle id не меняйте.
10. Подключите свой iPhone кабелем, выберите его и нажмите Run. Разрешите VPN, когда iOS спросит. Проверьте вход, тариф и тумблер. В контейнере группы появится `engine/wdtt.log`, если канал не встанет.
11. **Product → Archive**. Когда архив готов: **Distribute App → App Store Connect → Upload**.
12. Если App Store Connect запросит сведения об экспортном контроле, заполните анкету с учётом того, что приложение включает VPN (WireGuard).
13. TestFlight → сборка → **Internal Testing**: добавьте себя и людей из той же команды App Store Connect (до 100 человек). Им письмо приходит сразу, проверка Apple не нужна.
14. **External Testing**: группа с любыми email, до 10 000 человек. Первую сборку Apple смотрит (обычно от нескольких часов до пары дней). В «What to Test» напишите: войти, включить VPN, открыть сайт. Для входа нужен аккаунт Silent VPN.
15. На проверке могут спросить, зачем приложению обычный HTTP. Ответ: API сот слушает порт 9100 без TLS, Улей по HTTPS стоит запасным, из РФ его часто не открыть. Это уже записано в приложении (`NSAllowsArbitraryLoads`).

Каждая новая сборка: снова Archive → Upload. Номер сборки (`CURRENT_PROJECT_VERSION` в `project.yml`) увеличивайте на 1, иначе App Store Connect не примет файл.

## Пользователю: как поставить через TestFlight

Этот текст можно переслать как есть.

1. На iPhone откройте App Store и установите бесплатное приложение **TestFlight** от Apple.
2. Откройте письмо или ссылку, которую прислал разработчик (она начинается с `https://testflight.apple.com`).
3. Нажмите **Принять** / **View in TestFlight**, затем **Установить**.
4. На домашнем экране появится **Silent VPN**. Откройте его.
5. При первом включении VPN iPhone спросит разрешение добавить конфигурацию VPN. Нажмите **Разрешить** и подтвердите паролем или Face ID.
6. Войдите в тот же аккаунт, что на Android или компьютере. Если подписки нет — откройте «Подписка», выберите 3 или 5 устройств и тариф. Оплата откроется в браузере, после неё вернитесь в приложение.
7. На главном экране сдвиньте большой переключатель. Статус должен стать «Подключено».
8. Обновления приходят сами в TestFlight. Срок тестовой сборки — 90 дней, потом нужна новая.

Если TestFlight пишет, что приглашение недействительно, попросите прислать ссылку ещё раз. Если приложение просит VPN и сразу выключает его, напишите разработчику: на телефоне должна стоять сборка, собранная уже после `build-libwdtt.sh`.
