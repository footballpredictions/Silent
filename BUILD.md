# Keenetic 1.0.169 — локальная сборка 2026-10-10

Создан отдельный проект `keenetic`, без изменения исходного OpenWrt, ПК, серверов или роутеров.

- Go 1.26.2, CGO=0, 7 Linux targets: aarch64, armv7, armv5, mipsel, mips, x86_64, i386.
- Реально скомпилированы 14 ELF: автономный агент + текущий `pc/wdtt-go` транспорт для каждого CPU.
- ELF class/machine/endianness проверены; PT_INTERP отсутствует. MIPS softfloat, ARMv5/7 отдельные варианты.
- `go test ./...`: PASS, 25 cases включая подтесты. Исполнение на Windows: переносимые API/auth/config/WG-parser/DNS-boundary tests. Linux TUN и реальная маршрутизация этим не проверены.
- `GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go vet ./...`: PASS.
- Python unittest: 8 PASS. POSIX network.sh исполняется через Git Bash с подменёнными сетевыми командами; проверены ограничение LAN, IPv6 guard, rollback частичного запуска, собственная cleanup и быстрые NDM hooks. Хостовые маршруты не менялись.
- Release checks: все архитектуры, executable modes, LF/no-BOM, SHA256 manifest PASS.
- Все 14 бинарников, runtime scripts и README в итоговом архиве byte-for-byte совпадают с текущими файлами сборки/исходниками.
- Universal: 54039137 bytes, SHA256 `770f8985e0a59f6edf62e4eb5f9f3fb5c96fd8c1509493643e92dee408c31392`.
- `dist/` содержит универсальный архив, 7 отдельных архивов, manifest.json и SHA256SUMS.

Проверка архивов однажды запущена до завершения их пересоздания: получили ожидаемую неполную gzip/старый manifest. После exit=0 финальной сборки повторены проверки: 8 PASS; это не дефект runtime.

Требуются Entware, Linux >=3.2, TUN, подходящие iptables/ip6tables/ipset и свободные правила/таблица. Панель LAN:8787, отдельный локальный пароль; DNS LAN:15353 (не занимает mDNS 5353). IPv4 VPN, IPv6 LAN forwarding блокируется на время подключения. FastNAT/PPE, реальный RAM/CPU, трафик LAN, NDM события, supervisor и автоподключение требуют проверки на настоящем устройстве. Автоматическое отключение ускорения не выполняется; fail-open, strict kill switch отсутствует.

Исследование пользовательской темы 4PDA и первичных источников: RESEARCH.md. Commit/push/публикация/установка не выполнялись. Существующий OpenWrt DIAGNOSIS и четыре PC WIP пути сохранены.
