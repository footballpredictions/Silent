"""Только чтение OneDash: health/auth/balance/VPS. Без POST и без печати ключа.

Запуск из backend: python scripts/onedash_inventory.py
Ключ: ONEDASH_API_KEY в Silent-Project/.env.deploy
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.onedash_client import (  # noqa: E402
    CHANGE_IP_GET_PROBES,
    HOSTER_ID,
    OneDashClient,
    load_key_from_env_file,
)
from ai.ip_rotate_policy import KNOWN_HOSTER_BY_IP, hoster_for_ip  # noqa: E402

KNOWN_NODES = {
    "89.125.188.100": "Улей",
    "87.58.213.193": "Сота 1",
    "78.17.74.27": "Сота 2",
    "192.177.26.38": "Сота 3 HOSTKEY",
}


def _load_secrets() -> None:
    load_key_from_env_file(str(ROOT / ".env.deploy"))
    load_key_from_env_file(str(ROOT.parent / ".env.deploy"))


def main() -> int:
    _load_secrets()
    if not (os.environ.get("ONEDASH_API_KEY") or "").strip():
        print("ONEDASH_API_KEY не задан")
        return 2
    client = OneDashClient()
    inv = client.inventory()
    summary = inv.to_dict()
    # Не печатаем сырой JSON аккаунта целиком — только рабочие поля.
    out = {
        "hoster": HOSTER_ID,
        "ok": summary["ok"],
        "reason": summary["reason"],
        "auth_ok": summary["auth_ok"],
        "health_ok": summary["health_ok"],
        "balance_known": summary["balance_known"],
        "currency": summary["currency"],
        "http_status": summary["http_status"],
        "vps_count": len(inv.items),
        "mapped": [],
        "unmapped_known_ips": [],
        "change_ip_probes": {},
    }
    for ip, name in KNOWN_NODES.items():
        item = inv.find_by_ip(ip)
        row = {
            "name": name,
            "ip": ip,
            "policy_hoster": hoster_for_ip(ip) or KNOWN_HOSTER_BY_IP.get(ip, ""),
            "in_onedash": item is not None,
        }
        if item:
            row["vps_id"] = item.vps_id
            row["vps_name"] = item.name
            row["active"] = item.active
            row["static_ip"] = item.static_ip
            row["location"] = item.location
            if item:
                out["change_ip_probes"][ip] = client.probe_change_ip_paths(item.vps_id)
        else:
            out["unmapped_known_ips"].append({"name": name, "ip": ip})
        out["mapped"].append(row)
    extra = [item.to_dict() for item in inv.items if item.ip not in KNOWN_NODES]
    out["other_vps"] = [{"vps_id": x["vps_id"], "name": x["name"], "ip": x["ip"], "active": x["active"]} for x in extra]
    out["change_ip_probe_templates"] = list(CHANGE_IP_GET_PROBES)
    out["note"] = (
        "POST смены IP не вызывался. В API 2.0 метода нет. "
        "405 на GET может значить, что POST существует — без явного "
        "ONEDASH_CHANGE_IP_PATH и paid_enabled всё равно не зовём."
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if inv.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
