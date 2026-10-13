"""The shared policy contract, including imported router rules and precedence."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.routing_policy import build_policy, normalize_domains
from app.services.routing_policy_defaults import DIRECT_DOMAINS, VPN_DOMAINS


class PolicyTests(unittest.TestCase):
    def test_urls_unicode_subdomains_and_duplicates(self):
        self.assertEqual(normalize_domains(['https://3.shkolkovo.online/path?q=1', '*.VK.COM', 'vk.com', 'РФ']),
                         ['3.shkolkovo.online', 'vk.com', 'xn--p1ai'])

    def test_reject_unusable_domains_and_shell_injection(self):
        for value in ['x;reboot', 'a..ru', '-x.ru', '192.168.1.1', 'ftp://site.ru/',
                      'https://user:password@site.ru/', 'x/ru', 'a' * 64 + '.ru', 'localhost']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_domains([value])

    def test_revision_changes_only_when_policy_changes(self):
        first = build_policy(['ru', 'ozon.ru'], ['gdz-raketa.ru'])
        same = build_policy(['ozon.ru', 'ru', 'ru'], ['https://gdz-raketa.ru/'])
        self.assertEqual(first, same)
        self.assertNotEqual(first['revision'], build_policy(['ru'], ['gdz-raketa.ru'])['revision'])
        self.assertEqual(first['schema_version'], 1)
        self.assertEqual(first['refresh_seconds'], 300)

    def test_current_rules_migrated_without_loss(self):
        for name in ['max.ru', 'oneme.ru', 'wbstatic.net', 'flashscore.com', 'lsapp.eu', 'shkolkovo.online', 'ru']:
            self.assertIn(name, DIRECT_DOMAINS)
        self.assertIn('gdz-raketa.ru', VPN_DOMAINS)
        policy = build_policy(DIRECT_DOMAINS, VPN_DOMAINS)
        self.assertTrue(len(policy['revision']) == 64)

    def test_empty_lists_are_valid(self):
        self.assertEqual(build_policy([], [])['direct_domains'], [])


if __name__ == '__main__':
    unittest.main()
