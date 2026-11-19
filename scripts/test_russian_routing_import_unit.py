"""A server import must improve legacy-client coverage without widening exact rules."""
import io
import sys
import tarfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.routing_policy import build_policy, normalize_domains
from app.services.russian_routing_import import import_geosite, merge_russian_policy


def archive(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as source:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo('snapshot/data/'+name)
            info.size = len(data)
            source.addfile(info, io.BytesIO(data))
    return output.getvalue()


class RussianImportTests(unittest.TestCase):
    def test_russian_country_zones_supported_but_arbitrary_tlds_rejected(self):
        self.assertEqual(normalize_domains(['МОСКВА', 'рус', 'moscow', 'tatar']),
                         ['moscow', 'tatar', 'xn--80adxhks', 'xn--p1acf'])
        for name in ('com', 'net', 'org', 'localhost'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                normalize_domains([name])

    def test_missing_cdek_and_otzovik_reach_existing_clients(self):
        snapshot = import_geosite(archive({'category-ru':'ru\ninclude:cdek\notzovik.com\n', 'cdek':'cdek.shopping\n'}))
        current = build_policy(['ru', 'old-service.net'], ['gdz.ru'])
        policy, report = merge_russian_policy(current, snapshot)
        self.assertIn('cdek.shopping', policy['direct_domains'])
        self.assertIn('otzovik.com', policy['direct_domains'])
        self.assertEqual(policy['vpn_domains'], current['vpn_domains'])
        self.assertTrue(set(current['direct_domains']).issubset(policy['direct_domains']))
        self.assertEqual(set(policy), set(current))
        self.assertEqual(report['added_domains'], ['cdek.shopping', 'otzovik.com'])

    def test_exact_regex_shared_hosting_and_vpn_rules_not_promoted(self):
        snapshot = import_geosite(archive({'category-ru':
            'full:one.shared.net\nregexp:.*\\.example\\.com$\nyandexcloud.net\nngenix.net\ngdz.ru\napi.gdz.ru\nservice.ru\n'}))
        policy, report = merge_russian_policy(build_policy(['ru'], ['gdz.ru']), snapshot)
        self.assertEqual(policy['direct_domains'], ['ru'])
        self.assertEqual(policy['vpn_domains'], ['gdz.ru'])
        self.assertEqual(report['exact_rules_not_promoted'], ['one.shared.net'])
        self.assertEqual(report['regex_rules_skipped'], 1)
        self.assertEqual(report['shared_suffixes_skipped'], ['ngenix.net','yandexcloud.net'])

    def test_attributes_includes_and_country_zone_opt_in(self):
        snapshot = import_geosite(archive({'category-ru':'include:company @ru\nmoscow\n',
                                          'company':'service.net @ru\nforeign.net @cn\n'}))
        policy, _ = merge_russian_policy(build_policy(['ru'], []), snapshot)
        self.assertEqual(policy['direct_domains'], ['ru','service.net'])
        expanded, _ = merge_russian_policy(policy, snapshot, include_country_zones=True)
        self.assertIn('moscow', expanded['direct_domains'])

    def test_cycles_unknown_directives_and_missing_includes_fail_closed(self):
        for files in ({'category-ru':'include:missing'}, {'category-ru':'include:cycle','cycle':'include:category-ru'},
                      {'category-ru':'unexpected:service.net'}):
            with self.subTest(files=files), self.assertRaises(ValueError):
                import_geosite(archive(files))

    def test_parent_rules_compact_new_entries_without_removing_manual_entries(self):
        snapshot = import_geosite(archive({'category-ru':'service.net\napi.service.net\n'}))
        current = build_policy(['old.net','img.old.net'], [])
        policy, _ = merge_russian_policy(current, snapshot)
        self.assertEqual(policy['direct_domains'], ['img.old.net','old.net','service.net'])
        repeated, report = merge_russian_policy(policy, snapshot)
        self.assertEqual(policy, repeated)
        self.assertEqual(report['added_domains'], [])

    def test_legacy_client_limit_is_not_silently_truncated(self):
        snapshot = import_geosite(archive({'category-ru':'new.net'}))
        current = build_policy([f'd{i}.net' for i in range(2000)], [])
        with self.assertRaises(ValueError):
            merge_russian_policy(current, snapshot)


if __name__ == '__main__':
    unittest.main()
