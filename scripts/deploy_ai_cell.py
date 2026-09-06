"""AI-выход на соте: аудит и настройка (гигиена egress, свой DNS, TPROXY-прокси).

Работает только с одной сотой — той, у которой в Улье стоит флаг `ai_exit`
(сейчас это «Сота 3» / server4). Остальные соты и Улей не затрагиваются.

Пароль root от соты нигде не хранится локально: скрипт заходит на Улей,
запускает раннер внутри API-контейнера, а тот берёт зашифрованный пароль из БД
(тот же путь, что у provision/upgrade cell-agent) и идёт по SSH на соту.

Примеры (из папки backend):
    python scripts/deploy_ai_cell.py audit
    python scripts/deploy_ai_cell.py hygiene
    python scripts/deploy_ai_cell.py dns
    python scripts/deploy_ai_cell.py proxy            # Ф3, цепочки нет
    python scripts/deploy_ai_cell.py proxy --chain socks5://user:pass@host:1080   # Ф4
    python scripts/deploy_ai_cell.py proxy --off      # выключить прокси (fail-open)
    python scripts/deploy_ai_cell.py status
    python scripts/deploy_ai_cell.py rollback --scope proxy|dns|all
    python scripts/deploy_ai_cell.py harden --host 1.2.3.4   # базовая гигиена любой соты
    python scripts/deploy_ai_cell.py harden --all            # то же для всех сот

Инварианты: wdtt не рестартим, порты 56000/56001 не трогаем,
цепочка TPROXY живёт только пока watchdog видит здоровый sing-box.
"""
from __future__ import annotations

import argparse
import io
import json
import sys

from _deploy_common import BACKEND_ROOT, CONTAINER, connect, load_env, run

MODULE_SRC = (BACKEND_ROOT / "app" / "services" / "ai_exit_node.py").read_text(encoding="utf-8")
HARDEN_SRC = (BACKEND_ROOT / "app" / "services" / "cell_hardening.py").read_text(encoding="utf-8")

RUNNER_REMOTE = "/tmp/silent_ai_cell_runner.py"
ARGS_REMOTE = "/tmp/silent_ai_cell_args.json"
MODULE_REMOTE = "/tmp/silent_ai_exit_node.py"
HARDEN_REMOTE = "/tmp/silent_cell_hardening.py"

RUNNER_PY = r'''"""Раннер AI-выхода. Запускается ВНУТРИ api-контейнера Улья."""
import asyncio
import importlib.util
import json
import sys

sys.path.insert(0, "/app")  # раннер лежит в /tmp, пакет app — в рабочей папке контейнера

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import HiveCell
from app.services import hive_service
from app.services.threat_filter_settings import is_threat_filter_enabled

# Модуль берём из свежезалитой копии, а не из образа: правки фаз не требуют
# полного деплоя backend и рестарта API.
_spec = importlib.util.spec_from_file_location("ai_exit_node_local", "/tmp/silent_ai_exit_node.py")
ai_exit_node = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ai_exit_node)

_spec_h = importlib.util.spec_from_file_location("cell_hardening_local", "/tmp/silent_cell_hardening.py")
cell_hardening = importlib.util.module_from_spec(_spec_h)
_spec_h.loader.exec_module(cell_hardening)


async def _load_worker_cells():
    """Все соты (кроме Улья) с сохранённым SSH-паролем — для harden --all."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(HiveCell))).scalars().all()
        out = []
        for c in rows:
            if c.is_queen:
                continue
            pwd = hive_service.resolve_ssh_password(c)
            if not pwd:
                print(f"[runner] пропускаю {c.name}: нет сохранённого SSH-пароля")
                continue
            out.append({"name": c.name, "ip": (c.public_ip or "").strip(), "password": pwd})
        if not out:
            raise SystemExit("Нет сот с сохранённым SSH-паролем.")
        return out


async def _load(args):
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(HiveCell))).scalars().all()
        queen = next((c for c in rows if c.is_queen), None)
        target = None
        want_ip = (args.get("host") or "").strip()
        if want_ip:
            target = next((c for c in rows if (c.public_ip or "").strip() == want_ip), None)
        else:
            ai_cells = [c for c in rows if not c.is_queen and getattr(c, "ai_exit", False)]
            if len(ai_cells) > 1:
                raise SystemExit(
                    "Флаг ai_exit стоит у нескольких сот: "
                    + ", ".join(f"{c.name} ({c.public_ip})" for c in ai_cells)
                    + ". Укажите --host явно."
                )
            target = ai_cells[0] if ai_cells else None
        if target is None:
            raise SystemExit("Не нашёл соту с флагом ai_exit. Включите его в Улье или задайте --host.")
        if target.is_queen:
            raise SystemExit("Это Улей — на нём AI-выход не настраиваем.")
        if not getattr(target, "ai_exit", False) and not args.get("force"):
            raise SystemExit(
                f"У соты {target.name} ({target.public_ip}) нет флага ai_exit. "
                "Включите его в админке или добавьте --force."
            )
        pwd = hive_service.resolve_ssh_password(target)
        if not pwd:
            raise SystemExit(f"У соты {target.name} не сохранён SSH-пароль — переподключите её в Улье.")
        tf = await is_threat_filter_enabled(db)
        return {
            "name": target.name,
            "ip": (target.public_ip or "").strip(),
            "api_url": target.api_url or "",
            "api_secret_enc": target.api_secret_enc or "",
            "admin_only": bool(getattr(target, "admin_only", False)),
            "queen_ip": (queen.public_ip or "").strip() if queen else "",
            "password": pwd,
            "threat_filter": tf,
        }


def main():
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        args = json.load(fh)
    phase = args["phase"]
    kwargs = dict(args.get("kwargs") or {})
    timeout = int(args.get("timeout") or 900)

    if phase == "harden":
        # Гигиена не требует ai_exit: она нужна любой соте.
        script = cell_hardening.harden_script(**kwargs)
        if args.get("all_cells"):
            targets = asyncio.run(_load_worker_cells())
        else:
            args = dict(args, force=True)
            one = asyncio.run(_load(args))
            targets = [{"name": one["name"], "ip": one["ip"], "password": one["password"]}]
        failed = []
        for t in targets:
            print(f"[runner] harden: {t['name']} ({t['ip']})")
            code, out = ai_exit_node.run_on_cell(t["ip"], t["password"], script, timeout=timeout)
            print(out)
            if code != 0 or "=== done ===" not in out:
                failed.append(t["name"])
        if failed:
            print(f"[runner] НЕ ЗАВЕРШЕНО на: {', '.join(failed)}")
            sys.exit(2)
        print("[runner] ok")
        return

    info = asyncio.run(_load(args))

    if phase in ("hygiene",):
        if not info["queen_ip"]:
            raise SystemExit("Не нашёл публичный IP Улья — без него закрывать cell-agent нельзя.")
        kwargs.setdefault("queen_ip", info["queen_ip"])
    if phase == "dns":
        kwargs.setdefault("threat_filter_enabled", info["threat_filter"])

    print(f"[runner] сота: {info['name']} ({info['ip']}), admin_only={info['admin_only']}, фаза={phase}")
    if phase == "agent":
        from app.services.hive_provision_service import upgrade_cell_agent_via_ssh

        upgrade_cell_agent_via_ssh(info["ip"], info["password"])
        print("=== done ===")
        print("[runner] ok")
        return

    if phase == "egress":
        # Тот же путь, что у кнопки «Проверить выход» в Улье.
        from types import SimpleNamespace

        cell = SimpleNamespace(api_url=info["api_url"], api_secret_enc=info["api_secret_enc"])
        data = asyncio.run(ai_exit_node.fetch_cell_egress(cell))
        print(json.dumps(data, ensure_ascii=False, indent=2))
        print("=== done ===")
        print("[runner] ok")
        return
    if phase == "dns":
        print(f"[runner] фильтр угроз в админке: {'вкл' if info['threat_filter'] else 'выкл'}")
    script = ai_exit_node.build_phase_script(phase, **kwargs)
    code, out = ai_exit_node.run_on_cell(
        info["ip"], info["password"], script, timeout=int(args.get("timeout") or 900)
    )
    print(out)
    if code != 0 or "=== done ===" not in out:
        print(f"[runner] ФАЗА НЕ ЗАВЕРШЕНА, exit={code}")
        sys.exit(2)
    print("[runner] ok")


main()
'''


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI-выход на соте (только сота с флагом ai_exit)")
    p.add_argument(
        "phase",
        choices=[
            "audit", "hygiene", "dns", "proxy", "verify", "status",
            "rollback", "agent", "egress", "harden",
        ],
        help=(
            "agent — обновить cell-agent на соте; egress — чистота выхода (как кнопка в Улье); "
            "harden — базовая гигиена любой соты (ufw, TTL 64, IPv6 off)"
        ),
    )
    p.add_argument("--host", default="", help="IP соты, если ai_exit стоит у нескольких")
    p.add_argument("--force", action="store_true", help="разрешить соту без флага ai_exit")
    p.add_argument("--all", action="store_true", help="harden: применить ко всем сотам")
    p.add_argument("--timeout", type=int, default=900)
    # hygiene
    p.add_argument("--ipv6", choices=["off", "keep"], default="off")
    p.add_argument("--ssh-allow", default="", help="IP через запятую: сузить SSH (по умолчанию не трогаем)")
    p.add_argument("--agent-port", type=int, default=9100)
    # proxy
    p.add_argument("--chain", default="", help="Ф4: socks5://user:pass@host:port для ИИ-доменов")
    p.add_argument("--singbox-version", default="")
    p.add_argument("--off", action="store_true", help="proxy: поставить, но оставить выключенным")
    # rollback
    p.add_argument("--scope", choices=["proxy", "dns", "all"], default="all")
    return p.parse_args()


def phase_kwargs(a: argparse.Namespace) -> dict:
    if a.phase == "hygiene":
        allow = [x.strip() for x in a.ssh_allow.split(",") if x.strip()]
        return {"agent_port": a.agent_port, "ipv6_mode": a.ipv6, "ssh_allow": allow}
    if a.phase == "proxy":
        kw: dict = {"enable": not a.off}
        if a.chain.strip():
            kw["chain_url"] = a.chain.strip()
        if a.singbox_version.strip():
            kw["singbox_version"] = a.singbox_version.strip()
        return kw
    if a.phase == "harden":
        return {"agent_port": a.agent_port, "ipv6_mode": a.ipv6}
    if a.phase == "status":
        return {"agent_port": a.agent_port}
    if a.phase == "rollback":
        return {"scope": a.scope, "agent_port": a.agent_port}
    return {}


def main() -> None:
    a = parse_args()
    load_env()
    payload = {
        "phase": a.phase,
        "host": a.host.strip(),
        "force": bool(a.force),
        "all_cells": bool(a.all),
        "timeout": int(a.timeout),
        "kwargs": phase_kwargs(a),
    }

    client = connect()
    try:
        sftp = client.open_sftp()
        sftp.putfo(io.BytesIO(RUNNER_PY.encode("utf-8")), RUNNER_REMOTE)
        sftp.putfo(io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")), ARGS_REMOTE)
        sftp.putfo(io.BytesIO(MODULE_SRC.encode("utf-8")), MODULE_REMOTE)
        sftp.putfo(io.BytesIO(HARDEN_SRC.encode("utf-8")), HARDEN_REMOTE)
        sftp.close()
        run(client, f"docker cp {RUNNER_REMOTE} {CONTAINER}:{RUNNER_REMOTE}", timeout=60)
        run(client, f"docker cp {ARGS_REMOTE} {CONTAINER}:{ARGS_REMOTE}", timeout=60)
        run(client, f"docker cp {MODULE_REMOTE} {CONTAINER}:{MODULE_REMOTE}", timeout=60)
        run(client, f"docker cp {HARDEN_REMOTE} {CONTAINER}:{HARDEN_REMOTE}", timeout=60)
        out = run(
            client,
            f"docker exec -w /app {CONTAINER} python {RUNNER_REMOTE} {ARGS_REMOTE} 2>&1; "
            f"docker exec {CONTAINER} rm -f {ARGS_REMOTE} {RUNNER_REMOTE} {MODULE_REMOTE} {HARDEN_REMOTE} >/dev/null 2>&1; "
            f"rm -f {ARGS_REMOTE} {RUNNER_REMOTE} {MODULE_REMOTE} {HARDEN_REMOTE}",
            timeout=a.timeout + 120,
        )
    finally:
        client.close()

    if "[runner] ok" not in out:
        print("\nФаза завершилась с ошибкой — смотрите вывод выше.")
        sys.exit(2)
    print("\nГотово.")


if __name__ == "__main__":
    main()
