"""What the wheel must carry.

Anything missing from package-data is silently absent from the wheel: the app
installs, the mode never appears, and nothing says why. Learned the hard way —
see the parody-web-package-data-static-gotcha note.
"""
import tomllib
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent


def _pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


class PackagingTests(SimpleTestCase):
    def test_static_and_templates_are_declared(self):
        patterns = _pyproject()["tool"]["setuptools"]["package-data"]
        mine = patterns.get("parody_web_readaloud", [])
        self.assertIn("static/parody_web_readaloud/js/*.js", mine)
        self.assertIn("static/parody_web_readaloud/css/*.css", mine)
        self.assertIn("templates/parody_web/*.html", mine)

    def test_the_readalong_extra_names_its_dependencies(self):
        extra = _pyproject()["project"]["optional-dependencies"]["readalong"]
        joined = " ".join(extra)
        self.assertIn("boto3", joined)
        self.assertIn("PyMuPDF", joined)

    def test_the_bundle_is_committed(self):
        bundle = (ROOT / "parody_web_readaloud" / "static"
                  / "parody_web_readaloud" / "js" / "readalong.js")
        self.assertTrue(bundle.exists(),
                        "run `npm run build` and commit the bundle")

    def test_the_stylesheet_is_committed(self):
        css = (ROOT / "parody_web_readaloud" / "static"
               / "parody_web_readaloud" / "css" / "readalong.css")
        self.assertTrue(css.exists())

    def test_the_bundle_does_not_re_ship_pdfjs(self):
        """Read-along reads the annotator's DOM rather than its objects; if
        pdf.js has been pulled in, that decoupling has been lost."""
        bundle = (ROOT / "parody_web_readaloud" / "static"
                  / "parody_web_readaloud" / "js" / "readalong.js")
        self.assertLess(bundle.stat().st_size, 100_000)
