"""Игровой выход на соте: аудит Steam SDR (UDP) и UDP/MTU-тюнинг.

По аналогии с deploy_ai_cell.py: пароль соты из БД Улья, раннер в api-контейнере,
локально секреты не храним. Целевая сота — явно через --host (обычно Сота 2).

Примеры (из папки backend):
    python scripts/deploy_game_cell.py audit --host 78.17.74.27
    python scripts/deploy_game_cell.py probe --host 78.17.74.27
    python scripts/deploy_game_cell.py udp-tune --host 78.17.74.27
    python scripts/deploy_game_cell.py status --host 78.17.74.27
    python scripts/deploy_game_cell.py rollback --host 78.17.74.27

Инварианты: wdtt не рестартим, 56000/56001 не трогаем.
"""
from __future__ import annotations

import argparse
import io
import json
import sys

from _deploy_common import BACKEND_ROOT, CONTAINER, connect, load_env, run

MODULE_SRC = (BACKEND_ROOT / "app" / "services" / "game_exit_node.py").read_text(encoding="utf-8")

RUNNER_REMOTE = "/tmp/silent_game_cell_runner.py"
ARGS_REMOTE = "/tmp/silent_game_cell_args.json"
MODULE_REMOTE = "/tmp/silent_game_exit_node.py"

RUNNER_PY = r'''"""Раннер game-exit. Запускается ВНУТРИ api-контейнера Улья."""
import asyncio
import importlib.util
import json
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import HiveCell
from app.services import hive_service

_spec = importlib.util.spec_from_file_location("game_exit_node_local", "/tmp/silent_game_exit_node.py")
game_exit_node = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(game_exit_node)


async def _load(args):
    want_ip = (args.get("host") or "").strip()
    if not want_ip:
        raise SystemExit("Укажите --host IP соты (например Сота 2).")
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(HiveCell))).scalars().all()
        target = next((c for c in rows if (c.public_ip or "").strip() == want_ip), None)
        if target is None:
            raise SystemExit(f"Сота с IP {want_ip} не найдена в Улье.")
        if target.is_queen:
            raise SystemExit("Это Улей — игровой профиль только на соте.")
        pwd = hive_service.resolve_ssh_password(target)
        if not pwd:
            raise SystemExit(f"У соты {target.name} не сохранён SSH-пароль — переподключите её в Улье.")
        return {
            "name": target.name,
            "ip": (target.public_ip or "").strip(),
            "admin_only": bool(getattr(target, "admin_only", False)),
            "ai_exit": bool(getattr(target, "ai_exit", False)),
            "password": pwd,
        }


def main():
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        args = json.load(fh)
    phase = args["phase"]
    kwargs = dict(args.get("kwargs") or {})
    timeout = int(args.get("timeout") or 600)
    info = asyncio.run(_load(args))
    print(
        f"[runner] сота: {info['name']} ({info['ip']}), "
        f"admin_only={info['admin_only']}, ai_exit={info['ai_exit']}, фаза={phase}"
    )
    if info["ai_exit"] and phase == "udp-tune":
        print("[runner] ВНИМАНИЕ: на соте стоит ai_exit — тюнинг игр может пересечься с AI-правилами.")
    script = game_exit_node.build_phase_script(phase, **kwargs)
    code, out = game_exit_node.run_on_cell(info["ip"], info["password"], script, timeout=timeout)
    print(out)
    if code != 0 or "=== done ===" not in out:
        print(f"[runner] ФАЗА НЕ ЗАВЕРШЕНА, exit={code}")
        sys.exit(2)
    print("[runner] ok")


main()
'''


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Игровой UDP/MTU профиль на соте")
    p.add_argument(
        "phase",
        choices=["audit", "probe", "udp-tune", "status", "rollback"],
        help="audit/probe — только чтение; udp-tune — безопасные правила; rollback — снять",
    )
    p.add_argument("--host", required=True, help="Публичный IP соты (Сота 2 = 78.17.74.27)")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--relays", type=int, default=12, help="Сколько SDR-релеев пробовать в probe")
    return p.parse_args()


def phase_kwargs(a: argparse.Namespace) -> dict:
    if a.phase == "probe":
        return {"relay_limit": int(a.relays)}
    return {}


def main() -> None:
    a = parse_args()
    load_env()
    payload = {
        "phase": a.phase,
        "host": a.host.strip(),
        "timeout": int(a.timeout),
        "kwargs": phase_kwargs(a),
    }

    client = connect()
    try:
        sftp = client.open_sftp()
        sftp.putfo(io.BytesIO(RUNNER_PY.encode("utf-8")), RUNNER_REMOTE)
        sftp.putfo(io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")), ARGS_REMOTE)
        sftp.putfo(io.BytesIO(MODULE_SRC.encode("utf-8")), MODULE_REMOTE)
        sftp.close()
        run(client, f"docker cp {RUNNER_REMOTE} {CONTAINER}:{RUNNER_REMOTE}", timeout=60)
        run(client, f"docker cp {ARGS_REMOTE} {CONTAINER}:{ARGS_REMOTE}", timeout=60)
        run(client, f"docker cp {MODULE_REMOTE} {CONTAINER}:{MODULE_REMOTE}", timeout=60)
        out = run(
            client,
            f"docker exec -w /app {CONTAINER} python {RUNNER_REMOTE} {ARGS_REMOTE} 2>&1; "
            f"docker exec {CONTAINER} rm -f {ARGS_REMOTE} {RUNNER_REMOTE} {MODULE_REMOTE} >/dev/null 2>&1; "
            f"rm -f {ARGS_REMOTE} {RUNNER_REMOTE} {MODULE_REMOTE}",
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
