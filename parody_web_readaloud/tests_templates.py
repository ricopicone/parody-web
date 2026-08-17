"""Shadowing the annotator's head partial, without silently losing it."""
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
ANNOTATE_HEAD = (ROOT / "parody_web_annotate" / "templates" / "parody_web"
                 / "_pdf_view_head.html")
MY_HEAD = (ROOT / "parody_web_readaloud" / "templates" / "parody_web"
           / "_pdf_view_head.html")

# What the annotator's head partial contained when read-along copied it.
PINNED = ("{% load static parody_web_annotate %}{% ink_context as ink %}"
          "<link rel=\"stylesheet\" "
          "href=\"{% static 'parody_web_annotate/css/annotate.css' %}\">")


class HeadShadowTests(SimpleTestCase):
    def test_the_annotators_head_has_not_drifted(self):
        """Read-along shadows this file, so a change here must not go unnoticed.

        Django resolves app templates by INSTALLED_APPS order and only the
        first wins, so if the annotator adds something to its head and
        read-along does not copy it across, that something silently stops
        being emitted.
        """
        self.assertEqual(ANNOTATE_HEAD.read_text().strip(), PINNED,
                         "parody_web_annotate's head partial changed — copy "
                         "the change into parody_web_readaloud's shadow of it "
                         "and update PINNED here.")

    def test_the_shadow_re_emits_the_annotators_stylesheet(self):
        body = MY_HEAD.read_text()
        self.assertIn("parody_web_annotate/css/annotate.css", body)

    def test_the_shadow_loads_read_along(self):
        body = MY_HEAD.read_text()
        self.assertIn("parody_web_readaloud/css/readalong.css", body)
        self.assertIn("parody_web_readaloud/js/readalong.js", body)
