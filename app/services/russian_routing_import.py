"""Compile a pinned geosite snapshot into the existing domain-only policy.

No downloads, automatic publication, GeoIP inference or client-schema changes.
Exact hosts and regexes cannot become suffixes on existing clients.
"""
import io
import re
import tarfile

from app.services.routing_policy import RUSSIAN_DOMAIN_ZONES, build_policy, normalize_domains
from app.services.whitelist_catalog import AGGREGATE_SUFFIXES

MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_DATA_BYTES = 16 * 1024 * 1024
MAX_SOURCE_RULES = 20000
SHARED_SUFFIXES = AGGREGATE_SUFFIXES | {'ngenix.net', 'gcdn.co', 'azureedge.net', 'cloudflare.net'}


def import_geosite(data: bytes) -> dict:
    if not data or len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError('Invalid geosite archive size')
    files, size = {}, 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            if '/data/' not in member.name or not member.isfile():
                continue
            name = member.name.split('/data/', 1)[1]
            if not re.fullmatch(r'[a-z0-9_!-]+', name) or name in files:
                raise ValueError('Invalid geosite data filename')
            size += member.size
            if member.size > 256 * 1024 or size > MAX_DATA_BYTES or len(files) >= 10000:
                raise ValueError('Geosite data exceeds limits')
            with archive.extractfile(member) as source:
                files[name] = source.read().decode('utf-8-sig')

    used, visiting, cache = set(), set(), {}

    def expand(name):
        if name in visiting or len(visiting) >= 32 or name not in files:
            raise ValueError('Missing or circular geosite include: '+name)
        if name in cache:
            return cache[name]
        visiting.add(name)
        used.add(name)
        rules = []
        for raw in files[name].splitlines():
            parts = raw.split('#', 1)[0].split()
            if not parts:
                continue
            value, *tags = parts
            if any(not re.fullmatch(r'@!?[a-zA-Z0-9_-]+', tag) for tag in tags):
                raise ValueError('Unsupported geosite attribute')
            if value.startswith('include:'):
                target = value[8:]
                if not re.fullmatch(r'[a-z0-9_!-]+', target):
                    raise ValueError('Invalid geosite include')
                included = expand(target)
                for selector in tags:
                    if selector.startswith('@!'):
                        included = [rule for rule in included if '@'+selector[2:] not in rule[2]]
                    else:
                        included = [rule for rule in included if selector in rule[2]]
                rules.extend(included)
            else:
                kind = 'domain'
                if ':' in value:
                    kind, value = value.split(':', 1)
                if kind not in ('domain', 'full', 'regexp') or not value:
                    raise ValueError('Unsupported geosite rule')
                if kind != 'regexp':
                    value = normalize_domains([value])[0]
                rules.append((kind, value, tuple(tags)))
            if len(rules) > MAX_SOURCE_RULES:
                raise ValueError('Too many geosite rules')
        visiting.remove(name)
        cache[name] = rules
        return rules

    rules = expand('category-ru')
    return {'domains': sorted({value for kind, value, _ in rules if kind == 'domain'}),
            'exact_domains': sorted({value for kind, value, _ in rules if kind == 'full'}),
            'regex_count': sum(kind == 'regexp' for kind, _, _ in rules),
            'included_files': sorted(used)}


def merge_russian_policy(current: dict, snapshot: dict, *, include_country_zones: bool = False) -> tuple[dict, dict]:
    original = build_policy(current['direct_domains'], current['vpn_domains'])
    direct, vpn = set(original['direct_domains']), original['vpn_domains']
    skipped = set()

    def matches(host, rules):
        return any(host == rule or host.endswith('.'+rule) for rule in rules)

    # Parents first: compact only newly imported rules; preserve every manual entry.
    domains = normalize_domains(snapshot['domains'])
    for domain in sorted(domains, key=lambda value: (value.count('.'), len(value), value)):
        if domain in RUSSIAN_DOMAIN_ZONES:
            if not include_country_zones:
                continue
        elif domain in SHARED_SUFFIXES:
            skipped.add(domain)
            continue
        if not matches(domain, direct) and not matches(domain, vpn):
            direct.add(domain)
    policy = build_policy(sorted(direct), vpn)
    return policy, {'added_domains': sorted(direct-set(original['direct_domains'])),
                    'shared_suffixes_skipped': sorted(skipped),
                    'exact_rules_not_promoted': snapshot['exact_domains'],
                    'regex_rules_skipped': snapshot['regex_count'],
                    'included_files': snapshot['included_files']}
