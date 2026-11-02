"""map_clozes: where the blanks are, for every blanked book, at no cost."""
import json
import tempfile
from io import StringIO
from pathlib import Path

import fitz
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from parody_web_readaloud.models import ClozeMap, ReadAlongTrack

KEY_HTML = ('<p>at a fixed <span class="cloze-key">sampling rate</span>'
            ', which sets</p>')


def _book_pdf(path, drop=0):
    """Twenty pages, each different; page 5 — where the ARTIFACT's section
    `al` starts — holds a sentence with one blank in it."""
    doc = fitz.open()
    for i in range(20):
        page = doc.new_page(width=300, height=100)
        page.insert_text((10, 90), f"page {i + 1}", fontsize=8)
        if i == 4:
            page.insert_text((10, 20 + drop), "at a fixed", fontsize=10)
            page.insert_text((95, 20 + drop), ", which sets", fontsize=10)
            page.draw_line(fitz.Point(58, 22 + drop), fitz.Point(92, 22 + drop),
                           width=0.6)
    doc.save(path)
    doc.close()


class MapClozesTests(TestCase):
    def setUp(self):
        from parody_web.tests_printing import ARTIFACT, import_artifact
        self.ARTIFACT, self.import_artifact = ARTIFACT, import_artifact
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key_artifact = self.root / "key.json"
        self.key_artifact.write_text(json.dumps({"chapters": [{
            "slug": "one", "sections": [
                {"slug": "alpha", "hash": "al", "html": KEY_HTML}]}]}))
        self._publish(drop=0, sha="c")

    def _publish(self, drop, sha):
        _book_pdf(self.root / "print-book.pdf", drop=drop)
        data = json.loads(json.dumps(self.ARTIFACT))
        data["print"]["sha256"] = sha * 64
        self.book = self.import_artifact(data)

    def _run(self, *args, **kwargs):
        out, err = StringIO(), StringIO()
        kwargs.setdefault("key_artifact", str(self.key_artifact))
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            call_command("map_clozes", self.book.slug, *args,
                         stdout=out, stderr=err, **kwargs)
        return out.getvalue(), err.getvalue()

    def test_the_blank_is_mapped_where_the_student_writes(self):
        out, _ = self._run(section="al")
        self.assertIn("mapped al: 1 blanks", out)
        row = ClozeMap.objects.get(section_key="al")
        self.assertTrue(row.slice_key)
        [box] = row.clozes
        self.assertEqual(box["page"], 0, "page 0 of the section's own PDF")
        self.assertLess(box["x0"], 58 + 1)
        self.assertGreater(box["x1"], 92 - 1)

    def test_no_audio_and_no_track_come_of_it(self):
        self._run(section="al")
        self.assertEqual(ReadAlongTrack.objects.count(), 0)

    def test_a_mapped_pagination_is_not_parsed_again(self):
        self._run(section="al")
        out, _ = self._run(section="al")
        self.assertIn("0 mapped, 1 unchanged", out)

    def test_a_reflow_maps_the_new_pages_and_keeps_the_old(self):
        """The old map still measures ink written on the old pages."""
        self._run(section="al")
        self._publish(drop=30, sha="d")
        out, _ = self._run(section="al")
        self.assertIn("mapped al", out)
        rows = list(ClozeMap.objects.filter(section_key="al").order_by("created_at"))
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].slice_key, rows[1].slice_key)
        self.assertAlmostEqual(rows[1].clozes[0]["y0"] - rows[0].clozes[0]["y0"],
                               30, delta=0.5)

    def test_a_section_with_no_page_range_is_skipped(self):
        out, _ = self._run()
        self.assertFalse(ClozeMap.objects.filter(section_key="be").exists())
        self.assertIn("skipped", out)

    def test_a_section_without_key_html_is_not_guessed_from_the_blank_build(self):
        _, err = self._run(section="li")
        self.assertIn("no key-mode html", err)
        self.assertFalse(ClozeMap.objects.filter(section_key="li").exists())

    def test_drafts_are_not_mapped(self):
        self.book.sections.filter(slug="alpha").update(draft=True)
        with self.assertRaises(CommandError):
            self._run(section="al")

    def test_an_unknown_book_is_an_error(self):
        with self.assertRaises(CommandError), \
                override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            call_command("map_clozes", "nosuchbook", stdout=StringIO())
