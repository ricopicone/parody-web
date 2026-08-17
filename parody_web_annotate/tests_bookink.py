"""The whole-book overlay: where each note lands, and what is refused.

This is what a student prints and takes into an exam, so a note on the wrong
page is the failure that matters. Most of these tests exist to make that
impossible rather than unlikely.
"""
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from parody_web.tests_printing import import_artifact, make_pdf_with_content
from parody_web_annotate import bookink
from parody_web_annotate.models import InkLayer


def stroke(d="M1 1 L9 9 Z", color="#000000"):
    return {"tool": "pen", "color": color, "opacity": 1, "d": d}


class PlanBookOverlayTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.reader = get_user_model().objects.create_user("reader", password="x")
        self.client = Client()
        self.client.force_login(self.reader)
        # alpha is book pages [5, 9]; lead-in is [3, 5]
        self.alpha = self.book.sections.get(slug="alpha")

    def _request(self):
        from django.test import RequestFactory
        request = RequestFactory().get("/")
        request.user = self.reader
        return request

    def _layer(self, section_key, pages, strokes, **kw):
        return InkLayer.objects.create(
            user=self.reader, book_slug=self.book.slug, edition_id="",
            section_key=section_key, slice_key=kw.get("slice_key", "a" * 64),
            book_sha256=kw.get("book_sha256", "c" * 64),
            pages=pages, strokes=strokes)

    def test_a_note_lands_on_the_book_page_it_belongs_to(self):
        """Page 1 of a section starting at book page 5 is book page 5."""
        self._layer("al", [5, 9], {"1": [stroke()]})
        pages, pads, skipped = bookink.plan_book_overlay(self._request(), self.book)
        self.assertEqual(list(pages), [5])
        self.assertEqual(skipped, [])

    def test_notes_further_into_a_section_are_offset(self):
        self._layer("al", [5, 9], {"1": [stroke("A")], "3": [stroke("B")]})
        pages, _pads, _ = bookink.plan_book_overlay(self._request(), self.book)
        self.assertEqual(sorted(pages), [5, 7])
        self.assertEqual(pages[7][0]["d"], "B")

    def test_two_sections_sharing_a_page_both_draw_on_it(self):
        """Sections overlap by a page by design; both sets of notes belong."""
        self._layer("li", [3, 5], {"3": [stroke("lead-in")]})   # book page 5
        self._layer("al", [5, 9], {"1": [stroke("alpha")]})     # book page 5
        pages, _pads, _ = bookink.plan_book_overlay(self._request(), self.book)
        self.assertEqual(list(pages), [5])
        self.assertEqual({s["d"] for s in pages[5]}, {"lead-in", "alpha"})

    def test_only_the_newest_notes_for_a_section_are_used(self):
        old = self._layer("al", [5, 9], {"1": [stroke("old")]}, slice_key="1" * 64)
        self._layer("al", [5, 9], {"1": [stroke("new")]}, slice_key="2" * 64)
        InkLayer.objects.filter(pk=old.pk).update(
            updated_at=old.updated_at.replace(year=2020))
        pages, _pads, _ = bookink.plan_book_overlay(self._request(), self.book)
        self.assertEqual(pages[5][0]["d"], "new")

    def test_a_relaid_section_is_refused_rather_than_misplaced(self):
        """The section is 5 pages now and the notes were made on 3. Page 2 of
        those notes is no longer page 2 of this section."""
        self._layer("al", [5, 7], {"1": [stroke()], "2": [stroke()]})
        pages, pads, skipped = bookink.plan_book_overlay(self._request(), self.book)
        self.assertEqual(pages, {})
        self.assertEqual([s.reason for s in skipped], ["relaid"])
        self.assertEqual(skipped[0].title, "Alpha")

    def test_notes_survive_a_rebuild_that_did_not_change_the_section(self):
        """The whole point: the book moved on, the section did not, the notes
        still land."""
        self._layer("al", [5, 9], {"1": [stroke()]}, book_sha256="deadbeef")
        pages, pads, skipped = bookink.plan_book_overlay(self._request(), self.book)
        self.assertEqual(list(pages), [5])
        self.assertEqual(skipped, [])

    def test_notes_on_a_section_that_no_longer_exists_are_reported(self):
        self._layer("ghost", [5, 9], {"1": [stroke()]})
        pages, pads, skipped = bookink.plan_book_overlay(self._request(), self.book)
        self.assertEqual(pages, {})
        self.assertEqual([s.reason for s in skipped], ["gone"])

    def test_an_empty_layer_contributes_nothing(self):
        self._layer("al", [5, 9], {})
        pages, pads, skipped = bookink.plan_book_overlay(self._request(), self.book)
        self.assertEqual((pages, pads, skipped), ({}, {}, []))

    def test_a_page_beyond_the_section_is_dropped(self):
        """Defensive: stored data claiming page 9 of a 5-page section must not
        spill into whatever follows in the book."""
        self._layer("al", [5, 9], {"9": [stroke()]})
        pages, _pads, _ = bookink.plan_book_overlay(self._request(), self.book)
        self.assertEqual(pages, {})

    def test_a_gated_section_is_left_out_silently(self):
        """Not reported: 'skipped 1 section' would confirm it exists."""
        self._layer("al", [5, 9], {"1": [stroke()]})
        with override_settings(
                PARODY_WEB_ACCESS_POLICY="parody_web_annotate.tests.DenyAll"):
            pages, pads, skipped = bookink.plan_book_overlay(self._request(), self.book)
        self.assertEqual((pages, pads, skipped), ({}, {}, []))

    def test_anonymous_readers_have_no_notes(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        self.assertEqual(bookink.plan_book_overlay(request, self.book), ({}, {}, []))

    def test_the_summary_points_at_the_sections_to_fix(self):
        self._layer("al", [5, 7], {"1": [stroke()]})     # relaid
        self._layer("li", [3, 5], {"1": [stroke()]})     # fine
        summary = bookink.summary(self._request(), self.book)
        self.assertTrue(summary["any"])
        self.assertEqual([s["title"] for s in summary["stale"]], ["Alpha"])
        self.assertIn("/one/alpha/pdf/view/", summary["stale"][0]["url"])


class AnnotatedBookEndpointTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.cache = base / "live", base / "cache"
        self.root.mkdir()
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.reader = get_user_model().objects.create_user("reader", password="x")
        self.client = Client()
        self.client.force_login(self.reader)

    def _settings(self):
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                                 PARODY_WEB_PRINT_CACHE=str(self.cache))

    def _ink(self):
        InkLayer.objects.create(
            user=self.reader, book_slug=self.book.slug, edition_id="",
            section_key="al", slice_key="a" * 64, book_sha256="c" * 64,
            pages=[5, 9], strokes={"1": [stroke(color="#ff0000")]})

    def test_it_returns_the_whole_book_with_the_notes_on_it(self):
        import io
        from pypdf import PdfReader
        self._ink()
        with self._settings():
            resp = self.client.get("/pdf/annotated/")
        self.assertEqual(resp.status_code, 200)
        pdf = PdfReader(io.BytesIO(b"".join(resp.streaming_content)
                                   if resp.streaming else resp.content))
        self.assertEqual(len(pdf.pages), 20, "the whole book, not an extract")
        self.assertIn(b"1 0 0 rg", pdf.pages[4].get_contents().get_data())

    def test_pages_without_notes_are_untouched(self):
        import io
        from pypdf import PdfReader
        self._ink()
        with self._settings():
            resp = self.client.get("/pdf/annotated/")
        pdf = PdfReader(io.BytesIO(b"".join(resp.streaming_content)
                                   if resp.streaming else resp.content))
        self.assertNotIn(b"1 0 0 rg", pdf.pages[0].get_contents().get_data())

    def test_a_book_with_no_notes_has_nothing_to_download(self):
        with self._settings():
            self.assertEqual(self.client.get("/pdf/annotated/").status_code, 404)

    def test_anonymous_readers_get_nothing(self):
        self._ink()
        self.client.logout()
        with self._settings():
            self.assertEqual(self.client.get("/pdf/annotated/").status_code, 403)

    def test_it_is_named_so_it_is_not_confused_with_the_clean_book(self):
        self._ink()
        with self._settings():
            resp = self.client.get("/pdf/annotated/")
        self.assertIn("-annotated.pdf", resp["Content-Disposition"])


class BookNotesLinkTests(TestCase):
    """Where a reader finds the annotated book."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.reader = get_user_model().objects.create_user("reader", password="x")
        self.client = Client()

    def _settings(self):
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root))

    def _ink(self, pages=(5, 9)):
        InkLayer.objects.create(
            user=self.reader, book_slug=self.book.slug, edition_id="",
            section_key="al", slice_key="a" * 64, book_sha256="c" * 64,
            pages=list(pages), strokes={"1": [stroke()]})

    def test_the_home_page_offers_it_once_there_are_notes(self):
        self.client.force_login(self.reader)
        self._ink()
        with self._settings():
            html = self.client.get("/").content.decode()
        self.assertIn("/pdf/annotated/", html)
        self.assertIn("Download the book with your notes", html)

    def test_the_home_page_says_nothing_when_there_are_none(self):
        self.client.force_login(self.reader)
        with self._settings():
            html = self.client.get("/").content.decode()
        self.assertNotIn("with your notes", html)

    def test_the_section_rail_offers_it_too(self):
        self.client.force_login(self.reader)
        self._ink()
        with self._settings():
            html = self.client.get("/one/alpha/").content.decode()
        self.assertIn("/pdf/annotated/", html)

    def test_a_stale_section_is_named_with_a_way_to_fix_it(self):
        """Telling a student their notes were left out is the whole point of
        refusing to place them."""
        self.client.force_login(self.reader)
        self._ink(pages=(5, 7))          # section is 5 pages now, notes on 3
        with self._settings():
            html = self.client.get("/").content.decode()
        self.assertIn("earlier layout", html)
        self.assertIn("Alpha", html)
        self.assertIn("/one/alpha/pdf/view/", html)
        self.assertNotIn("Download the book with your notes", html)

    def test_anonymous_readers_are_offered_nothing(self):
        self._ink()
        with self._settings():
            html = self.client.get("/").content.decode()
        self.assertNotIn("with your notes", html)


class PadsThroughTheStackTests(TestCase):
    """A margin note is stored, planned and exported like any other, except
    that it widens the page it belongs to."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.cache = base / "live", base / "cache"
        self.root.mkdir()
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.reader = get_user_model().objects.create_user("reader", password="x")
        self.client = Client()
        self.client.force_login(self.reader)

    def _settings(self):
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                                 PARODY_WEB_PRINT_CACHE=str(self.cache))

    def _put(self, body):
        return self.client.put("/one/alpha/ink/", body,
                               content_type="application/json")

    def test_a_pad_note_round_trips(self):
        with self._settings():
            self._put({"strokes": {}, "pads": {"1": [stroke("PAD")]}})
            got = self.client.get("/one/alpha/ink/").json()
        self.assertEqual(got["pads"]["1"][0]["d"], "PAD")
        self.assertEqual(got["strokes"], {})

    def test_a_pad_note_alone_counts_as_having_annotated(self):
        """Otherwise a reader who only used the margin would be told they had
        no notes and offered no download."""
        with self._settings():
            self._put({"strokes": {}, "pads": {"1": [stroke()]}})
        layer = InkLayer.objects.get(user=self.reader)
        self.assertEqual(layer.stroke_count, 1)

    def test_pads_reach_the_book_plan_on_the_right_page(self):
        from django.test import RequestFactory
        request = RequestFactory().get("/")
        request.user = self.reader
        with self._settings():
            self._put({"strokes": {}, "pads": {"1": [stroke("PAD")]}})
            pages, pads, skipped = bookink.plan_book_overlay(request, self.book)
        self.assertEqual(pages, {})
        self.assertEqual(list(pads), [5])    # alpha starts at book page 5
        self.assertEqual(skipped, [])

    def test_the_annotated_section_pdf_widens_the_padded_page(self):
        import io
        from pypdf import PdfReader
        with self._settings():
            self._put({"strokes": {}, "pads": {"1": [stroke()]}})
            resp = self.client.get("/one/alpha/pdf/annotated/")
        pdf = PdfReader(io.BytesIO(b"".join(resp.streaming_content)
                                   if resp.streaming else resp.content))
        self.assertEqual(float(pdf.pages[0].mediabox.width), 300.0)
        self.assertEqual(float(pdf.pages[1].mediabox.width), 200.0)

    def test_carry_forward_brings_the_margin_along(self):
        with self._settings():
            self._put({"strokes": {}, "pads": {"1": [stroke("PAD")]}})
            layer = InkLayer.objects.get(user=self.reader)
            resp = self.client.post(
                "/one/alpha/ink/carry-forward/",
                {"from": layer.slice_key, "to": "f" * 64},
                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        copy = InkLayer.objects.get(user=self.reader, slice_key="f" * 64)
        self.assertEqual(copy.pads["1"][0]["d"], "PAD")

    def test_pads_must_be_an_object(self):
        with self._settings():
            resp = self._put({"strokes": {}, "pads": "nope"})
        self.assertEqual(resp.status_code, 400)

    def test_a_client_that_sends_no_pads_still_works(self):
        """Older bundles cached in a reader's browser."""
        with self._settings():
            resp = self._put({"strokes": {"1": [stroke()]}})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(InkLayer.objects.get(user=self.reader).pads, {})
