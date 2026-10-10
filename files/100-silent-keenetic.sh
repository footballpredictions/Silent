#!/bin/sh
# NDM's queue is shared (24s limit). Run only private rules for the changed table.
case "${type:-iptables}" in
    iptables) ;;
    ip6tables) [ "${table:-}" = filter ] || exit 0; table=ipv6 ;;
    *) exit 0 ;;
esac
case "${table:-}" in filter|nat|mangle|ipv6) ;; *) exit 0 ;; esac
[ -f /opt/var/run/silent-keenetic/active ] || exit 0
/opt/lib/silent-keenetic/silent-keenetic --restore "${table}" >/dev/null 2>&1
