import asyncio
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.whitelist_test_policy import build_catalog_test_policy


class TestCatalogPolicy(unittest.TestCase):
    def setUp(self):
        self.catalog = {'revision': 'a' * 64, 'entries': [
            {'kind': 'exact', 'value': 'api.max.ru'},
            {'kind': 'suffix', 'value': 'max.ru'},
        ]}
        self.active = {'revision': 'b' * 64, 'direct_domains': ['existing.ru'], 'vpn_domains': ['blocked.max.ru']}

    def test_typed_rules_and_vpn_overrides_without_mutation(self):
        before = copy.deepcopy((self.catalog, self.active))
        result = build_catalog_test_policy(self.catalog, self.active)
        self.assertEqual(result['direct_exact_domains'], ['api.max.ru'])
        self.assertEqual(result['direct_domains'], ['existing.ru', 'max.ru'])
        self.assertEqual(result['vpn_domains'], ['blocked.max.ru'])
        self.assertEqual(result['profile'], 'catalog-test')
        self.assertEqual((self.catalog, self.active), before)

    def test_revision_changes_with_exact_rules_and_overrides(self):
        first = build_catalog_test_policy(self.catalog, self.active)['revision']
        self.catalog['entries'][0]['value'] = 'different.max.ru'
        second = build_catalog_test_policy(self.catalog, self.active)['revision']
        self.active['vpn_domains'] = []
        third = build_catalog_test_policy(self.catalog, self.active)['revision']
        self.assertEqual(len({first, second, third}), 3)

    def test_manual_direct_updates_are_merged_without_countrywide_rules(self):
        self.active['direct_domains'] = ['ru', 'su', 'xn--p1ai', 'sweb.ru', 'max.ru']
        before = copy.deepcopy(self.active)
        policy = build_catalog_test_policy(self.catalog, self.active)
        self.assertEqual(policy['direct_domains'], ['max.ru', 'sweb.ru'])
        self.assertEqual(policy['direct_exact_domains'], ['api.max.ru'])
        self.assertEqual(self.active, before)
        self.active['direct_domains'].append('manual.ru')
        updated = build_catalog_test_policy(self.catalog, self.active)
        self.assertIn('manual.ru', updated['direct_domains'])
        self.assertNotEqual(policy['revision'], updated['revision'])

    def test_manual_vpn_override_preserved_when_domain_is_in_both_lists(self):
        self.active['direct_domains'] = ['blocked.max.ru']
        policy = build_catalog_test_policy(self.catalog, self.active)
        self.assertIn('blocked.max.ru', policy['direct_domains'])
        self.assertIn('blocked.max.ru', policy['vpn_domains'])

    def test_empty_broad_unknown_and_oversized_fail_closed(self):
        for entries in ([], [{'kind': 'suffix', 'value': 'ru'}], [{'kind': 'suffix', 'value': 'timeweb.cloud'}],
                        [{'kind': 'unknown', 'value': 'max.ru'}],
                        [{'kind': 'exact', 'value': f'host{index}.max.ru'} for index in range(2001)]):
            with self.subTest(entries=len(entries)), self.assertRaises(ValueError):
                build_catalog_test_policy({**self.catalog, 'entries': entries}, self.active)

    def test_default_endpoint_ignores_catalog_and_preserves_policy(self):
        from app.api.vpn import get_routing_policy
        with patch('app.services.routing_policy.load_policy', new=AsyncMock(return_value=self.active)), \
                patch('app.services.whitelist_catalog.load_catalog', side_effect=AssertionError('Default must not read catalog')):
            self.assertEqual(asyncio.run(get_routing_policy(db=None)), self.active)

    def test_explicit_profile_only_and_catalog_failure_is_503(self):
        from app.api.vpn import get_routing_policy
        from fastapi import HTTPException
        with patch('app.services.routing_policy.load_policy', new=AsyncMock(return_value=self.active)), \
                patch('app.services.whitelist_catalog.load_catalog', return_value=self.catalog):
            self.assertEqual(asyncio.run(get_routing_policy(profile='catalog-test', db=None))['profile'], 'catalog-test')
            with self.assertRaises(HTTPException) as unknown:
                asyncio.run(get_routing_policy(profile='unknown', db=None))
            self.assertEqual(unknown.exception.status_code, 400)
        with patch('app.services.routing_policy.load_policy', new=AsyncMock(return_value=self.active)), \
                patch('app.services.whitelist_catalog.load_catalog', return_value=None):
            with self.assertRaises(HTTPException) as unavailable:
                asyncio.run(get_routing_policy(profile='catalog-test', db=None))
            self.assertEqual(unavailable.exception.status_code, 503)


if __name__ == '__main__':
    unittest.main()
