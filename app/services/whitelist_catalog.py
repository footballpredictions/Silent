"""Typed community-source inventory; never publishes client routing rules."""
import hashlib
import ipaddress
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Source:
    id: str
    url: str
    format: str


@dataclass(frozen=True)
class FetchResult:
    status: int
    body: bytes
    etag: str = ''


SOURCES = (
    Source('hxehex', 'https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/main/whitelist.txt', 'plain'),
    Source('jinndi', 'https://raw.githubusercontent.com/jinndi/geosite-cheburnet/main/geosite-cheburnet.json', 'singbox'),
)
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_RULES = 20000
MAX_HISTORY = 8
AGGREGATE_SUFFIXES = frozenset({
    'ru', 'su', 'xn--p1ai', 'com.ru', 'net.ru', 'org.ru', 'spb.ru', 'msk.ru',
    'github.io', 'pages.dev', 'cloudfront.net', 'amazonaws.com', 'azurewebsites.net',
    'yandexcloud.net', 'storage.yandexcloud.net', 'timeweb.cloud', 'timeweb.com',
    'clstorage.net', 'akamaized.net', 'akamaihd.net', 'fastly.net', 'googleusercontent.com',
})


class ExcessiveSourceChange(ValueError):
    pass


def catalog_directory() -> Path:
    return Path(__file__).resolve().parents[2] / 'update' / 'whitelist-discovery'


def _normal_domain(raw: str) -> str:
    if not isinstance(raw, str) or len(raw) > 1024:
        raise ValueError('InvalidDomain')
    domain = raw.strip().rstrip('.').lower().encode('idna').decode('ascii')
    if len(domain) > 253 or '.' not in domain or any(
        not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
        for label in domain.split('.')
    ):
        raise ValueError('InvalidDomain')
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError('IPNotDomain')
    if domain.endswith(('.local', '.localhost', '.internal', '.invalid', '.test', '.example')):
        raise ValueError('NonPublicDomain')
    return domain


def parse_source(source: Source, body: bytes) -> tuple[list[dict], list[dict]]:
    if not body or len(body) > MAX_SOURCE_BYTES:
        raise ValueError('InvalidSourceSize')
    content = body.decode('utf-8-sig')
    rules = []
    if source.format == 'plain':
        rules = [('exact', line.strip()) for line in content.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    elif source.format == 'singbox':
        payload = json.loads(content)
        if not isinstance(payload, dict) or payload.get('version') not in (1, 2, 3) or not isinstance(payload.get('rules'), list):
            raise ValueError('InvalidRuleset')
        for rule in payload['rules']:
            if not isinstance(rule, dict) or not rule or set(rule) - {'domain', 'domain_suffix'}:
                raise ValueError('UnsupportedConditionalRule')
            for field, kind in (('domain', 'exact'), ('domain_suffix', 'suffix')):
                values = rule.get(field, [])
                if not isinstance(values, list):
                    raise ValueError('InvalidDomainList')
                rules.extend((kind, value) for value in values)
    else:
        raise ValueError('UnsupportedFormat')
    if len(rules) > MAX_RULES:
        raise ValueError('SourceRuleLimit')
    accepted = set()
    quarantined = []
    for kind, raw in rules:
        try:
            domain = _normal_domain(raw)
            if domain in AGGREGATE_SUFFIXES:
                raise ValueError('AggregateSuffix')
            accepted.add((kind, domain))
        except (ValueError, UnicodeError) as error:
            value = raw if isinstance(raw, str) and re.fullmatch(r'[a-zA-Z0-9.*_/-]{1,253}', raw) else '<non-domain>'
            quarantined.append({'kind': kind, 'value': value, 'reason': str(error) if isinstance(error, ValueError) and str(error) in {'AggregateSuffix', 'IPNotDomain', 'NonPublicDomain'} else 'InvalidDomain'})
    if not accepted:
        raise ValueError('EmptyDomainSource')
    return [{'kind': kind, 'value': value} for kind, value in sorted(accepted)], quarantined


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


def fetch_source(source: Source, etag: str = '') -> FetchResult:
    if source not in SOURCES:
        raise ValueError('UnregisteredSource')
    headers = {'User-Agent': 'SilentVPN-WhitelistCatalog/1', 'Accept-Encoding': 'identity'}
    if etag:
        headers['If-None-Match'] = etag
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    deadline = time.monotonic() + 30
    try:
        with opener.open(urllib.request.Request(source.url, headers=headers), timeout=15) as response:
            chunks = []
            size = 0
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError('SourceDeadline')
                chunk = response.read1(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_SOURCE_BYTES:
                    raise ValueError('SourceSizeLimit')
                chunks.append(chunk)
            body = b''.join(chunks)
            return FetchResult(response.status, body, response.headers.get('ETag', '')[:512])
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return FetchResult(304, b'', etag)
        raise


@contextmanager
def _catalog_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'refresh.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0, 2)
            if not lock.tell():
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.catalog-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_catalog(directory: Path | None = None) -> dict | None:
    path = (directory or catalog_directory()) / 'catalog.json'
    if not path.is_file():
        return None
    if path.stat().st_size > 16 * MAX_SOURCE_BYTES:
        raise ValueError('InvalidCatalogSize')
    result = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(result, dict) or result.get('schema_version') != 1 or not isinstance(result.get('sources'), dict):
        raise ValueError('InvalidCatalog')
    return result


def refresh_catalog(directory: Path | None = None, fetch=fetch_source, now: datetime | None = None) -> dict:
    directory = directory or catalog_directory()
    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    with _catalog_lock(directory):
        previous = load_catalog(directory) or {}
        sources = {}
        for source in SOURCES:
            cached = previous.get('sources', {}).get(source.id, {})
            current = {**cached, 'url': source.url, 'format': source.format, 'checked_at': timestamp}
            try:
                response = fetch(source, cached.get('etag', ''))
                if response.status == 304:
                    if not cached.get('entries'):
                        raise ValueError('NotModifiedWithoutCache')
                elif response.status == 200:
                    entries, rejected = parse_source(source, response.body)
                    old_rules = {(entry['kind'], entry['value']) for entry in cached.get('entries', [])}
                    new_rules = {(entry['kind'], entry['value']) for entry in entries}
                    if len(old_rules) >= 20 and len(old_rules ^ new_rules) / max(len(old_rules), len(new_rules)) > .5:
                        raise ExcessiveSourceChange('ExcessiveSourceChange')
                    digest = hashlib.sha256(response.body).hexdigest()
                    current.update(entries=entries, quarantine=rejected, sha256=digest, etag=response.etag,
                                   content_observed_changed_at=timestamp if digest != cached.get('sha256') else cached.get('content_observed_changed_at'))
                else:
                    raise ValueError('UnexpectedHTTPStatus')
                current.update(status='current', error=None, last_success_at=timestamp, upstream_updated_at=cached.get('upstream_updated_at'))
            except Exception as error:
                current.update(status='stale' if cached.get('entries') else 'unavailable', error=type(error).__name__)
            sources[source.id] = current
        merged = {}
        for source_id, source_state in sources.items():
            for entry in source_state.get('entries', []):
                key = (entry['kind'], entry['value'])
                merged.setdefault(key, []).append(source_id)
        entries = [{'kind': key[0], 'value': key[1], 'sources': sorted(source_ids), 'evidence': 'source_listed'}
                   for key, source_ids in sorted(merged.items())]
        revision = hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        catalog = {'schema_version': 1, 'checked_at': timestamp, 'revision': revision, 'entries': entries,
                   'sources': sources, 'reachability': 'not_measured', 'auto_publish': False}
        if previous.get('revision') and previous['revision'] != revision:
            if not re.fullmatch('[a-f0-9]{64}', previous['revision']):
                raise ValueError('InvalidPreviousRevision')
            history = directory / 'history'
            _write_json(history / (previous['revision'] + '.json'), previous)
            snapshots = sorted((path for path in history.glob('*.json') if re.fullmatch(r'[a-f0-9]{64}\.json', path.name)), key=lambda path: path.stat().st_mtime, reverse=True)
            for snapshot in snapshots[MAX_HISTORY:]:
                snapshot.unlink()
        _write_json(directory / 'catalog.json', catalog)
        return catalog


def catalog_summary(catalog: dict | None) -> dict:
    if catalog is None:
        return {'status': 'not_collected', 'auto_publish': False, 'reachability': 'not_measured'}
    sources = {source_id: {key: value for key, value in state.items() if key not in ('entries', 'quarantine')}
               for source_id, state in catalog['sources'].items()}
    return {key: catalog[key] for key in ('schema_version', 'checked_at', 'revision', 'reachability', 'auto_publish')} | {
        'status': 'current' if all(state.get('status') == 'current' for state in sources.values()) else 'degraded',
        'source_count': len(sources), 'entry_count': len(catalog['entries']),
        'domain_count': len({entry['value'] for entry in catalog['entries']}),
        'exact_count': sum(entry['kind'] == 'exact' for entry in catalog['entries']),
        'suffix_count': sum(entry['kind'] == 'suffix' for entry in catalog['entries']),
        'quarantine_count': sum(len(state.get('quarantine', [])) for state in catalog['sources'].values()), 'sources': sources,
    }
