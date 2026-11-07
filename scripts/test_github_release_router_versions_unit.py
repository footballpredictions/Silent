"""Router release badges must follow the same publication as release metadata."""
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.github_release_service import _patch_index_html_releases


HTML = '''<a id="pcDownload" href="old"></a><a id="androidDownload" href="old"></a>
<span id="pcVersion" data-version="1.0.171">v1.0.171</span><p id="pcMeta">old</p>
<span id="androidVersion" data-version="1.0.171">v1.0.171</span><p id="androidMeta">old</p>
<span class="version-badge" id="openwrtVersion" data-version="1.0.171">v1.0.171</span>
<script>const INLINE_FALLBACK = {};</script>'''


def releases(openwrt='1.0.172', keenetic='1.0.172'):
    result = {p: {'version': '1.0.172', 'size': 123,
                  'filename': p + '.bin', 'download_url': 'https://example.test/' + p}
              for p in ('pc', 'android')}
    for platform, version in (('openwrt', openwrt), ('keenetic', keenetic)):
        if version:
            result[platform] = {'version': version}
    return result


class RouterLandingReleaseTests(unittest.TestCase):
    def badge(self, html):
        return re.search(r'<span[^>]*id="openwrtVersion"[^>]*>[^<]*</span>', html)[0]

    def test_publication_updates_existing_static_badge_without_javascript(self):
        badge = self.badge(_patch_index_html_releases(HTML, releases()))
        self.assertIn('data-version="1.0.172"', badge)
        self.assertIn('data-openwrt-version="1.0.172"', badge)
        self.assertIn('data-keenetic-version="1.0.172"', badge)
        self.assertIn('>v1.0.172</span>', badge)

    def test_inline_offline_versions_include_both_router_platforms(self):
        html = _patch_index_html_releases(HTML, releases('1.0.173', '1.0.172'))
        fallback = html.split('const INLINE_FALLBACK = {', 1)[1]
        for platform, version in (('openwrt', '1.0.173'), ('keenetic', '1.0.172')):
            self.assertRegex(fallback, platform + r': \{\s*version: "' + re.escape(version) + '"')

    def test_mixed_versions_never_claim_the_other_platform_is_updated(self):
        badge = self.badge(_patch_index_html_releases(HTML, releases('1.0.173', '1.0.172')))
        self.assertIn('>OpenWrt v1.0.173 · Keenetic v1.0.172</span>', badge)
        self.assertIn('data-version=""', badge)

    def test_incomplete_metadata_preserves_existing_static_badge(self):
        badge = self.badge(_patch_index_html_releases(HTML, releases('1.0.173', None)))
        self.assertEqual(badge, self.badge(HTML))

    def test_repeated_publication_is_idempotent(self):
        first = _patch_index_html_releases(HTML, releases())
        self.assertEqual(_patch_index_html_releases(first, releases()), first)


if __name__ == '__main__':
    unittest.main()
