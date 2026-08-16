"""The ink layer: identity, isolation, and surviving a re-import."""
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from parody_web_annotate.models import InkLayer


class InkLayerModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.reader = User.objects.create_user("reader", password="x")
        self.other = User.objects.create_user("other", password="x")
        self.kw = dict(book_slug="print-book", edition_id="", section_key="al",
                       slice_key="a" * 64, book_sha256="b" * 64, pages=[5, 9],
                       strokes={})

    def test_one_layer_per_reader_section_and_version(self):
        InkLayer.objects.create(user=self.reader, **self.kw)
        with self.assertRaises(IntegrityError):
            InkLayer.objects.create(user=self.reader, **self.kw)

    def test_two_versions_of_one_section_coexist(self):
        InkLayer.objects.create(user=self.reader, **self.kw)
        InkLayer.objects.create(user=self.reader, **{**self.kw, "slice_key": "c" * 64})
        self.assertEqual(InkLayer.objects.filter(user=self.reader).count(), 2)

    def test_two_readers_annotate_the_same_version_independently(self):
        InkLayer.objects.create(user=self.reader, **self.kw)
        InkLayer.objects.create(user=self.other, **self.kw)
        self.assertEqual(InkLayer.objects.count(), 2)

    def test_it_carries_everything_needed_to_cut_its_own_pdf(self):
        """Section.print_pages is overwritten every import; this row must not
        depend on it."""
        layer = InkLayer.objects.create(user=self.reader, **self.kw)
        self.assertEqual(layer.book_sha256, "b" * 64)
        self.assertEqual(layer.pages, [5, 9])

    def test_stroke_count_sums_the_pages(self):
        layer = InkLayer.objects.create(
            user=self.reader, **{**self.kw,
                                 "strokes": {"1": [{}, {}], "2": [{}]}})
        self.assertEqual(layer.stroke_count, 3)


class DenyAll:
    """An access policy that refuses every PDF."""

    def __getattr__(self, name):
        def hook(*args, **kwargs):
            return False
        return hook


class InkEndpointTests(TestCase):
    """Reading and writing ink, gated exactly as the PDF is."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.test import Client
        from parody_web.tests_printing import import_artifact, make_pdf_with_content

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()

        User = get_user_model()
        self.reader = User.objects.create_user("reader", password="x")
        self.other = User.objects.create_user("other", password="x")
        self.client = Client()
        self.url = "/one/alpha/ink/"
        self.body = {"strokes": {"1": [{"tool": "pen", "color": "#000",
                                        "size": 2, "opacity": 1,
                                        "points": [[1, 2, 0.5]], "d": "M1 2"}]}}

    def _settings(self, **extra):
        from django.test import override_settings
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root), **extra)

    def _put(self, body=None):
        return self.client.put(self.url, body or self.body,
                               content_type="application/json")

    def test_put_then_get_round_trips(self):
        self.client.force_login(self.reader)
        with self._settings():
            self.assertEqual(self._put().status_code, 200)
            got = self.client.get(self.url).json()
        self.assertEqual(got["strokes"]["1"][0]["tool"], "pen")

    def test_a_write_records_the_version_it_belongs_to(self):
        """Recorded on write, while Section.print_pages is still true."""
        self.client.force_login(self.reader)
        with self._settings():
            self._put()
        layer = InkLayer.objects.get(user=self.reader)
        self.assertEqual(layer.pages, [5, 9])
        self.assertEqual(layer.book_sha256, "c" * 64)
        self.assertEqual(len(layer.slice_key), 64)

    def test_a_reader_never_sees_another_readers_ink(self):
        with self._settings():
            self.client.force_login(self.other)
            self._put()
            self.client.force_login(self.reader)
            got = self.client.get(self.url).json()
        self.assertEqual(got["strokes"], {})

    def test_a_reader_cannot_overwrite_another_readers_ink(self):
        with self._settings():
            self.client.force_login(self.other)
            self._put()
            self.client.force_login(self.reader)
            self._put({"strokes": {}})
        theirs = InkLayer.objects.get(user=self.other)
        self.assertEqual(len(theirs.strokes["1"]), 1)
        self.assertEqual(InkLayer.objects.count(), 2)

    def test_anonymous_cannot_write(self):
        with self._settings():
            self.assertEqual(self._put().status_code, 403)
        self.assertEqual(InkLayer.objects.count(), 0)

    def test_a_refused_section_yields_no_ink(self):
        self.client.force_login(self.reader)
        with self._settings(
                PARODY_WEB_ACCESS_POLICY="parody_web_annotate.tests.DenyAll"):
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertEqual(self._put().status_code, 404)

    def test_the_response_lists_the_versions_worth_showing(self):
        self.client.force_login(self.reader)
        with self._settings():
            self._put()
            versions = self.client.get(self.url).json()["versions"]
        self.assertEqual(len(versions), 1)
        self.assertTrue(versions[0]["current"])


class VersionedPdfAndCarryForwardTests(TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.test import Client
        from parody_web import printing
        from parody_web.tests_printing import import_artifact, make_pdf_with_content

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.archive, self.cache = base / "live", base / "arc", base / "c"
        self.root.mkdir()
        make_pdf_with_content(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.printing = printing

        User = get_user_model()
        self.reader = User.objects.create_user("reader", password="x")
        self.client = Client()
        self.client.force_login(self.reader)

    def _settings(self):
        from django.test import override_settings
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                                 PARODY_WEB_PRINT_ARCHIVE=str(self.archive),
                                 PARODY_WEB_PRINT_CACHE=str(self.cache))

    def _annotate_then_release_a_new_book(self):
        """Annotate the current version, then push a new book PDF over it."""
        from parody_web.tests_printing import make_pdf_with_content
        self.printing.archive_book_pdf(self.book)
        old_key = self.printing.slice_key_for(self.book, self.book.sections.get(slug="alpha"))
        self.client.put("/one/alpha/ink/",
                        {"strokes": {"1": [{"tool": "pen", "d": "M1 2"}]}},
                        content_type="application/json")
        # seed=1 so alpha's own pages really changed — without it the key is
        # (correctly) unchanged and there is nothing to carry forward.
        make_pdf_with_content(self.root / "print-book.pdf", 24, seed=1)
        self.printing._reader.cache_clear()
        self.book.print_sha256 = "e" * 64
        self.book.save()
        self.printing.archive_book_pdf(self.book)
        return old_key

    def test_the_current_version_needs_no_v(self):
        with self._settings():
            self.assertEqual(self.client.get("/one/alpha/pdf/at/").status_code, 200)

    def test_an_old_version_still_resolves_after_a_new_release(self):
        with self._settings():
            old_key = self._annotate_then_release_a_new_book()
            resp = self.client.get("/one/alpha/pdf/at/", {"v": old_key})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_a_version_the_reader_has_no_ink_for_is_absent(self):
        with self._settings():
            self.assertEqual(
                self.client.get("/one/alpha/pdf/at/", {"v": "f" * 64}).status_code, 404)

    def test_carry_forward_copies_and_keeps_the_old_layer(self):
        with self._settings():
            old_key = self._annotate_then_release_a_new_book()
            new_key = self.printing.slice_key_for(
                self.book, self.book.sections.get(slug="alpha"))
            resp = self.client.post("/one/alpha/ink/carry-forward/",
                                    {"from": old_key, "to": new_key},
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(InkLayer.objects.count(), 2)
        self.assertEqual(InkLayer.objects.get(slice_key=old_key).strokes,
                         InkLayer.objects.get(slice_key=new_key).strokes)

    def test_carry_forward_refuses_rather_than_clobbering(self):
        with self._settings():
            old_key = self._annotate_then_release_a_new_book()
            new_key = self.printing.slice_key_for(
                self.book, self.book.sections.get(slug="alpha"))
            InkLayer.objects.create(
                user=self.reader, book_slug=self.book.slug, edition_id="",
                section_key="al", slice_key=new_key, book_sha256="e" * 64,
                pages=[5, 9], strokes={"1": [{"tool": "pen", "d": "M9 9"}]})
            resp = self.client.post("/one/alpha/ink/carry-forward/",
                                    {"from": old_key, "to": new_key},
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(
            InkLayer.objects.get(slice_key=new_key).strokes["1"][0]["d"], "M9 9")

    def test_a_rebuild_that_misses_this_section_keeps_the_notes_attached(self):
        """The promise of the whole feature.

        Found by accident: an early fixture rebuilt the book with identical
        page content and carry-forward refused, because there was nothing to
        carry — the notes were already on the current version.
        """
        from parody_web.tests_printing import make_pdf_with_content
        with self._settings():
            self.printing.archive_book_pdf(self.book)
            self.client.put("/one/alpha/ink/",
                            {"strokes": {"1": [{"tool": "pen", "d": "M1 2"}]}},
                            content_type="application/json")
            before = self.client.get("/one/alpha/ink/").json()

            # a new release: more pages, but alpha's own pages are untouched
            make_pdf_with_content(self.root / "print-book.pdf", 24)
            self.printing._reader.cache_clear()
            after = self.client.get("/one/alpha/ink/").json()

        self.assertEqual(after["slice_key"], before["slice_key"])
        self.assertEqual(after["strokes"], before["strokes"])
        self.assertEqual(len(after["versions"]), 1,
                         "an untouched section must not sprout a second version")


class AnnotatedDownloadTests(TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from django.test import Client
        from parody_web.tests_printing import import_artifact, make_pdf_with_content

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
        from django.test import override_settings
        return override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                                 PARODY_WEB_PRINT_CACHE=str(self.cache))

    def _ink(self):
        self.client.put("/one/alpha/ink/",
                        {"strokes": {"1": [{"tool": "pen", "color": "#ff0000",
                                            "opacity": 1, "d": "M10 10 L50 50 Z"}]}},
                        content_type="application/json")

    def test_it_returns_a_pdf_with_the_ink_in_it(self):
        from pypdf import PdfReader
        import io
        with self._settings():
            self._ink()
            resp = self.client.get("/one/alpha/pdf/annotated/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        pdf = PdfReader(io.BytesIO(b"".join(resp.streaming_content)
                                   if resp.streaming else resp.content))
        self.assertEqual(len(pdf.pages), 5)          # alpha is pages 5..9
        self.assertIn(b"1 0 0 rg", pdf.pages[0].get_contents().get_data())

    def test_it_is_named_so_the_reader_can_tell_it_apart(self):
        with self._settings():
            self._ink()
            resp = self.client.get("/one/alpha/pdf/annotated/")
        self.assertIn("-annotated.pdf", resp["Content-Disposition"])

    def test_a_section_with_no_ink_has_nothing_to_download(self):
        with self._settings():
            self.assertEqual(
                self.client.get("/one/alpha/pdf/annotated/").status_code, 404)

    def test_editing_the_ink_produces_a_fresh_file(self):
        with self._settings():
            self._ink()
            self.client.get("/one/alpha/pdf/annotated/")
            self.client.put("/one/alpha/ink/",
                            {"strokes": {"1": [{"tool": "pen", "color": "#00ff00",
                                                "opacity": 1, "d": "M1 1 L9 9 Z"}]}},
                            content_type="application/json")
            resp = self.client.get("/one/alpha/pdf/annotated/")
        from pypdf import PdfReader
        import io
        pdf = PdfReader(io.BytesIO(b"".join(resp.streaming_content)
                                   if resp.streaming else resp.content))
        self.assertIn(b"0 1 0 rg", pdf.pages[0].get_contents().get_data())

    def test_anonymous_gets_nothing(self):
        with self._settings():
            self._ink()
            self.client.logout()
            self.assertEqual(
                self.client.get("/one/alpha/pdf/annotated/").status_code, 403)
