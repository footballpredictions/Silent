"""Unit tests: классификатор блокировок агента доступности (без сети и БД)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from ai.availability_classifier import (  # noqa: E402
    classify_target,
    classify_targets,
    plan_incidents,
    report_status,
    report_summary,
)
from ai.availability_knowledge import (  # noqa: E402
    KIND_ASN_PARTIAL,
    KIND_DNS_POISONING,
    KIND_HTTP_STUB,
    KIND_IP_BLACKHOLE,
    KIND_MOBILE_SHUTDOWN,
    KIND_NO_VANTAGE,
    KIND_OK,
    KIND_PORT_BLOCK,
    KIND_PROTOCOL_FINGERPRINT,
    KIND_RST_INJECTION,
    KIND_SERVICE_DOWN,
    KIND_SNI_BLOCK,
    KIND_THROTTLING,
    KIND_UDP_BLOCK,
    all_methods,
    knowledge_to_dict,
    render_commands,
)
from ai.availability_model import (  # noqa: E402
    client_report_age_sec,
    CHANNEL_AGENT_TCP,
    CHANNEL_API_HTTP,
    CHANNEL_API_TCP,
    CHANNEL_API_TLS,
    CHANNEL_DNS,
    CHANNEL_PING,
    CHANNEL_TLS_NO_SNI,
    CHANNEL_WDTT_UDP,
    ERR_HTTP,
    ERR_RESET,
    ERR_TIMEOUT,
    ClientSignals,
    NodeResult,
    ProbeResult,
    TARGET_QUEEN,
    TargetSnapshot,
    VantageAggregate,
)
from ai.availability_probes import _parse_node_payload  # noqa: E402


def _agg(channel: str, *, ok: int = 0, failed: int = 0, error: str = ERR_TIMEOUT,
         latency: float | None = 40.0, source: str = "ru-external",
         asns: list[str] | None = None, ips: tuple[str, ...] = ()) -> VantageAggregate:
    agg = VantageAggregate(channel=channel, source=source)
    for i in range(ok):
        agg.nodes.append(
            NodeResult(
                node=f"ru{i + 1}.node",
                country="ru",
                asn=(asns[i] if asns and i < len(asns) else "AS200000"),
                ok=True,
                latency_ms=latency,
                resolved_ips=ips,
            )
        )
    for i in range(failed):
        agg.nodes.append(
            NodeResult(
                node=f"ru{ok + i + 1}.node",
                country="ru",
                asn=(asns[ok + i] if asns and (ok + i) < len(asns) else "AS8359"),
                ok=False,
                error_kind=error,
                detail=error,
            )
        )
    return agg


def _queen(**kw) -> TargetSnapshot:
    snap = TargetSnapshot(
        name="Улей",
        host="132.243.234.162",
        role=TARGET_QUEEN,
        api_port=443,
        wdtt_port=56000,
        wg_port=56001,
        domain="132-243-234-162.nip.io",
        note="server1",
        status="active",
    )
    snap.local[CHANNEL_API_TCP] = ProbeResult(channel=CHANNEL_API_TCP, ok=True, latency_ms=3.0)
    snap.local[CHANNEL_API_TLS] = ProbeResult(channel=CHANNEL_API_TLS, ok=True, latency_ms=12.0)
    snap.local[CHANNEL_API_HTTP] = ProbeResult(channel=CHANNEL_API_HTTP, ok=True, latency_ms=15.0)
    snap.local[CHANNEL_WDTT_UDP] = ProbeResult(
        channel=CHANNEL_WDTT_UDP, ok=True, inconclusive=True, detail="нет ответа"
    )
    for k, v in kw.items():
        setattr(snap, k, v)
    return snap


def _kinds(snap: TargetSnapshot) -> set[str]:
    return {v.kind for v in classify_target(snap)}


def test_all_ok_gives_ok_verdict():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=5)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=5)
    verdicts = classify_target(snap)
    assert [v.kind for v in verdicts] == [KIND_OK]
    assert report_status(verdicts) == "ok"


def test_ip_blackhole_when_every_channel_times_out():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, failed=5)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=5)
    snap.world[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=2, source="world-external")
    verdicts = classify_target(snap)
    assert verdicts[0].kind == KIND_IP_BLACKHOLE
    assert verdicts[0].severity == "critical"
    assert verdicts[0].fixes, "у вывода обязательно должно быть решение"
    assert any("новую соту" in f for f in verdicts[0].fixes)
    assert report_status(verdicts) == "blocked"


def test_blackhole_not_reported_when_world_also_down():
    """Если адрес мёртв и вне РФ — это не блокировка, а наша поломка/маршрут."""
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, failed=5)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=5)
    snap.world[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=2, source="world-external")
    snap.world[CHANNEL_PING] = _agg(CHANNEL_PING, failed=2, source="world-external")
    assert KIND_IP_BLACKHOLE not in _kinds(snap)


def test_service_down_when_local_probe_also_fails():
    snap = _queen()
    snap.local[CHANNEL_API_TCP] = ProbeResult(
        channel=CHANNEL_API_TCP, ok=False, error_kind="refused", detail="refused"
    )
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=5)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=5, error="refused")
    verdicts = classify_target(snap)
    assert KIND_SERVICE_DOWN in {v.kind for v in verdicts}
    assert report_status(verdicts) == "down"


def test_port_block_when_one_port_dies_and_others_live():
    snap = _queen()
    snap.agent_port = 9100
    snap.local[CHANNEL_AGENT_TCP] = ProbeResult(channel=CHANNEL_AGENT_TCP, ok=True, latency_ms=2.0)
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=5)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=5)
    snap.ru[CHANNEL_AGENT_TCP] = _agg(CHANNEL_AGENT_TCP, failed=5)
    verdicts = classify_target(snap)
    port_block = [v for v in verdicts if v.kind == KIND_PORT_BLOCK]
    assert port_block, "должен быть вывод про порт"
    assert "DNAT" in " ".join(port_block[0].fixes)


def test_udp_block_when_tcp_alive_and_udp_dead():
    snap = _queen()
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=5)
    snap.ru[CHANNEL_WDTT_UDP] = _agg(CHANNEL_WDTT_UDP, failed=5)
    kinds = _kinds(snap)
    assert KIND_UDP_BLOCK in kinds
    assert KIND_IP_BLACKHOLE not in kinds


def test_sni_block_when_tcp_ok_but_tls_with_domain_fails():
    snap = _queen()
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=5)
    snap.ru[CHANNEL_API_TLS] = _agg(CHANNEL_API_TLS, failed=5, error=ERR_RESET)
    snap.ru[CHANNEL_TLS_NO_SNI] = _agg(CHANNEL_TLS_NO_SNI, ok=5)
    verdicts = classify_target(snap)
    sni = [v for v in verdicts if v.kind == KIND_SNI_BLOCK]
    assert sni and sni[0].confidence >= 0.8
    assert any("IP" in f for f in sni[0].fixes)


def test_foreign_http_answer_reads_as_stub_not_sni_block():
    snap = _queen()
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=4)
    snap.ru[CHANNEL_API_TLS] = _agg(CHANNEL_API_TLS, failed=4, error=ERR_HTTP)
    kinds = _kinds(snap)
    assert KIND_HTTP_STUB in kinds
    assert KIND_SNI_BLOCK not in kinds, "ответ дошёл — имя не режется"


def test_dns_poisoning_when_ru_nodes_resolve_elsewhere():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=3)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=3)
    snap.ru[CHANNEL_DNS] = _agg(CHANNEL_DNS, ok=3, ips=("10.20.30.40",))
    verdicts = classify_target(snap)
    assert verdicts[0].kind == KIND_DNS_POISONING
    assert "10.20.30.40" in " ".join(verdicts[0].evidence)


def test_dns_ok_when_resolved_to_our_ip():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=3)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=3)
    snap.ru[CHANNEL_DNS] = _agg(CHANNEL_DNS, ok=3, ips=("132.243.234.162",))
    assert KIND_DNS_POISONING not in _kinds(snap)


def test_rst_injection_distinguished_from_timeout():
    snap = _queen()
    snap.agent_port = 9100
    snap.local[CHANNEL_AGENT_TCP] = ProbeResult(channel=CHANNEL_AGENT_TCP, ok=True)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=5)
    snap.ru[CHANNEL_AGENT_TCP] = _agg(CHANNEL_AGENT_TCP, failed=5, error=ERR_RESET)
    kinds = _kinds(snap)
    assert KIND_RST_INJECTION in kinds
    assert KIND_PORT_BLOCK not in kinds


def test_partial_asn_block_is_warning_with_carriers():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=5)
    snap.ru[CHANNEL_API_TCP] = _agg(
        CHANNEL_API_TCP, ok=2, failed=3, asns=["AS200000", "AS200000", "AS8359", "AS31133", "AS3216"]
    )
    verdicts = classify_target(snap)
    partial = [v for v in verdicts if v.kind == KIND_ASN_PARTIAL]
    assert partial
    assert partial[0].severity == "warning"
    joined = " ".join(partial[0].evidence)
    assert "МТС" in joined or "МегаФон" in joined or "Билайн" in joined
    assert report_status(verdicts) == "degraded"


def test_throttling_needs_control_vantage():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=5, latency=900.0)
    snap.world[CHANNEL_PING] = _agg(CHANNEL_PING, ok=2, latency=60.0, source="world-external")
    kinds = _kinds(snap)
    assert KIND_THROTTLING in kinds

    # Без контрольной точки замедление не объявляем — можно принять свой лаг за шейпинг.
    snap2 = _queen()
    snap2.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=5, latency=900.0)
    assert KIND_THROTTLING not in _kinds(snap2)


def test_mobile_shutdown_from_client_telemetry():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=5)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=5)
    snap.clients = ClientSignals(
        window_minutes=30,
        reports=24,
        failures=24,
        by_stage={"handshake": 24},
        by_network={"mobile": 22, "wifi": 2},
        by_carrier={"МТС": 14, "Билайн": 8},
        by_transport={"udp": 24},
    )
    kinds = _kinds(snap)
    assert KIND_MOBILE_SHUTDOWN in kinds


def test_fingerprint_when_tunnel_dies_after_connect():
    snap = _queen()
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=5)
    snap.clients = ClientSignals(
        window_minutes=30,
        reports=18,
        failures=18,
        by_stage={"tunnel_dead": 15, "tcp": 3},
        by_network={"wifi": 10, "mobile": 8},
        by_transport={"udp": 18},
        short_lived_tunnels=12,
    )
    verdicts = classify_target(snap)
    fp = [v for v in verdicts if v.kind == KIND_PROTOCOL_FINGERPRINT]
    assert fp
    assert any("обход" in f.lower() or "обфускац" in f.lower() for f in fp[0].fixes)


def test_udp_block_from_client_handshake_failures():
    snap = _queen()
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=5)
    snap.clients = ClientSignals(
        window_minutes=30,
        reports=20,
        failures=20,
        by_stage={"handshake": 18, "tcp": 2},
        by_network={"wifi": 12, "mobile": 8},
        by_transport={"udp": 18},
    )
    assert KIND_UDP_BLOCK in _kinds(snap)


def test_few_client_failures_do_not_trigger_verdict():
    snap = _queen()
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=5)
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=5)
    snap.clients = ClientSignals(
        window_minutes=30, reports=2, failures=2, by_stage={"handshake": 2},
        by_network={"mobile": 2}, by_transport={"udp": 2},
    )
    assert _kinds(snap) == {KIND_OK}


def test_no_vantage_marks_report_unknown():
    snap = _queen()
    verdicts = classify_target(snap)
    assert verdicts[0].kind == "no_vantage"
    assert report_status(verdicts) == "unknown"


def test_every_verdict_has_actionable_fix():
    """Требование к агенту: любой вывод обязан содержать решение."""
    for m in all_methods():
        assert m.fixes, f"метод {m.kind} без решения"
        assert m.how_it_works, f"метод {m.kind} без описания"
    for item in knowledge_to_dict():
        assert item["fixes"]


def test_commands_are_rendered_with_real_host():
    cmds = render_commands(KIND_IP_BLACKHOLE, host="1.2.3.4", domain="example.ru")
    assert cmds and all("<IP>" not in c for c in cmds)
    assert any("1.2.3.4" in c for c in cmds)


def test_report_summary_mentions_worst_problem():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, failed=5)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=5)
    verdicts = classify_targets([snap])
    status = report_status(verdicts)
    summary = report_summary(verdicts, status)
    assert "Улей" in summary
    assert status == "blocked"


def _blocked_verdicts() -> list:
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, failed=4)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=4)
    return classify_targets([snap])


PLAN_ARGS = dict(confirm_cycles=2, renotify_sec=12 * 3600.0, max_per_cycle=2)


def test_incident_needs_second_cycle_before_it_is_logged():
    verdicts = _blocked_verdicts()
    push, state = plan_incidents(verdicts, {}, now_ts=1000.0, **PLAN_ARGS)
    assert push == [], "одиночный фейл не должен писаться в инциденты"
    assert all(v["seen"] == 1 for v in state.values())

    push, state = plan_incidents(verdicts, state, now_ts=2800.0, **PLAN_ARGS)
    assert push, "подтверждённая проблема обязана попасть в журнал"


def test_same_problem_is_not_logged_every_cycle():
    verdicts = _blocked_verdicts()
    _, state = plan_incidents(verdicts, {}, now_ts=0.0, **PLAN_ARGS)
    push, state = plan_incidents(verdicts, state, now_ts=1800.0, **PLAN_ARGS)
    assert push

    ts = 1800.0
    for _ in range(20):
        ts += 1800.0
        push, state = plan_incidents(verdicts, state, now_ts=ts, **PLAN_ARGS)
        assert push == [], "повтор в пределах окна тишины забивает журнал"

    push, _ = plan_incidents(verdicts, state, now_ts=ts + 13 * 3600.0, **PLAN_ARGS)
    assert push, "через окно тишины напоминание допустимо"


def test_resolved_problem_forgets_signature():
    verdicts = _blocked_verdicts()
    _, state = plan_incidents(verdicts, {}, now_ts=0.0, **PLAN_ARGS)
    _, state = plan_incidents(verdicts, state, now_ts=1800.0, **PLAN_ARGS)

    ok = _queen()
    ok.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=4)
    _, state = plan_incidents(classify_targets([ok]), state, now_ts=3600.0, **PLAN_ARGS)
    assert state == {}, "решённая проблема не должна тянуться в состоянии"


def test_incident_count_per_cycle_is_capped():
    snaps = []
    for i in range(5):
        snap = _queen()
        snap.name = f"Сота {i}"
        snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, failed=4)
        snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=4)
        snaps.append(snap)
    verdicts = classify_targets(snaps)
    _, state = plan_incidents(verdicts, {}, now_ts=0.0, **PLAN_ARGS)
    push, _ = plan_incidents(verdicts, state, now_ts=1800.0, **PLAN_ARGS)
    assert len(push) == 2, "за цикл пишем не больше лимита, остальное видно в отчёте"


def test_warning_severity_never_becomes_incident():
    snap = _queen()
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=3, failed=2)
    verdicts = classify_target(snap)
    assert verdicts and all(v.severity == "warning" for v in verdicts)
    _, state = plan_incidents(verdicts, {}, now_ts=0.0, **PLAN_ARGS)
    push, _ = plan_incidents(verdicts, state, now_ts=1800.0, **PLAN_ARGS)
    assert push == [], "деградация — не инцидент, только отчёт"


def test_unchecked_cell_does_not_hide_healthy_hive():
    queen = _queen()
    queen.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=4)
    cell = _queen()
    cell.name = "Сота 1"
    cell.role = "cell"
    verdicts = classify_targets([queen, cell])
    kinds = {v.kind for v in verdicts}
    assert KIND_NO_VANTAGE in kinds
    assert report_status(verdicts) == "ok", "непроверенная снаружи сота не гасит статус"


def test_parse_node_payload_shapes():
    ok, latency, kind, detail, ips = _parse_node_payload(
        "tcp", [{"address": "1.2.3.4", "time": 0.05}]
    )
    assert ok and latency and abs(latency - 50.0) < 1e-6 and kind == ""

    ok, _, kind, _, _ = _parse_node_payload("tcp", [{"error": "Connection timed out"}])
    assert not ok and kind == ERR_TIMEOUT

    ok, _, kind, _, _ = _parse_node_payload("tcp", [{"error": "Connection refused"}])
    assert not ok and kind == "refused"

    ok, _, kind, _, _ = _parse_node_payload("tcp", None)
    assert not ok and kind == ERR_TIMEOUT

    ok, latency, _, _, _ = _parse_node_payload(
        "ping", [[["OK", 0.12, "1.2.3.4"], ["OK", 0.2, "1.2.3.4"]]]
    )
    assert ok and latency and abs(latency - 120.0) < 1e-6

    ok, _, _, _, _ = _parse_node_payload("ping", [[["Timeout", None, None]]])
    assert not ok

    ok, _, _, _, _ = _parse_node_payload("http", [[1, 0.13, "OK", "200", "1.2.3.4"]])
    assert ok

    # Редирект от нашего же nginx — TLS с нашим SNI дошёл, это не блокировка.
    ok, _, _, _, _ = _parse_node_payload("http", [[1, 0.13, "Moved", "301", "1.2.3.4"]])
    assert ok

    ok, _, kind, _, _ = _parse_node_payload("http", [[1, 0.13, "Forbidden", "403", "1.2.3.4"]])
    assert not ok and kind == ERR_HTTP

    ok, _, _, _, ips = _parse_node_payload("dns", [{"A": ["5.6.7.8"], "TTL": 300}])
    assert ok and ips == ("5.6.7.8",)

    ok, _, kind, _, _ = _parse_node_payload("dns", [{"A": []}])
    assert not ok and kind == "dns"


MAX_AGE = 48 * 3600


def test_client_report_without_age_counts_as_now():
    # Старые клиенты поля не присылают — считаем, что отказ только что.
    assert client_report_age_sec(None, MAX_AGE) == 0
    assert client_report_age_sec("", MAX_AGE) == 0
    assert client_report_age_sec("не число", MAX_AGE) == 0


def test_queued_client_report_keeps_its_age():
    # Репорт пролежал в очереди 2 часа — он не про «сейчас».
    assert client_report_age_sec(7200, MAX_AGE) == 7200
    assert client_report_age_sec("7200", MAX_AGE) == 7200


def test_client_clock_ahead_does_not_move_report_into_future():
    assert client_report_age_sec(-500, MAX_AGE) == 0


def test_client_report_older_than_retention_is_dropped():
    assert client_report_age_sec(MAX_AGE + 1, MAX_AGE) is None
    assert client_report_age_sec(MAX_AGE, MAX_AGE) == MAX_AGE


def test_delayed_client_report_falls_out_of_aggregation_window():
    """Отложенный репорт не должен попадать в 30-минутное окно агента."""
    window_sec = 30 * 60
    fresh = client_report_age_sec(60, MAX_AGE)
    delayed = client_report_age_sec(3 * 3600, MAX_AGE)
    assert fresh is not None and fresh < window_sec, "свежий отказ агент видит"
    assert delayed is not None and delayed > window_sec, "старый отказ не создаёт ложную блокировку"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    print(f"ok ({len(tests)} tests)")
