"""The shipped router panels share screens/styles; allow only named platform adapters."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
OPENWRT=ROOT.parent/'openwrt/web'

@unittest.skipUnless(OPENWRT.is_dir(),'Optional sibling OpenWrt checkout required')
class RouterUIParity(unittest.TestCase):
    def test_all_shipped_screens_and_styles_match_openwrt(self):
        own=ROOT/'agent/web'
        self.assertEqual({p.relative_to(own) for p in own.rglob('*') if p.is_file()},
                         {p.relative_to(OPENWRT) for p in OPENWRT.rglob('*') if p.is_file()})
        for original in OPENWRT.rglob('*'):
            if not original.is_file():continue
            relative=original.relative_to(OPENWRT)
            with self.subTest(asset=relative):
                source=original.read_text(encoding='utf-8').replace('OpenWrt','Keenetic').replace('openwrt','keenetic')
                target=(own/relative).read_text(encoding='utf-8')
                def normalized(text):
                    text=re.sub(r'1\.0\.\d+-r\d+','CACHE_REVISION',text)
                    text=text.replace('/* uhttpd briefly restarts during installation; keep polling */','/* PANEL_RESTART */')
                    text=text.replace('/* Agent restarts during installation; keep polling. */','/* PANEL_RESTART */')
                    # OpenWrt CGI inserts this same legacy promo default server-side.
                    text=text.replace('{ code, plan_type: "monthly" }','{ code }')
                    return text
                self.assertEqual(normalized(source),normalized(target))
