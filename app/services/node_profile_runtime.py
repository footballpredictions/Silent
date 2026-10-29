"""Standalone host-side profile transaction. No Docker/app dependencies.

Only our tagged rules and profile files are owned here. Never restart wdtt,
replace peers, flush tables, change host DNS, or lower a live interface MTU.
The journal survives API/SSH loss; a separate systemd timer can recover it.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path('/opt/silent-vpn/node-profiles')
TAG = 'SILENT_NODE_PROFILE'
NET = '10.66.0.0/16'
GAME_SYSCTLS = {
    'net.ipv4.ip_no_pmtu_disc': '0',
    'net.netfilter.nf_conntrack_udp_timeout': '120',
    'net.netfilter.nf_conntrack_udp_timeout_stream': '180',
}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


class Host:
    def run(self, *args: str, check: bool = True) -> str:
        p = subprocess.run(args, capture_output=True, text=True, timeout=12)
        if check and p.returncode:
            # Do not expose arbitrary command output (may contain credentials).
            raise RuntimeError(f'{args[0]} failed ({p.returncode})')
        return p.stdout.strip()

    def present(self, table: str, chain: str, args: list[str]) -> bool:
        p = subprocess.run(['iptables', '-w', '5', '-t', table, '-C', chain, *args],
                           capture_output=True, timeout=10)
        if p.returncode not in (0, 1):
            raise RuntimeError('iptables check failed')
        return p.returncode == 0

    def rule(self, table: str, chain: str, args: list[str], enabled: bool) -> None:
        if self.present(table, chain, args) != enabled:
            self.run('iptables', '-w', '5', '-t', table, '-A' if enabled else '-D', chain, *args)

    def health(self, queen: bool) -> dict:
        if self.run('systemctl', 'is-active', 'wdtt') != 'active':
            raise RuntimeError('VPN service is not active')
        pid = self.run('systemctl', 'show', 'wdtt', '-p', 'MainPID', '--value')
        if not pid.isdigit() or int(pid) <= 0:
            raise RuntimeError('VPN process is unavailable')
        # Deliberately no peer mutation; never put keys into status/logs.
        peers = [line.split()[0] for line in self.run('wg', 'show', 'wdtt0', 'latest-handshakes').splitlines()
                 if len(line.split()) == 2 and int(line.split()[1]) > time.time() - 180]
        port = 8000 if queen else 9100
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=5) as r:
            if r.status != 200:
                raise RuntimeError('API health failed')
        return {'pid': pid, 'peers': [hashlib.sha256(p.encode()).hexdigest() for p in peers]}


def rules() -> list[tuple[str, str, list[str], str]]:
    return [
        ('mangle', 'POSTROUTING', ['-s', NET, '-m', 'comment', '--comment', TAG + '_AI',
                                 '-j', 'TTL', '--ttl-set', '64'], 'ai'),
        ('mangle', 'FORWARD', ['-s', NET, '-p', 'tcp', '--tcp-flags', 'SYN,RST', 'SYN',
                             '-m', 'comment', '--comment', TAG + '_GAME',
                             '-j', 'TCPMSS', '--clamp-mss-to-pmtu'], 'gaming'),
    ]


def check_health(before: dict, after: dict) -> None:
    if before['pid'] != after['pid']:
        raise RuntimeError('VPN process changed during profile application')
    if not set(before['peers']).issubset(after['peers']):
        raise RuntimeError('VPN peers changed during profile application')


def legacy_dns_rules(host: Host) -> list[tuple[str, str, list[str]]]:
    """Remove only the old AI DNS DNAT, never the API or threat-filter rules."""
    found = []
    for line in host.run('iptables', '-t', 'nat', '-S', 'PREROUTING').splitlines():
        args = shlex.split(line)
        if (args[:2] != ['-A', 'PREROUTING'] or '-s' not in args
                or args[args.index('-s') + 1] != NET or '--dport' not in args
                or args[args.index('--dport') + 1] != '53'
                or '--to-destination' not in args):
            continue
        dst = args[args.index('--to-destination') + 1]
        if dst.endswith(':5353') and '-j' in args and args[args.index('-j') + 1] == 'DNAT':
            found.append(('nat', 'PREROUTING', args[2:]))
    return found


def restore(host: Host, journal: dict, *, root: Path | None = None) -> None:
    errors = []
    for entry in reversed(journal.get('rules', [])):
        try:
            host.rule(entry['table'], entry['chain'], entry['args'], entry['present'])
        except Exception:
            errors.append('firewall')
    for key, old in journal.get('sysctls', {}).items():
        try:
            # Respect concurrent administrators / other tuners.
            if host.run('sysctl', '-n', key) == GAME_SYSCTLS[key]:
                host.run('sysctl', '-w', f'{key}={old}')
        except Exception:
            errors.append('sysctl')
    for entry in journal.get('legacy_units', []):
        try:
            host.run('systemctl', 'enable', entry['unit'])
            if entry['active']:
                host.run('systemctl', 'start', entry['unit'])
        except Exception:
            errors.append('legacy DNS timer')
    if errors:
        raise RuntimeError('Rollback requires attention: ' + ', '.join(errors))
    if root is not None:
        path = root / 'applied.json'
        current = json.loads(path.read_text()) if path.exists() else {}
        if current.get('operation_id') == journal['operation_id']:
            previous = journal.get('previous_applied')
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                atomic_json(path, previous)


def apply(request: dict, *, host: Host | None = None, root: Path = ROOT) -> dict:
    host = host or Host()
    op = request['operation_id']
    status_path = root / f'{op}.status.json'
    before = None
    target = {k: bool(request[k]) for k in ('ai', 'gaming')}
    previous_path = root / 'applied.json'
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    journal = {'rules': [], 'sysctls': {}, 'legacy_units': [], 'before': before,
               'previous_applied': previous or None,
               'operation_id': op, 'queen': request['queen'], 'state': 'running'}
    atomic_json(status_path, journal)

    def remember_rule(table: str, chain: str, args: list[str]) -> None:
        journal['rules'].append({'table': table, 'chain': chain, 'args': args,
                                 'present': host.present(table, chain, args)})
        atomic_json(status_path, journal)

    try:
        before = host.health(request['queen'])
        journal['before'] = before
        atomic_json(status_path, journal)
        # Reject a legacy custom proxy rather than tear down its live TCP flows.
        if request.get('legacy_ai') and not target['ai']:
            if (Path('/etc/silent-ai/proxy.enabled').exists()
                    and host.run('systemctl', 'is-active', 'sing-box', check=False) == 'active'):
                raise RuntimeError('Disable the legacy AI proxy before removing its profile')
            # Keep resolver processes and host resolv.conf intact. Existing DNS
            # conntrack entries finish normally; new flows use the client DNS.
            for unit in ('silent-ai-rules.service', 'silent-ai-dnslist.timer'):
                if host.run('systemctl', 'is-enabled', unit, check=False) == 'enabled':
                    journal['legacy_units'].append({'unit': unit, 'active':
                        host.run('systemctl', 'is-active', unit, check=False) == 'active'})
                    atomic_json(status_path, journal)
                    host.run('systemctl', 'disable', unit)
                    if unit.endswith('.timer'):
                        host.run('systemctl', 'stop', unit)
            for table, chain, args in legacy_dns_rules(host):
                remember_rule(table, chain, args)
                host.rule(table, chain, args, False)

        for table, chain, args, flag in rules():
            remember_rule(table, chain, args)
            host.rule(table, chain, args, target[flag])

        mtu_floor = max(int(previous.get('mtu_floor', 0)), int(request.get('mtu_floor', 0)),
                        1420 if target['gaming'] else 0)
        if mtu_floor:
            link = json.loads(host.run('ip', '-j', 'link', 'show', 'dev', 'wdtt0'))[0]
            # Only raise. Old server3 clients can still use 1420 after disabling
            # the profile; lowering the server would blackhole their UDP.
            if int(link['mtu']) < mtu_floor:
                host.run('ip', 'link', 'set', 'dev', 'wdtt0', 'mtu', str(mtu_floor))
        if target['gaming']:
            for key, value in GAME_SYSCTLS.items():
                old = host.run('sysctl', '-n', key)
                if key.startswith('net.netfilter.') and int(old) >= int(value):
                    continue
                journal['sysctls'][key] = old
                atomic_json(status_path, journal)
                host.run('sysctl', '-w', f'{key}={value}')
                if host.run('sysctl', '-n', key) != value:
                    raise RuntimeError('UDP tuning verification failed')
            link = json.loads(host.run('ip', '-j', 'link', 'show', 'dev', 'wdtt0'))[0]
            if int(link['mtu']) < 1420:
                raise RuntimeError('Game MTU verification failed')

        for table, chain, args, flag in rules():
            if host.present(table, chain, args) != target[flag]:
                raise RuntimeError('Profile firewall verification failed')
        check_health(before, host.health(request['queen']))
        atomic_json(root / 'applied.json', {**target, 'queen': request['queen'],
                                         'legacy_ai': request.get('legacy_ai', False),
                                         'operation_id': op, 'mtu_floor': mtu_floor})
        journal.update(state='applied', result=target)
        atomic_json(status_path, journal)
        return journal
    except BaseException as exc:
        try:
            restore(host, journal, root=root)
            if before is not None:
                check_health(before, host.health(request['queen']))
            journal.update(state='error', error=str(exc)[:300], rolled_back=True)
        except BaseException as rollback_error:
            journal.update(state='error', error=str(rollback_error)[:300], rolled_back=False)
        atomic_json(status_path, journal)
        raise


def main() -> None:
    import fcntl
    ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(ROOT, 0o700)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(RuntimeError('Profile application timed out')))
    with (ROOT / 'lock').open('w') as lock:
        # Serialise requests across API workers and boot/recovery jobs.
        fcntl.flock(lock, fcntl.LOCK_EX)
        mode, op = sys.argv[1:3]
        if mode == 'recover':
            path = ROOT / f'{op}.status.json'
            if path.exists():
                journal = json.loads(path.read_text())
                if journal['state'] == 'running':
                    applied = ROOT / 'applied.json'
                    committed = json.loads(applied.read_text()) if applied.exists() else {}
                    if committed.get('operation_id') == op:
                        journal.update(state='applied', result={k: committed[k] for k in ('ai', 'gaming')})
                    else:
                        try:
                            restore(Host(), journal, root=ROOT)
                            journal.update(state='error', error='Interrupted operation rolled back', rolled_back=True)
                        except Exception:
                            journal.update(state='error', error='Recovery requires attention', rolled_back=False)
                    atomic_json(path, journal)
            return
        if mode == 'boot':
            if not (ROOT / 'applied.json').exists():
                return
            request = json.loads((ROOT / 'applied.json').read_text())
            request['operation_id'] = 'boot'
        else:
            request = json.loads((ROOT / f'{op}.request.json').read_text())
        apply(request)


if __name__ == '__main__':
    main()
