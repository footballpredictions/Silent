# Исследование порта Silent VPN для Keenetic

Дата: 2026-10-10. Источники прочитаны; роутеры и серверы не изменялись. Результат сборки не означает подтверждённую работу на конкретной модели.

## Запрошенная тема 4PDA

[Keenetic – способы обхода блокировок](https://4pda.to/forum/index.php?showtopic=1109473) успешно прочитана через Firecrawl после недоступности прямого веб-чтения. Это обсуждение развёртывания VPN и выборочного обхода на Keenetic. В первой странице присутствуют АнтиЗапрет/OpenVPN, настройки DNS, ссылки на проекты Zapret и сообщения об AmneziaWG и KVAS. Тема полезна как указатель на практические подходы, но не подтверждает совместимость WDTT/Silent VPN. Команды и сторонние установщики из обсуждения автоматически не выполнялись.

## Подтверждённая платформа и зависимости

- [Keenetic OPKG](https://support.keenetic.com/hero/kn-1011/en/18481-opkg.html): среда дополнительного ПО через Entware на USB-накопителе с EXT; рекомендован EXT4. [Внутренняя память](https://support.keenetic.com/titan/kn-1811/en/18482-installing-opkg-entware-in-the-router-s-internal-memory.html) доступна только части моделей, начиная с KeeneticOS 3.7. Архитектуру выбирать по модели и реальному CPU/ABI, а не по названию семейства.
- [WireGuard upstream](https://git.zx2c4.com/wireguard-go/about/): Linux-процесс `wireguard-go -f IFACE` создаёт TUN; управление возможно через `wg`. [Исходник TUN](https://github.com/WireGuard/wireguard-go/blob/master/tun/tun_linux.go) открывает `/dev/net/tun`. Встроенный в Go-агент wireguard-go также требует поддержку TUN ядром; простое создание device node её не добавляет.
- [Entware Makefile wireguard-go](https://github.com/Entware/entware-go/blob/master/wireguard-go/Makefile) подтверждает пакет и путь `/opt/bin/wireguard-go`. Для встроенной реализации внешний пакет не обязателен.
- [Go MinimumRequirements](https://go.dev/wiki/MinimumRequirements): начиная с Go 1.24 минимум Linux 3.2; необходимы FUTEX и EPOLL. MIPS/mipsle требуют MIPS32r1. Локальный `go tool dist list` содержит linux/mips, linux/mipsle, linux/arm, linux/arm64, linux/amd64. Для роутерного MIPS собирать с `GOMIPS=softfloat`; ARMv5/ARMv7 выбирать через `GOARM=5`/`7`; [официальный Go MIPS wiki](https://go.dev/wiki/GoMips). Наличие цели компиляции не подтверждает запуск на конкретном ядре.

Практический preflight: версия `uname -r`, наличие character device `/dev/net/tun`, `ip -4 rule show`, `ipset` и xtables-версия `iptables`. Для policy routing использовать Entware `ip-full`, если имеющийся `ip` не поддерживает `rule`; при iptables с `nf_tables` не предполагать совместимость со штатными xtables Keenetic. Последнее подтверждает исходный проект [SSClash-Go](https://github.com/zerolabnet/SSClash-Go), но требует проверки установленного устройства.

## События и восстановление правил

[Первичная документация NDM OPKG](https://github.com/ndmsystems/packages/wiki/Opkg-Component):

- `/opt/etc/init.d/S*` для старта/остановки Entware-процессов; не заменять чужой initrc.
- `/opt/etc/ndm/netfilter.d/` вызывается при переписи таблицы. Проверять `$type` (IPv4/IPv6) и `$table` (filter/nat/mangle), восстанавливать только свои правила.
- Все хуки выполняются общей очередью; таймаут каждого — 24 секунды. Полный reconnect, DNS-сеть и длительное ожидание переносить в агент/фон, оставляя hook быстрым.
- `wan.d` сообщает start/stop подключения. С 4.0 основной интерфейсный hook — `iflayerchanged.d`; `ifstatechanged.d` сохранён для совместимости.

Инженерное решение: отдельные именованные цепочки, fwmark/mask, номер таблицы и приоритет правила; не менять main default, глобальные политики, штатные `_NDM_*`-цепочки или весь ruleset. Ограничить захват входящим LAN-интерфейсом и LAN-подсетью. Добавить явные LAN→TUN FORWARD, обратный ESTABLISHED/RELATED и scoped NAT, если сервер не маршрутизирует клиентские LAN-подсети. В таблице VPN нужны необходимые локальные маршруты либо исключения до назначения mark. Пакеты самого транспорта и серверный endpoint должны оставаться в обычной маршрутизации, чтобы не создать петлю. Эти рекомендации требуют испытания с реальными NDM-правилами.

## Ускорение и security level

[Объяснение разработчика NDM о netfilter](https://forum.keenetic.ru/topic/1355-как-правильно-использовать-netfilter-в-opkg/) подтверждает, что ускорители могут изменять поведение policy routing/netfilter. Для диагностики указаны `system set net.netfilter.nf_conntrack_fastnat 0`, `no ppe software`, `no ppe hardware`. Глобальное выключение снижает скорость; порт не должен автоматически сохранять эти изменения. Сначала проверять прохождение новых и существующих LAN-соединений и восстановление правил после WAN-событий. Обычный `MARK` отделён от внутреннего NDM mark с NDMS 2.08, однако требуется исключить конфликты с другими Entware-программами.

Обычный самостоятельный Linux TUN с частными iptables-правилами и штатный NDM OpkgTun — разные пути интеграции. Не менять security-level всех интерфейсов и не обещать UI-видимость собственного TUN без проверки. [TrustTunnel-Keenetic upstream](https://github.com/artemevsevev/TrustTunnel-Keenetic) показывает альтернативный путь через OpkgTun на прошивках 5+, но его совместимость не переносится автоматически на Silent VPN.

## Панель и доменные исключения

- Панель Go привязывать к конкретному LAN_IP:PORT; сохранять штатные порты управления Keenetic. Если используется BusyBox, [официальная справка](https://busybox.net/downloads/BusyBox.html) подтверждает `httpd -f -p IP:PORT -h WEBROOT -c CONF`; наличие applet определяется сборкой.
- [Штатные DNS-based routes](https://support.keenetic.com/starter/kn-1112/en/51150-dns-based-routes.html) доступны с KeeneticOS 5.0: клиент должен находиться в Default policy и использовать роутер как DNS. Чужой DoH/DoT обходит наблюдение DNS; это нельзя скрывать в описании доменных исключений.
- Для собственного DNS proxy инженерный вариант: отдельный LAN_IP:PORT и DNAT только LAN TCP/UDP53. Не заменять системный DNS/DHCP и не включать глобальный opkg dns-override. Добавлять A-ответы в частный ipset direct с TTL/ограничением размера и проверять CNAME, AAAA, TCP DNS. [DNSmasq upstream](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html) подтверждает доменные ipset, включая поддомены, и требование заранее создать set; этот принцип можно реализовать в Go без замены dnsmasq.
- Ограничение IPv4 должно быть явно заявлено: без отдельной обработки AAAA/IPv6 трафик IPv6 не получает обещанного VPN-маршрута. Совместный IP CDN также может расширить исключение за пределы одного домена.

## Проверка на устройстве ещё требуется

TUN/iptables/ipset-модули, соответствие архитектуры, IPv4 LAN forwarding, конфликт marks/tables, свежий handshake и фактический внешний IP, перезапись NDM после изменения WAN, DNS-петли, локальная панель после отключения VPN, поведение при падении процесса, скорость с ускорением, расход RAM и CPU. До этого статус — собранный отдельный порт с локальными проверками, а не подтверждённая поддержка всех Keenetic.
