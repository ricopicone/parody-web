"""Ink on a translation read beside the English (task #825).

The reader shows each English page with its twin page beside it. Ink on the
twin page belongs to the same layer as the English ink — one reader, one
section, one version — kept per language, and goes wherever that layer goes:
saved, carried forward, and drawn into the side-by-side download.
"""
import io
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from parody_web.tests_printing import make_pdf_with_content
from parody_web.tests_twins import import_artifact, pdf_bytes, write_twin
from parody_web_annotate.models import InkLayer

PEN = {"tool": "pen", "color": "#ff0000", "opacity": 1, "d": "M10 10 L50 50 Z"}
BLUE = {"tool": "pen", "color": "#0000ff", "opacity": 1, "d": "M5 5 L40 40 Z"}


def pdf_from(resp):
    from pypdf import PdfReader
    return PdfReader(io.BytesIO(b"".join(resp.streaming_content)
                                if resp.streaming else resp.content))


class _TwinBook(TestCase):
    """A book with a German twin of all of alpha, and a signed-in reader."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.cache = base / "live", base / "cache"
        self.root.mkdir()
        self.settings = override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                                          PARODY_WEB_PRINT_CACHE=str(self.cache))
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        make_pdf_with_content(self.root / "print-book.pdf", 20)   # 200 x 200
        # twin pages 1..5 hold English 5..9, which is all of alpha
        self.book, _ = import_artifact(twin=[str(write_twin(
            self.root, content=pdf_bytes(5, 100), sbs_content=pdf_bytes(5, 300),
            sidecar={"abspages": [5, 6, 7, 8, 9],
                     "sections": {"one/alpha": [1, 5]}}))])
        self.reader = get_user_model().objects.create_user("reader", password="x")
        self.client = Client()
        self.client.force_login(self.reader)

    def _put(self, body):
        return self.client.put("/one/alpha/ink/", body, content_type="application/json")

    def _layer(self):
        return InkLayer.objects.get(user=self.reader)


class TwinInkTests(_TwinBook):

    # -- saving ---------------------------------------------------------------

    def test_twin_ink_round_trips(self):
        resp = self._put({"strokes": {"1": [PEN]}, "twins": {"de": {"2": [BLUE]}}})
        self.assertEqual(resp.status_code, 200)
        got = self.client.get("/one/alpha/ink/").json()
        self.assertEqual(got["twins"], {"de": {"2": [BLUE]}})
        self.assertEqual(got["strokes"], {"1": [PEN]})

    def test_a_save_that_says_nothing_of_twins_keeps_them(self):
        # a viewer bundle from before twins, still open in a tab, saves only
        # the English: that must not wipe the reader's notes on the translation
        self._put({"strokes": {"1": [PEN]}, "twins": {"de": {"2": [BLUE]}}})
        self._put({"strokes": {"1": [PEN, PEN]}})
        self.assertEqual(self._layer().twins, {"de": {"2": [BLUE]}})

    def test_a_save_replaces_only_the_languages_it_sends(self):
        # An English-only tab, or one showing the other language, saved every
        # language it had loaded: one opened before the reader wrote on the
        # Chinese erased those notes on its next save.
        self._put({"strokes": {}, "twins": {"de": {"2": [BLUE]}, "zh": {"1": [PEN]}}})
        self._put({"strokes": {"1": [PEN]}, "twins": {}})
        self.assertEqual(self._layer().twins, {"de": {"2": [BLUE]}, "zh": {"1": [PEN]}})
        self._put({"strokes": {}, "twins": {"de": {"3": [PEN]}}})
        self.assertEqual(self._layer().twins, {"de": {"3": [PEN]}, "zh": {"1": [PEN]}})

    def test_a_language_sent_empty_is_cleared(self):
        # erasing every stroke on the translation shown sends it as {}
        self._put({"strokes": {}, "twins": {"de": {"2": [BLUE]}, "zh": {"1": [PEN]}}})
        self._put({"strokes": {}, "twins": {"zh": {}}})
        self.assertEqual(self._layer().twins, {"de": {"2": [BLUE]}})

    def test_keys_are_replaced_per_language_too(self):
        self._put({"strokes": {}, "twins": {"de": {"1": [BLUE]}, "zh": {"1": [PEN]}},
                   "twin_keys": {"de": "k-de", "zh": "k-zh"}})
        self._put({"strokes": {}, "twins": {"de": {"1": [BLUE, BLUE]}}, "twin_keys": {"de": "k-de2"}})
        self.assertEqual(self._layer().twin_keys, {"de": "k-de2", "zh": "k-zh"})

    def test_malformed_twins_are_refused(self):
        for bad in ([], {"de": []}, {"de": {"1": "x"}}, "de"):
            with self.subTest(bad=bad):
                self.assertEqual(self._put({"strokes": {}, "twins": bad}).status_code, 400)

    def test_stroke_count_counts_the_translation(self):
        self._put({"strokes": {}, "twins": {"de": {"1": [BLUE, BLUE]}, "zh": {"3": [PEN]}}})
        self.assertEqual(self._layer().stroke_count, 3)

    def test_carry_forward_brings_the_translation_notes_too(self):
        InkLayer.objects.create(user=self.reader, book_slug="print-book",
                                section_key="al", slice_key="old", book_sha256="b" * 64,
                                pages=[5, 9], strokes={"1": [PEN]},
                                twins={"de": {"1": [BLUE]}})
        resp = self.client.post("/one/alpha/ink/carry-forward/", {"from": "old"},
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        new = InkLayer.objects.exclude(slice_key="old").get()
        self.assertEqual(new.twins, {"de": {"1": [BLUE]}})

    # -- the stage ------------------------------------------------------------

    def test_the_stage_always_knows_the_copy_with_notes(self):
        # Download and print move to it after the first save, so the stage
        # carries it before the reader has written anything
        html = self.client.get("/one/alpha/pdf/view/?twin=de").content.decode()
        self.assertIn('data-annotated-url="/one/alpha/pdf/annotated/?twin=de"', html)
        self.assertIn("data-ink-download", html)

    def test_the_stage_is_handed_the_paired_twin(self):
        html = self.client.get("/one/alpha/pdf/view/?twin=de").content.decode()
        self.assertIn('data-twin-url="/one/alpha/pdf/de/paired/?inline=1"', html)
        self.assertIn('data-twin-language="de"', html)
        self.assertIn('data-twin-name="Deutsch"', html)
        html = self.client.get("/one/alpha/pdf/view/?twin=en").content.decode()
        self.assertNotIn("data-twin-url", html)

    def test_an_older_version_has_no_twin_beside_it(self):
        # the twin pairs with the English the book serves now, not an archive
        InkLayer.objects.create(user=self.reader, book_slug="print-book",
                                section_key="al", slice_key="old", book_sha256="b" * 64,
                                pages=[5, 9], strokes={"1": [PEN]})
        html = self.client.get("/one/alpha/pdf/view/?twin=de&v=old").content.decode()
        self.assertIn('data-slice-key="old"', html)
        self.assertNotIn("data-twin-url", html)

    def test_download_and_print_follow_what_is_shown(self):
        html = self.client.get("/one/alpha/pdf/view/?twin=de").content.decode()
        # nothing annotated yet: the plain side-by-side sheets
        self.assertIn('href="/one/alpha/pdf/de/side-by-side/"', html)
        self.assertIn('data-print-url="/one/alpha/pdf/de/side-by-side/"', html)
        self._put({"strokes": {"1": [PEN]}})
        html = self.client.get("/one/alpha/pdf/view/?twin=de").content.decode()
        self.assertIn('data-download-url="/one/alpha/pdf/annotated/?twin=de"', html)
        self.assertIn('href="/one/alpha/pdf/annotated/?twin=de"', html)

    # -- the download ---------------------------------------------------------

    def test_the_side_by_side_download_carries_both_inks(self):
        self._put({"strokes": {"1": [PEN]}, "twins": {"de": {"1": [BLUE]}}})
        resp = self.client.get("/one/alpha/pdf/annotated/?twin=de")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("alpha-de-side-by-side-annotated.pdf", resp["Content-Disposition"])
        pdf = pdf_from(resp)
        self.assertEqual(len(pdf.pages), 5)
        # English page (200) then its twin page (101) on one sheet
        self.assertEqual([round(float(p.mediabox.width)) for p in pdf.pages],
                         [301, 302, 303, 304, 305])
        text = pdf.pages[0].get_contents().get_data()
        self.assertIn(b"1 0 0 rg", text)
        self.assertIn(b"0 0 1 rg", text)

    def test_the_twin_ink_lands_on_the_twin_page(self):
        import fitz
        self._put({"strokes": {"1": [PEN]}, "twins": {"de": {"1": [BLUE]}}})
        resp = self.client.get("/one/alpha/pdf/annotated/?twin=de")
        body = b"".join(resp.streaming_content) if resp.streaming else resp.content
        page = fitz.open(stream=body, filetype="pdf")[0]
        fills = {tuple(round(c, 2) for c in d["fill"]): d["rect"]
                 for d in page.get_drawings() if d.get("fill")}
        # top-left origin, as the reader stores ink: the English pen where it
        # was drawn, the translation's 200pt across, on the twin page
        self.assertEqual(tuple(round(v) for v in fills[(1.0, 0.0, 0.0)]), (10, 10, 50, 50))
        self.assertEqual(tuple(round(v) for v in fills[(0.0, 0.0, 1.0)]), (205, 5, 240, 40))

    def test_a_used_margin_widens_the_sheet_by_half_the_english_page(self):
        self._put({"strokes": {"1": [PEN]}, "pads": {"1": [PEN]}})
        pdf = pdf_from(self.client.get("/one/alpha/pdf/annotated/?twin=de"))
        self.assertEqual(round(float(pdf.pages[0].mediabox.width)), 200 + 101 + 100)
        self.assertEqual(round(float(pdf.pages[1].mediabox.width)), 200 + 102)

    def test_an_unknown_translation_is_the_english_download(self):
        self._put({"strokes": {"1": [PEN]}})
        resp = self.client.get("/one/alpha/pdf/annotated/?twin=zh")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(round(float(pdf_from(resp).pages[0].mediabox.width)), 200)


class TranslationOnlyInkTests(_TwinBook):
    """Ink on the translation alone must not stand in for English notes: the
    whole-book PDF, carry-forward and the English download are English."""

    def setUp(self):
        super().setUp()
        from parody_web import printing
        self.current = printing.slice_key_for(self.book, self.book.sections.get(slug="alpha"))
        self.old = InkLayer.objects.create(
            user=self.reader, book_slug="print-book", section_key="al", slice_key="old",
            book_sha256="b" * 64, pages=[5, 9], strokes={"1": [PEN]},
            twins={"zh": {"3": [PEN]}, "de": {"2": [PEN]}})
        self._put({"strokes": {}, "twins": {"de": {"1": [BLUE]}}})   # newer, German only
        self.new = InkLayer.objects.get(slice_key=self.current)

    def test_the_book_pdf_keeps_the_older_english_notes(self):
        from django.test import RequestFactory

        from parody_web_annotate import bookink
        request = RequestFactory().get("/")
        request.user = self.reader
        pages, _, _ = bookink.plan_book_overlay(request, self.book)
        self.assertEqual(pages, {5: [PEN]})

    def test_carry_forward_brings_the_english_and_keeps_the_translation_here(self):
        resp = self.client.post("/one/alpha/ink/carry-forward/", {"from": "old"},
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.new.refresh_from_db()
        self.assertEqual(self.new.strokes, {"1": [PEN]})
        # German was drawn here already and stays; Chinese comes over
        self.assertEqual(self.new.twins, {"de": {"1": [BLUE]}, "zh": {"3": [PEN]}})

    def test_the_offer_to_bring_notes_forward_still_stands(self):
        html = self.client.get("/one/alpha/pdf/view/?twin=en").content.decode()
        self.assertIn("data-ink-carry", html)

    def test_the_english_download_does_not_promise_notes(self):
        html = self.client.get("/one/alpha/pdf/view/?twin=en").content.decode()
        self.assertNotIn('href="/one/alpha/pdf/annotated/', html)
        html = self.client.get("/one/alpha/pdf/view/?twin=de").content.decode()
        self.assertIn('href="/one/alpha/pdf/annotated/?twin=de"', html)



class TwinKeyTests(_TwinBook):
    """Each language's ink carries the key of the translated pages it was
    written over (printing.twin_paired_key)."""

    def test_the_stage_is_handed_the_key(self):
        from parody_web import printing
        alpha = self.book.sections.get(slug="alpha")
        key = printing.twin_paired_key(self.book, alpha, self.book.twins.get())
        html = self.client.get("/one/alpha/pdf/view/?twin=de").content.decode()
        self.assertIn(f'data-twin-key="{key}"', html)

    def test_keys_round_trip_with_the_ink(self):
        self._put({"strokes": {}, "twins": {"de": {"1": [BLUE]}}, "twin_keys": {"de": "k1"}})
        got = self.client.get("/one/alpha/ink/").json()
        self.assertEqual(got["twin_keys"], {"de": "k1"})
        # a save from before translations says nothing of either, and keeps both
        self._put({"strokes": {"1": [PEN]}})
        self.assertEqual(self._layer().twin_keys, {"de": "k1"})

    def test_malformed_keys_are_refused(self):
        for bad in ([], {"de": 3}, "k"):
            with self.subTest(bad=bad):
                resp = self._put({"strokes": {}, "twins": {}, "twin_keys": bad})
                self.assertEqual(resp.status_code, 400)

    def test_carry_forward_keeps_each_languages_key_with_its_ink(self):
        from parody_web import printing
        current = printing.slice_key_for(self.book, self.book.sections.get(slug="alpha"))
        InkLayer.objects.create(
            user=self.reader, book_slug="print-book", section_key="al", slice_key="old",
            book_sha256="b" * 64, pages=[5, 9], strokes={"1": [PEN]},
            twins={"de": {"1": [PEN]}, "zh": {"1": [PEN]}}, twin_keys={"de": "kd", "zh": "kz"})
        self._put({"strokes": {}, "twins": {"de": {"1": [BLUE]}}, "twin_keys": {"de": "now"}})
        self.client.post("/one/alpha/ink/carry-forward/", {"from": "old"},
                         content_type="application/json")
        layer = InkLayer.objects.get(slice_key=current)
        self.assertEqual(layer.twin_keys, {"de": "now", "zh": "kz"})


@override_settings(PARODY_WEB_ACCESS_POLICY="parody_web.tests_twins.KeyTwinPolicy")
class KeyTwinDownloadTests(_TwinBook):
    """The annotated side-by-side download is what the reader showed: the
    translation filled in for a reader who has done the section (task #865)."""

    def setUp(self):
        from parody_web.tests_twins import write_key

        super().setUp()
        sidecar = self.root / "print-book-de.twin.json"
        write_key(self.root, sidecar, pdf_bytes(5, 500))
        self.book, _ = import_artifact(twin=[str(sidecar)])
        self.book.sections.filter(slug="alpha").update(
            key_html='<p><span class="cloze-key">x</span></p>')

    def _sheets(self):
        self._put({"strokes": {"1": [PEN]}, "twins": {"de": {"1": [BLUE]}}})
        resp = self.client.get("/one/alpha/pdf/annotated/?twin=de")
        self.assertEqual(resp.status_code, 200)
        return resp, [round(float(p.mediabox.width)) for p in pdf_from(resp).pages]

    def test_a_reader_who_has_done_it_gets_the_translation_filled(self):
        self.client.force_login(get_user_model().objects.create_user("done", password="x"))
        resp, widths = self._sheets()
        self.assertEqual(widths, [701, 702, 703, 704, 705])  # English 200 + key 501..
        self.assertIn("no-store", resp["Cache-Control"])

    def test_anyone_else_gets_it_blank(self):
        _, widths = self._sheets()
        self.assertEqual(widths, [301, 302, 303, 304, 305])
