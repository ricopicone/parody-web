"""The GIF figure player ships, and every book page loads it.

Its behaviour is tested under `node --test` (assets/gifplayer/). What can only
break here is delivery, and delivery fails silently: a static file missing
from package-data is absent from the wheel, the page loads, and the figures
just go on looping with no controls.
"""
import re
import tomllib
from pathlib import Path

from django.test import TestCase

from parody_web.tests import _import

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "parody_web" / "static" / "parody_web" / "js" / "gifplayer.js"
BASE = ROOT / "parody_web" / "templates" / "parody_web" / "base.html"


class GifPlayerDeliveryTests(TestCase):
    def test_the_js_directory_is_in_package_data(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        patterns = data["tool"]["setuptools"]["package-data"]["parody_web"]
        self.assertIn("static/parody_web/js/*.js", patterns)

    def test_the_bundle_is_committed_and_small(self):
        self.assertTrue(BUNDLE.exists(), "run `npm run build` and commit the bundle")
        self.assertLess(BUNDLE.stat().st_size, 30_000)

    def test_base_loads_it_as_a_module(self):
        base = BASE.read_text(encoding="utf-8")
        self.assertRegex(
            base, r"<script type=\"module\" src=\"\{% static 'parody_web/js/gifplayer\.js' %\}\"></script>")

    def test_a_section_page_carries_it(self):
        _import()
        r = self.client.get("/hardware/specific-t1/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(re.search(r'<script type="module" src="[^"]*parody_web/js/gifplayer[^"]*\.js"',
                                  r.content.decode()))
