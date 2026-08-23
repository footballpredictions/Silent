"""Отчёт агента доступности из консоли — когда админка недоступна.

Запуск на VPS по SSH (модуль лежит внутри контейнера API):

    docker exec backend-api-1 python -m ai.availability_cli            # последний отчёт
    docker exec backend-api-1 python -m ai.availability_cli --run      # проверить сейчас
    docker exec backend-api-1 python -m ai.availability_cli --history 20
    docker exec backend-api-1 python -m ai.availability_cli --clients
    docker exec backend-api-1 python -m ai.availability_cli --knowledge
    docker exec backend-api-1 python -m ai.availability_cli --json     # машинный вывод

Ничего не меняет на сервере: только читает БД и (с `--run`) делает сетевые пробы.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

SEV_MARK = {"critical": "[КРИТ]", "error": "[БЛОК]", "warning": "[ВНИМ]", "info": "[ OK ]"}
STATUS_TEXT = {
    "ok": "Всё доступно",
    "degraded": "Работает с деградацией",
    "blocked": "Есть блокировка",
    "down": "Сервис не отвечает",
    "unknown": "Недостаточно данных",
}


def _line(char: str = "-", width: int = 78) -> str:
    return char * width


def _print_verdict(index: int, verdict: dict[str, Any]) -> None:
    mark = SEV_MARK.get(str(verdict.get("severity")), "[ ?? ]")
    print(
        f"{index}. {mark} {verdict.get('target')} ({verdict.get('host')}) — "
        f"{verdict.get('title')}  [уверенность {verdict.get('confidence')}]"
    )
    print(f"   Что происходит: {verdict.get('summary')}")
    for ev in verdict.get("evidence") or []:
        print(f"   · {ev}")
    fixes = verdict.get("fixes") or []
    if fixes:
        print("   Решение:")
        for fix in fixes:
            print(f"     - {fix}")
    commands = verdict.get("commands") or []
    if commands:
        print("   Команды для проверки/фикса:")
        for cmd in commands:
            print(f"     $ {cmd}")
    print()


def _print_report(report: dict[str, Any] | None) -> None:
    if not report:
        print("Отчётов пока нет. Запустите проверку: --run")
        return
    status = str(report.get("status") or "unknown")
    print(_line("="))
    print(f"ДОСТУПНОСТЬ SILENT VPN — {STATUS_TEXT.get(status, status).upper()}")
    print(f"Время отчёта: {report.get('ts')}   (проверка заняла {report.get('duration_sec')} с)")
    print(f"Итог: {report.get('summary')}")
    print(_line("="))

    vantage = report.get("vantage") or {}
    ru_nodes = vantage.get("ru_nodes") or []
    world_nodes = vantage.get("world_nodes") or []
    print(
        f"Точки наблюдения: РФ — {len(ru_nodes)} ({', '.join(ru_nodes) or 'нет'}); "
        f"контроль вне РФ — {len(world_nodes)}; внешних проверок за цикл: {vantage.get('checks', 0)}"
    )
    for warn in report.get("warnings") or []:
        print(f"ВНИМАНИЕ: {warn}")
    print()

    verdicts = report.get("verdicts") or []
    problems = [v for v in verdicts if v.get("kind") != "ok"]
    if not problems:
        print("Проблем не найдено — все проверенные узлы видны из РФ.")
    else:
        print(f"НАЙДЕНО ПРОБЛЕМ: {len(problems)}")
        print(_line())
        for i, verdict in enumerate(problems, 1):
            _print_verdict(i, verdict)

    print(_line())
    print("УЗЛЫ И КАНАЛЫ")
    for target in report.get("targets") or []:
        print(
            f"  {target.get('name')} ({target.get('host')}) — статус {target.get('status') or '?'}, "
            f"онлайн {target.get('online_count', 0)}"
        )
        for channel, probe in (target.get("local") or {}).items():
            state = "ok" if probe.get("ok") else f"FAIL {probe.get('error_kind')}"
            extra = " (не показательно)" if probe.get("inconclusive") else ""
            print(f"      локально  {channel:<14} {state}{extra}")
        for channel, agg in (target.get("ru") or {}).items():
            rtt = agg.get("median_latency_ms")
            rtt_text = f"{float(rtt):.0f} мс" if rtt is not None else "—"
            print(
                f"      из РФ     {channel:<14} {agg.get('ok')}/{agg.get('total')} нод ok"
                f"  RTT {rtt_text}  ошибки: {agg.get('error_kinds') or '-'}"
            )
        for channel, probe in (target.get("peer") or {}).items():
            state = "ok" if probe.get("ok") else f"FAIL {probe.get('error_kind')}"
            print(f"      с соты    {channel:<14} {state}")
        clients = target.get("clients")
        if clients:
            print(
                f"      клиенты   отказов {clients.get('failures')} за "
                f"{clients.get('window_minutes')} мин; стадии {clients.get('by_stage')}; "
                f"сети {clients.get('by_network')}"
            )
    print(_line("="))


async def _cmd_latest(as_json: bool) -> int:
    from app.services.availability_store import load_latest_report

    report = await load_latest_report()
    if as_json:
        print(json.dumps(report or {}, ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    return 0 if report else 1


async def _cmd_run(as_json: bool) -> int:
    from ai.availability_agent import run_availability_check

    print("Запускаю проверку доступности (пробы только читают)...", file=sys.stderr)
    report = await run_availability_check(incidents=False)
    data = report.to_dict()
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_report(data)
    return 0 if data.get("status") == "ok" else 2


async def _cmd_history(limit: int, as_json: bool) -> int:
    from app.services.availability_store import load_history

    items = await load_history(limit)
    if as_json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    if not items:
        print("История пуста.")
        return 1
    print(f"{'ВРЕМЯ':<28} {'СТАТУС':<10} ИТОГ")
    for item in items:
        print(f"{str(item.get('ts')):<28} {str(item.get('status')):<10} {item.get('summary')}")
    return 0


async def _cmd_clients(window: int, as_json: bool) -> int:
    from app.services.availability_store import aggregate_client_reports

    buckets = await aggregate_client_reports(window)
    if as_json:
        print(json.dumps(buckets, ensure_ascii=False, indent=2))
        return 0
    if not buckets:
        print(f"Клиентских репортов за последние {window} мин нет.")
        return 1
    for slot, data in sorted(buckets.items()):
        title = "все узлы" if slot == "*" else slot
        print(f"[{title}] отказов {data.get('failures')} за {data.get('window_minutes')} мин")
        print(f"   стадии:    {data.get('by_stage')}")
        print(f"   транспорт: {data.get('by_transport')}")
        print(f"   сети:      {data.get('by_network')}")
        print(f"   операторы: {data.get('by_carrier')}")
        print(f"   короткоживущих туннелей: {data.get('short_lived_tunnels')}")
        print()
    return 0


def _cmd_knowledge(as_json: bool) -> int:
    from ai.availability_knowledge import knowledge_to_dict

    items = knowledge_to_dict()
    if as_json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    for item in items:
        print(_line("="))
        print(f"{item['title']}  [{item['kind']}, {item['severity']}]")
        print(_line())
        print(item["how_it_works"])
        print("\nПризнаки:")
        for s in item["signals"]:
            print(f"  · {s}")
        print("\nРешение:")
        for f in item["fixes"]:
            print(f"  - {f}")
        if item["commands"]:
            print("\nКоманды:")
            for c in item["commands"]:
                print(f"  $ {c}")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="availability_cli",
        description="Отчёт агента доступности Silent VPN (детекция блокировок DPI/ТСПУ)",
    )
    parser.add_argument("--run", action="store_true", help="выполнить проверку прямо сейчас")
    parser.add_argument("--history", type=int, metavar="N", help="последние N отчётов (только итоги)")
    parser.add_argument("--clients", action="store_true", help="сводка клиентских репортов")
    parser.add_argument(
        "--window", type=int, default=60, metavar="MIN", help="окно для --clients, минут (по умолчанию 60)"
    )
    parser.add_argument("--knowledge", action="store_true", help="справочник методов блокировок и решений")
    parser.add_argument("--json", action="store_true", help="вывод в JSON")
    args = parser.parse_args(argv)

    if args.knowledge:
        return _cmd_knowledge(args.json)
    if args.history:
        return asyncio.run(_cmd_history(args.history, args.json))
    if args.clients:
        return asyncio.run(_cmd_clients(args.window, args.json))
    if args.run:
        return asyncio.run(_cmd_run(args.json))
    return asyncio.run(_cmd_latest(args.json))


if __name__ == "__main__":
    raise SystemExit(main())
