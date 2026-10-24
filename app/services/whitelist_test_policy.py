"""Read-only opt-in projection of source candidates for isolated Android testing."""
import hashlib
import json

from app.services.routing_policy import normalize_domains
from app.services.whitelist_catalog import AGGREGATE_SUFFIXES


def build_catalog_test_policy(catalog: dict, active_policy: dict) -> dict:
    if not catalog or not catalog.get('entries'):
        raise ValueError('CatalogUnavailable')
    exact, suffix = set(), set()
    for entry in catalog['entries']:
        domain = normalize_domains([entry['value']])[0]
        if entry['kind'] == 'exact':
            exact.add(domain)
        elif entry['kind'] == 'suffix' and domain not in AGGREGATE_SUFFIXES:
            suffix.add(domain)
        else:
            raise ValueError('InvalidCatalogRule')
    payload = {
        'schema_version': 1,
        'profile': 'catalog-test',
        'direct_domains': normalize_domains(sorted(suffix)),
        'direct_exact_domains': normalize_domains(sorted(exact)),
        'vpn_domains': normalize_domains(active_policy['vpn_domains']),
    }
    payload['revision'] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    payload['refresh_seconds'] = 300
    payload['catalog_revision'] = catalog['revision']
    payload['reachability'] = 'not_measured'
    if len(json.dumps(payload)) > 240000:
        raise ValueError('CatalogPolicyTooLarge')
    return payload
