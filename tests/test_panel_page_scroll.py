"""Mobile page pane must be a real scroll container (flex min-height:0)."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
CSS = (ROOT / "web/css/app.css").read_text(encoding="utf-8")


class PanelPageScrollTests(unittest.TestCase):
    def test_css_makes_page_a_flex_scroll_pane(self):
        self.assertRegex(CSS, r"\.stage\s*\{[^}]*min-height:\s*0")
        self.assertRegex(CSS, r"\.page\s*\{[^}]*min-height:\s*0")
        self.assertRegex(CSS, r"\.page\s*\{[^}]*overflow-y:\s*auto")
        self.assertRegex(CSS, r"\.app\s*\{[^}]*100dvh")
        self.assertIn("touch-action: pan-y", CSS)

    @unittest.skipUnless(NODE, "Node required for optional Playwright layout probe")
    def test_page_scrolls_under_short_mobile_viewport(self):
        html = f"""<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{CSS}</style></head>
<body><div id="app" class="app"><div class="shell">
<main class="stage"><div class="topbar"></div>
<div class="page" id="page"><div class="page-inner">
{"<div class='session'>row</div>" * 40}
</div></div></main></div></div></body></html>"""
        runner = r"""
let chromium;
try { ({ chromium } = require('playwright')); }
catch (err) { console.error('NO_PLAYWRIGHT'); process.exit(3); }
(async () => {
  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:390,height:320}, isMobile:true, hasTouch:true});
  await page.goto(process.argv[1], {waitUntil:'load'});
  const result = await page.evaluate(() => {
    const el = document.getElementById('page');
    const style = getComputedStyle(el);
    return {
      ok: el.scrollHeight > el.clientHeight + 20
        && (style.overflowY === 'auto' || style.overflowY === 'scroll')
        && el.clientHeight > 0 && el.clientHeight < 320,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      overflowY: style.overflowY,
    };
  });
  console.log(JSON.stringify(result));
  await browser.close();
  process.exit(result.ok ? 0 : 1);
})().catch((err) => { console.error(String(err)); process.exit(2); });
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scroll.html"
            path.write_text(html, encoding="utf-8", newline="\n")
            script = Path(directory) / "check.cjs"
            script.write_text(runner, encoding="utf-8", newline="\n")
            result = subprocess.run(
                [NODE, str(script), path.as_uri()],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                cwd=str(ROOT.parent),
            )
            if result.returncode == 3 or "NO_PLAYWRIGHT" in (result.stderr + result.stdout):
                self.skipTest("playwright not installed for layout probe")
            self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
            payload = re.search(r"\{.*\}", result.stdout)
            self.assertIsNotNone(payload)
            self.assertIn('"ok":true', payload.group(0).replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
