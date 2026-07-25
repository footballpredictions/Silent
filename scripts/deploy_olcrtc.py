"""Деплой olcrtc srv на Улей (systemd, не Docker).

Пул комнат MVP: несколько yaml + template unit olcrtc@slot
  server.yaml          — legacy (= pc)
  server-pc.yaml       → olcrtc@pc
  server-android.yaml  → olcrtc@android

Читает YAML из update/olcrtc/ (после «Записать YAML» в админке).

Использование:
  cd backend
  python scripts/deploy_olcrtc.py

Опционально:
  OLCRTC_BIN=path/to/olcrtc   — локальный бинарь для загрузки
  OLCRTC_SKIP_BIN=1           — только yaml + restart (бинарь уже на сервере)
"""
from __future__ import annotations

import io
import os
import textwrap
from pathlib import Path

from _deploy_common import BACKEND_ROOT, REMOTE, connect, run

REMOTE_OLCRTC = "/opt/silent-vpn/olcrtc"
UNIT_LEGACY = "/etc/systemd/system/olcrtc.service"
UNIT_TEMPLATE = "/etc/systemd/system/olcrtc@.service"
LOCAL_DIR = BACKEND_ROOT / "update" / "olcrtc"


def _legacy_unit() -> str:
    return textwrap.dedent(
        f"""\
        [Unit]
        Description=Silent VPN olcrtc server (legacy single yaml)
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        WorkingDirectory={REMOTE_OLCRTC}
        ExecStart={REMOTE_OLCRTC}/olcrtc {REMOTE_OLCRTC}/server.yaml
        Restart=on-failure
        RestartSec=5
        LimitNOFILE=65535

        [Install]
        WantedBy=multi-user.target
        """
    )


def _template_unit() -> str:
    return textwrap.dedent(
        f"""\
        [Unit]
        Description=Silent VPN olcrtc srv (%i)
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        WorkingDirectory={REMOTE_OLCRTC}
        ExecStart={REMOTE_OLCRTC}/olcrtc {REMOTE_OLCRTC}/server-%i.yaml
        Restart=on-failure
        RestartSec=5
        LimitNOFILE=65535

        [Install]
        WantedBy=multi-user.target
        """
    )


def _local_yaml_files() -> list[Path]:
    if not LOCAL_DIR.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(LOCAL_DIR.glob("server*.yaml")):
        if p.is_file():
            out.append(p)
    return out


def main() -> None:
    client = connect()
    sftp = client.open_sftp()

    # data dirs for slot-provider units (pc-telemost, android-jitsi, …)
    run(
        client,
        f"mkdir -p {REMOTE_OLCRTC}/data {REMOTE_OLCRTC}/data-pc {REMOTE_OLCRTC}/data-android "
        f"{REMOTE_OLCRTC}/data-pc-jitsi {REMOTE_OLCRTC}/data-pc-wbstream {REMOTE_OLCRTC}/data-pc-telemost "
        f"{REMOTE_OLCRTC}/data-android-jitsi {REMOTE_OLCRTC}/data-android-wbstream "
        f"{REMOTE_OLCRTC}/data-android-telemost",
    )

    yaml_files = _local_yaml_files()
    uploaded_slots: list[str] = []
    if yaml_files:
        for lp in yaml_files:
            remote = f"{REMOTE_OLCRTC}/{lp.name}"
            sftp.put(str(lp), remote)
            print("upload", lp.name)
            if lp.name.startswith("server-") and lp.name.endswith(".yaml"):
                uploaded_slots.append(lp.name[len("server-") : -len(".yaml")])
            elif lp.name == "server.yaml":
                if not any(f.name == "server-pc-jitsi.yaml" for f in yaml_files):
                    sftp.put(str(lp), f"{REMOTE_OLCRTC}/server-pc-jitsi.yaml")
                    print("also → server-pc-jitsi.yaml (from server.yaml)")
                    if "pc-jitsi" not in uploaded_slots:
                        uploaded_slots.append("pc-jitsi")
    else:
        print("WARN: local", LOCAL_DIR, "has no server*.yaml — leave remote as-is")
        run(
            client,
            f"ls -la {REMOTE_OLCRTC}/server*.yaml 2>/dev/null || echo yaml_MISSING",
        )
        listing = run(client, f"ls {REMOTE_OLCRTC}/server-*.yaml 2>/dev/null || true")
        for line in listing.splitlines():
            name = Path(line.strip()).name
            if name.startswith("server-") and name.endswith(".yaml"):
                uploaded_slots.append(name[len("server-") : -len(".yaml")])

    # Binary
    skip_bin = os.environ.get("OLCRTC_SKIP_BIN", "").strip() in ("1", "true", "yes")
    bin_candidates = [
        Path(os.environ["OLCRTC_BIN"]) if os.environ.get("OLCRTC_BIN") else None,
        BACKEND_ROOT / "olcrtc" / "olcrtc",
        BACKEND_ROOT / "olcrtc" / "olcrtc-linux-amd64",
        BACKEND_ROOT.parent / "vendor" / "olcrtc" / "olcrtc",
    ]
    uploaded_bin = False
    if not skip_bin:
        for cand in bin_candidates:
            if cand and cand.is_file():
                remote_bin = f"{REMOTE_OLCRTC}/olcrtc"
                sftp.put(str(cand), remote_bin)
                run(client, f"chmod +x {remote_bin}")
                print("upload binary", cand)
                uploaded_bin = True
                break
        if not uploaded_bin:
            print(
                "WARN: olcrtc binary not found locally. "
                "Build from https://github.com/openlibrecommunity/olcrtc "
                "(mage build / mage cross) and place at backend/olcrtc/olcrtc "
                "or set OLCRTC_BIN=..."
            )
            run(client, f"test -x {REMOTE_OLCRTC}/olcrtc && echo bin_ok || echo bin_MISSING")

    # systemd: template + stop legacy single unit when pool is used
    sftp.putfo(io.BytesIO(_template_unit().encode()), "/tmp/olcrtc@.service")
    run(client, f"mv /tmp/olcrtc@.service {UNIT_TEMPLATE}")
    sftp.putfo(io.BytesIO(_legacy_unit().encode()), "/tmp/olcrtc.service")
    run(client, f"mv /tmp/olcrtc.service {UNIT_LEGACY}")
    run(client, "systemctl daemon-reload")

    slots = sorted(set(uploaded_slots)) or ["pc-jitsi"]
    # Prefer per-provider units; stop legacy single + old multi-profile pc/android
    if slots:
        run(client, "systemctl disable --now olcrtc.service 2>/dev/null || true")
        # Старые unit'ы с failover jitsi+wb+telemost в одном процессе — ломают telemost
        if any("-" in s and s.split("-")[-1] in ("jitsi", "wbstream", "telemost") for s in slots):
            for legacy in ("pc", "android"):
                if legacy not in slots:
                    run(
                        client,
                        f"systemctl disable --now olcrtc@{legacy}.service 2>/dev/null || true",
                    )
                    print(f"disabled legacy olcrtc@{legacy} (multi-provider failover)")
        for slot in slots:
            # не поднимать голые pc/android если есть pc-jitsi и т.п.
            if slot in ("pc", "android") and any(
                s.startswith(f"{slot}-") for s in slots if s != slot
            ):
                run(client, f"systemctl disable --now olcrtc@{slot}.service 2>/dev/null || true")
                print(f"skip legacy olcrtc@{slot} — используем {slot}-*")
                continue
            check = run(
                client,
                f"test -f {REMOTE_OLCRTC}/server-{slot}.yaml && test -x {REMOTE_OLCRTC}/olcrtc "
                f"&& echo READY_{slot} || echo NOT_{slot}",
            )
            if f"READY_{slot}" in check:
                run(client, f"systemctl enable olcrtc@{slot}.service")
                run(client, f"systemctl restart olcrtc@{slot}.service")
                run(
                    client,
                    f"sleep 1; systemctl --no-pager -l status olcrtc@{slot}.service | head -n 15",
                )
            else:
                print(f"Skip olcrtc@{slot} — нет server-{slot}.yaml или бинаря")
    else:
        run(client, "systemctl enable olcrtc.service")
        check = run(
            client,
            f"test -f {REMOTE_OLCRTC}/server.yaml && test -x {REMOTE_OLCRTC}/olcrtc && echo READY || echo NOT_READY",
        )
        if "READY" in check:
            run(client, "systemctl restart olcrtc.service")
            run(client, "sleep 2; systemctl --no-pager -l status olcrtc.service | head -n 20")

    # sync API code for olcrtc endpoints (docker cp)
    api_files = [
        "app/services/olcrtc_settings.py",
        "app/services/olcrtc_room_accounts.py",
        "app/api/admin.py",
        "app/api/vpn.py",
        "app/main.py",
        "ai/olcrtc_room_agent.py",
        "ai/olcrtc_room_provision.py",
    ]
    for rel in api_files:
        lp = BACKEND_ROOT / rel.replace("/", os.sep)
        if not lp.is_file():
            continue
        rp = f"{REMOTE}/{rel.replace(chr(92), '/')}"
        run(client, f"mkdir -p {os.path.dirname(rp)}")
        sftp.put(str(lp), rp)
        print("upload", rel)

    dist = BACKEND_ROOT / "admin-ui" / "dist"
    if dist.is_dir():
        rdist = f"{REMOTE}/admin-ui/dist"
        run(client, f"mkdir -p {rdist}/assets")
        for root, _, names in os.walk(dist):
            for name in names:
                lp = Path(root) / name
                rel = lp.relative_to(dist).as_posix()
                rp = f"{rdist}/{rel}"
                run(client, f"mkdir -p {os.path.dirname(rp)}")
                sftp.put(str(lp), rp)
                print("ui", rel)
    else:
        print("WARN: admin-ui/dist missing — npm run build в admin-ui")

    sftp.close()

    slots_q = " ".join(slots)
    script = f"""#!/bin/bash
set -e
cd {REMOTE}
CONTAINER=${{DEPLOY_CONTAINER:-backend-api-1}}
for f in app/services/olcrtc_settings.py app/services/olcrtc_room_accounts.py \\
  app/api/admin.py app/api/vpn.py app/main.py \\
  ai/olcrtc_room_agent.py ai/olcrtc_room_provision.py; do
  [ -f "$f" ] && docker cp "$f" "$CONTAINER:/app/$f"
done
# yaml из контейнера (после admin apply) → хост, если локально не заливали свежие
if [ -d /app/update/olcrtc ] 2>/dev/null; then true; fi
docker exec "$CONTAINER" sh -c 'ls /app/update/olcrtc/server*.yaml 2>/dev/null' || true
for y in $(docker exec "$CONTAINER" sh -c 'ls /app/update/olcrtc/server*.yaml 2>/dev/null' || true); do
  bn=$(basename "$y")
  docker cp "$CONTAINER:$y" "{REMOTE_OLCRTC}/$bn" || true
  echo "sync $bn from container"
done
# если из контейнера пришёл только server.yaml — продублировать в pc
if [ -f {REMOTE_OLCRTC}/server.yaml ] && [ ! -f {REMOTE_OLCRTC}/server-pc.yaml ]; then
  cp {REMOTE_OLCRTC}/server.yaml {REMOTE_OLCRTC}/server-pc.yaml
fi
docker compose restart api
sleep 12
echo "=== olcrtc-config pc ==="
curl -s "http://127.0.0.1:8000/api/vpn/olcrtc-config?device_type=pc" | head -c 400; echo
echo "=== olcrtc-config android ==="
curl -s "http://127.0.0.1:8000/api/vpn/olcrtc-config?device_type=android" | head -c 400; echo
for s in {slots_q}; do
  systemctl is-active "olcrtc@$s.service" || true
done
systemctl is-active olcrtc.service 2>/dev/null || true
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_olcrtc_api.sh")
    sftp2.close()
    run(client, "bash /tmp/deploy_olcrtc_api.sh 2>&1", timeout=180)
    client.close()
    print("Done — pool units:", ", ".join(f"olcrtc@{s}" for s in slots))


if __name__ == "__main__":
    main()
