#!/bin/sh
export PATH=/opt/sbin:/opt/bin:/usr/sbin:/usr/bin:/sbin:/bin
ROOT=/opt/lib/silent-keenetic
PID=/opt/var/run/silent-keenetic/agent.pid
child=''
stopping=0
finish() {
    stopping=1
    if [ -n "$child" ]; then kill "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
    "$ROOT/silent-keenetic" --cleanup >/dev/null 2>&1
    rm -f /opt/etc/silent-keenetic/web.ready
    rm -f "$PID"
    exit 0
}
trap finish TERM INT HUP
while [ "$stopping" = 0 ]; do
    "$ROOT/silent-keenetic" &
    child=$!
    wait "$child"
    child=''
    rm -f /opt/etc/silent-keenetic/web.ready
    "$ROOT/silent-keenetic" --cleanup >/dev/null 2>&1
    sleep 5
done
