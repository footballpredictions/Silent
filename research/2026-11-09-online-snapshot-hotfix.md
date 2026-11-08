# Online snapshot and SMTP fallback corrections

## Production failure

A read-only audit on 2026-11-08 observed the dashboard change from 129 to 103
and back to 129. One cell's `/v1/status` response was missing. Its contribution
fell from roughly 28 live WireGuard handshakes to one DB-connected device.
The partial total replaced the shared Redis integer, so both API workers and
every dashboard mode agreed on an incorrect measurement.

An isolated reproduction of the actual collection/assembly path gave 134 to
105 with an unchanged device population and exactly one missing measurement.
Worker consistency alone did not cover this failure.

## Presentation snapshot

`app/services/hive_online_snapshot.py` owns presentation-only collection state.
It never changes peers, VPN services, subscriptions or device connection flags.

- Each node keeps its last measured count and observation timestamp.
- A missing measurement can reuse that value for at most 90 seconds. It is
  immediately marked `stale`; a failed poll never renews its observation time.
- After 90 seconds, or for a missing measurement without a previous value, the
  total is `null` and its quality is `unknown`. A DB-only partial sum is not
  represented as the measured total.
- Successful decreases and zero counts are published immediately. There is
  no monotonic maximum or smoothing of actual measurements.
- The collection timestamp is taken before network work. Redis WATCH/MULTI
  prevents a slower, older collection from overwriting a newer collection.
- Redis holds the snapshot under `hive:online_snapshot:v1`. Its TTL does not
  extend node measurement lifetimes. Cached reads also enforce observation age.
- The old `hive:vpn_online_shown` integer remains atomically available for
  compatible readers when a total is known; it is removed when it is unknown.
- Queen WG read failures carry `wg_stats_ok=false`, preserving existing numeric
  diagnostic fields while distinguishing an unsuccessful read from measured zero.

Admin stats and hive summary expose optional `online_status`,
`online_snapshot_at`, `online_observed_at`, `online_stale_nodes`, and
`online_unknown_nodes`. Hive cells expose optional node quality and timestamp.
Legacy per-cell count fields remain integers; the current UI hides them when
their measurement is unknown. Client-facing VPN contracts are unchanged.

Dashboard/hive UI labels reused measurements and unavailable totals. The
availability panel explicitly distinguishes IP/API reachability from a tested
VPN data session and displays actual versus requested Russian probe points.
Classifier decisions and IP/port automation were not changed by this work.

## SMTP event-loop failure

The legacy synchronous relay lookup used `asyncio.run` with the application's
shared asyncpg pool. A pooled connection created on the API loop could then be
used by another thread's loop, producing `different loop` and
`asyncpg.InternalClientError`, and losing the relay list.

Async auth callers continue to supply prepared relay lists. The synchronous
compatibility fallback now owns a temporary NullPool engine, creates and closes
its connection in that same loop, disposes the engine, and has a six-second
lookup deadline. It does not reuse or dispose the API process's engine. No mail
is sent by the regression checks.

## Regression checks

Run from the backend root with the project's Python dependencies:

```powershell
python scripts/test_hive_online_partial_unit.py
python scripts/test_dashboard_online_consistency_unit.py
python scripts/test_email_relay_loop_unit.py
python scripts/test_email_smtp_unit.py
```

The nine collection tests cover missing cell/Queen measurements, the actual
Queen failure DTO, independent worker reads, repeated failures, expiry even
without another collection, cold partial collection, genuine decreases, and
an older writer. Two SMTP loop tests cover synchronous and running-loop callers.
The canonical deploy preflight includes the new tests, and its source guard
includes both new snapshot code and the SMTP relay module.

For built UI QA, serve `admin-ui/dist` on 127.0.0.1:3012 and run:

```powershell
node scripts/test_online_quality_ui.cjs
```

It exercises fresh/stale/unknown states, compatibility with older API payloads,
both dashboard and hive pages, 1280/390 widths, and availability scope copy.
Production verification additionally uses unique temporary Redis keys and a
separate process to repeat the real DB/SMTP lookup without touching mail or VPN.

## Deployed verification (2026-11-09, Moscow)

Canonical selected-file deployment and all 31 preflight scripts passed. The
running API's 35 guarded source files, admin publication on HTTPS 443/2083,
cache headers/assets, and the four-cell API allowlist were verified.

Actual Redis with disposable keys produced 134 -> 134/stale for a missing
measurement, null after expiry, an immediate fresh decrease to 104, and 104
after a late older writer. Actual DB relay lookup returned three relay entries
in each calling context with no loop errors and without sending messages.
Twelve rounds / 36 real API requests agreed within each snapshot generation.

All five WDTT PIDs/restart counts, interface indexes, API DNAT rules, and all
111 live peer addresses from the safety baseline were preserved. Final API
health was HTTP 200 in 41 ms; the 1,030 API log lines since restart contained
zero errors, tracebacks, shared snapshot failures, cross-loop failures or kicks.

Private local verification receipts are named `backend-fix-*-20261109` under
the workspace `.playwright-mcp` directory. These operator artifacts are not
required by the deployed application or included in the source commit.

## Follow-up: dry-run route selection is not UDP reachability evidence

The user then supplied a contradictory report: its relay-plan card claimed
"UDP reaches the server" while the channel details contained no Russian UDP
measurements. `cell_relay_policy` used `path is not False` to choose the safe
direct route, so `None` (unmeasured) and `True` shared a success explanation.
The broader availability scope note did not correct this separate card.

Direct routing remains the safe default. Optional `ru_udp_status` on the plan
and hops now separates `unverified`, `reachable` and `unreachable`. Missing,
pending or single-source failed UDP results remain unverified; failed ping is
not evidence of UDP failure. A relay candidate requires two distinct failing
UDP sources and a positively probed entry. The plan remains unexecuted, with no
new tunnels or changes to client Endpoints, WG, WDTT or iptables.

Read-side report reclassification rebuilds unexecuted relay plans from their
stored measurements, preserving timestamps and archive bytes. No new probe
cycle is required to correct an old success claim. The UI distinguishes a
default direct route from measured reachability and also handles legacy
payloads that do not contain the new evidence field.

The relay-policy suite now contains 12 cases including saved-report replay.
Ten browser cases cover unknown/legacy/confirmed/relay/hold states at 1280 and
390 pixels. Both that suite and the existing 58-case classifier suite pass.
The canonical preflight includes relay-policy regression tests; the source
guard also includes `ai/cell_relay_policy.py`.

The follow-up passed all 32 canonical preflight scripts and deployed two Python
files plus admin UI. Four real API reads corrected the same saved report's
legacy success title while preserving its timestamp and archive SHA. All five
hops retained direct routing with `ru_udp_status=unverified`; no new probe was
requested and the plan remained unexecuted. All five WDTT PIDs, interface
indexes and API DNAT rules were preserved. Final health was HTTP 200 in 43 ms,
with zero errors/tracebacks or kicks in the 557 API log lines since restart.
