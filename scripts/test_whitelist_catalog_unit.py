import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.whitelist_catalog import SOURCES, FetchResult, Source, catalog_summary, fetch_source, load_catalog, parse_source, refresh_catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.now = datetime(2026, 10, 24, tzinfo=timezone.utc)

    def tearDown(self):
        self.temporary.cleanup()

    def fetch(self, source, etag):
        if source.format == 'plain':
            return FetchResult(200, b'max.ru\napi.max.ru\n', 'first')
        return FetchResult(200, json.dumps({'version': 3, 'rules': [{'domain_suffix': ['max.ru']}]}).encode(), 'second')

    def test_plain_hosts_are_exact_not_silently_expanded_to_suffix(self):
        entries, rejected = parse_source(SOURCES[0], b'API.MAX.RU\nmax.ru.\n')
        self.assertEqual(entries, [{'kind': 'exact', 'value': 'api.max.ru'}, {'kind': 'exact', 'value': 'max.ru'}])
        self.assertEqual(rejected, [])

    def test_preserves_json_exact_and_suffix_semantics(self):
        body = json.dumps({'version': 3, 'rules': [{'domain': ['api.max.ru'], 'domain_suffix': ['max.ru']}]}).encode()
        entries, _ = parse_source(SOURCES[1], body)
        self.assertEqual(entries, [{'kind': 'exact', 'value': 'api.max.ru'}, {'kind': 'suffix', 'value': 'max.ru'}])

    def test_quarantines_countrywide_cloud_ip_and_subscription_rules(self):
        body = b'max.ru\nru\n7.64.0.0/12\nvless://secret@example.com\n*.ru\nlocalhost\n'
        entries, rejected = parse_source(SOURCES[0], body)
        self.assertEqual(entries, [{'kind': 'exact', 'value': 'max.ru'}])
        self.assertEqual(len(rejected), 5)
        body = json.dumps({'version': 3, 'rules': [{'domain_suffix': ['max.ru', 'spb.ru', 'yandexcloud.net']}]}).encode()
        entries, rejected = parse_source(SOURCES[1], body)
        self.assertEqual(entries, [{'kind': 'suffix', 'value': 'max.ru'}])
        self.assertEqual(len(rejected), 2)
        self.assertNotIn('secret', json.dumps(rejected))

    def test_rejects_conditional_and_empty_sources(self):
        for body in (b'<html>Access denied</html>', b'', b'ru\n'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_source(SOURCES[0], body)
        with self.assertRaises(ValueError):
            parse_source(SOURCES[1], b'{"version":3,"rules":[{"domain_suffix":["max.ru"],"invert":true}]}')

    def test_collects_provenance_without_claiming_reachability(self):
        catalog = refresh_catalog(self.directory, self.fetch, self.now)
        self.assertEqual(len(catalog['entries']), 3)
        self.assertTrue(all(entry['evidence'] == 'source_listed' for entry in catalog['entries']))
        self.assertFalse(catalog['auto_publish'])
        self.assertEqual(catalog['reachability'], 'not_measured')
        self.assertEqual(catalog['sources'][SOURCES[0].id]['upstream_updated_at'], None)
        self.assertEqual(catalog_summary(catalog)['source_count'], 2)

    def test_timestamp_changes_do_not_change_content_revision(self):
        first = refresh_catalog(self.directory, self.fetch, self.now)
        second = refresh_catalog(self.directory, self.fetch, datetime(2026, 10, 25, tzinfo=timezone.utc))
        self.assertEqual(first['revision'], second['revision'])

    def test_not_modified_uses_cache_and_sends_etag(self):
        first = refresh_catalog(self.directory, self.fetch, self.now)
        seen = []
        def unchanged(source, etag):
            seen.append(etag)
            return FetchResult(304, b'', etag)
        second = refresh_catalog(self.directory, unchanged, self.now)
        self.assertEqual(first['entries'], second['entries'])
        self.assertEqual(seen, ['first', 'second'])

    def test_failed_refresh_preserves_last_good_entries(self):
        first = refresh_catalog(self.directory, self.fetch, self.now)
        def failed(source, etag):
            raise TimeoutError('upstream unavailable')
        second = refresh_catalog(self.directory, failed, self.now)
        self.assertEqual(first['entries'], second['entries'])
        self.assertEqual(first['revision'], second['revision'])
        self.assertTrue(all(source['status'] == 'stale' for source in second['sources'].values()))

    def test_304_without_cache_is_not_accepted(self):
        catalog = refresh_catalog(self.directory, lambda source, etag: FetchResult(304, b''), self.now)
        self.assertEqual(catalog['entries'], [])
        self.assertTrue(all(source['status'] == 'unavailable' for source in catalog['sources'].values()))

    def test_mass_change_is_quarantined_and_snapshot_survives(self):
        def initial(source, etag):
            if source.format == 'plain':
                return FetchResult(200, '\n'.join(f'host{index}.max.ru' for index in range(30)).encode())
            return self.fetch(source, etag)
        first = refresh_catalog(self.directory, initial, self.now)
        second = refresh_catalog(self.directory, self.fetch, self.now)
        self.assertEqual(first['entries'], second['entries'])
        self.assertEqual(second['sources'][SOURCES[0].id]['error'], 'ExcessiveSourceChange')

    def test_retains_previous_content_snapshot_when_sources_change(self):
        first = refresh_catalog(self.directory, self.fetch, self.now)
        def changed(source, etag):
            result = self.fetch(source, etag)
            return FetchResult(result.status, result.body.replace(b'max.ru', b'ya.ru'))
        second = refresh_catalog(self.directory, changed, self.now)
        self.assertNotEqual(first['revision'], second['revision'])
        snapshot = self.directory / 'history' / (first['revision'] + '.json')
        self.assertEqual(json.loads(snapshot.read_text())['revision'], first['revision'])

    def test_source_urls_are_fixed_and_ssrf_cannot_be_configured(self):
        for url in ('http://127.0.0.1/', 'https://example.com/', 'https://raw.githubusercontent.com/other/data/main/list.txt'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                fetch_source(Source('custom', url, 'plain'))

    def test_oversized_sources_rejected_before_parsing(self):
        with self.assertRaises(ValueError):
            parse_source(SOURCES[0], b'x' * (2 * 1024 * 1024 + 1))

    def test_failed_atomic_replace_keeps_last_good_catalog(self):
        first = refresh_catalog(self.directory, self.fetch, self.now)
        with patch('app.services.whitelist_catalog.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                refresh_catalog(self.directory, self.fetch, self.now)
        self.assertEqual(load_catalog(self.directory), first)

    def test_refresh_never_modifies_active_policy_file(self):
        active = self.directory / 'routing-policy.json'
        active.write_bytes(b'{"direct_domains":["max.ru"],"vpn_domains":["gdz.ru"]}')
        before = active.read_bytes()
        refresh_catalog(self.directory, self.fetch, self.now)
        self.assertEqual(active.read_bytes(), before)

    def test_parallel_refresh_cannot_replace_in_progress_snapshot(self):
        started = Event()
        release = Event()
        def blocked(source, etag):
            started.set()
            self.assertTrue(release.wait(5))
            return self.fetch(source, etag)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(refresh_catalog, self.directory, blocked, self.now)
            try:
                self.assertTrue(started.wait(5))
                with self.assertRaises(OSError):
                    refresh_catalog(self.directory, self.fetch, self.now)
            finally:
                release.set()
            self.assertEqual(len(future.result()['entries']), 3)


if __name__ == '__main__':
    unittest.main()
