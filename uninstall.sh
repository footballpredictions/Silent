#!/bin/sh
set -eu
if [ -x /opt/etc/init.d/S99silent-keenetic ]; then
    /opt/etc/init.d/S99silent-keenetic stop
elif [ -x /opt/lib/silent-keenetic/silent-keenetic ]; then
    /opt/lib/silent-keenetic/silent-keenetic --cleanup
fi
rm -f /opt/etc/init.d/S99silent-keenetic /opt/etc/ndm/netfilter.d/100-silent-keenetic.sh
rm -rf /opt/lib/silent-keenetic
if [ "${1:-}" = '--purge' ]; then rm -rf /opt/etc/silent-keenetic; fi
echo 'Silent Keenetic удалён. Конфигурация сохранена, если не указан --purge.'
