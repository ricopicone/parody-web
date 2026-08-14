"""Per-section print PDFs: import, slicing, gating, and chrome."""
import json
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from parody_web import printing
from parody_web.models import Book, Section

ARTIFACT = {
    "schema_version": 2,
    "slug": "print-book",
    "title": "Print Book",
    "author": ["A. Author"],
    "print": {"pdf": "print-book.pdf", "pages": 20, "sha256": "c" * 64},
    "chapters": [{
        "title": "One", "slug": "one", "hash": "c1",
        "sections": [
            {"title": "One", "slug": "lead-in", "hash": "li",
             "html": "<p>Intro.</p>", "print": {"pages": [3, 5]}},
            {"title": "Alpha", "slug": "alpha", "hash": "al",
             "html": "<p>Alpha.</p>", "print": {"pages": [5, 9]}},
            {"title": "Beta", "slug": "beta", "hash": "be",
             "html": "<p>Beta.</p>"},
        ],
    }],
}


def import_artifact(data=None, **opts):
    payload = json.loads(json.dumps(data or ARTIFACT))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        path = f.name
    call_command("import_artifact", path, **opts)
    Path(path).unlink()
    return Book.objects.get(slug=payload["slug"])


class ImportPrintFieldsTests(TestCase):
    def test_book_carries_the_print_metadata(self):
        book = import_artifact()
        self.assertEqual(book.print_pdf, "print-book.pdf")
        self.assertEqual(book.print_pages, 20)
        self.assertEqual(book.print_sha256, "c" * 64)

    def test_sections_carry_their_page_range(self):
        book = import_artifact()
        alpha = book.sections.get(slug="alpha")
        self.assertEqual(alpha.print_pages, [5, 9])

    def test_a_section_without_a_range_is_null(self):
        book = import_artifact()
        self.assertIsNone(book.sections.get(slug="beta").print_pages)

    def test_page_count_is_inclusive_of_both_ends(self):
        book = import_artifact()
        # [5, 9] shares page 5 with the lead-in and page 9 with what follows
        self.assertEqual(book.sections.get(slug="alpha").print_page_count, 5)
        self.assertIsNone(book.sections.get(slug="beta").print_page_count)

    def test_an_artifact_with_no_print_block_imports_cleanly(self):
        data = json.loads(json.dumps(ARTIFACT))
        del data["print"]
        for sec in data["chapters"][0]["sections"]:
            sec.pop("print", None)
        book = import_artifact(data)
        self.assertEqual(book.print_pdf, "")
        self.assertIsNone(book.print_pages)
        self.assertTrue(all(s.print_pages is None for s in book.sections.all()))


class PrintSettingsTests(SimpleTestCase):
    def test_no_root_configured_means_the_feature_is_off(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=""):
            self.assertIsNone(printing.print_root())

    def test_cache_defaults_inside_the_print_root(self):
        with tempfile.TemporaryDirectory() as td:
            with override_settings(PARODY_WEB_PRINT_ROOT=td,
                                   PARODY_WEB_PRINT_CACHE=""):
                self.assertEqual(printing.print_cache_root(),
                                 Path(td) / ".cache")

    def test_cache_can_be_pointed_elsewhere(self):
        with tempfile.TemporaryDirectory() as td, \
                tempfile.TemporaryDirectory() as cache:
            with override_settings(PARODY_WEB_PRINT_ROOT=td,
                                   PARODY_WEB_PRINT_CACHE=cache):
                self.assertEqual(printing.print_cache_root(), Path(cache))

    def test_a_non_directory_root_is_rejected_at_startup(self):
        with self.assertRaises(ImproperlyConfigured):
            printing.validate_print_settings("/definitely/not/here", "", "")

    def test_xaccel_requires_the_cache_to_live_under_the_root(self):
        # nginx maps ONE internal location at the print root, so a cache
        # outside it could never be streamed.
        with tempfile.TemporaryDirectory() as td, \
                tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(ImproperlyConfigured):
                printing.validate_print_settings(td, outside, "/print-internal/")
            printing.validate_print_settings(td, "", "/print-internal/")

    def test_valid_settings_pass(self):
        with tempfile.TemporaryDirectory() as td:
            printing.validate_print_settings(td, "", "")


def make_pdf(path, pages):
    """A real multi-page PDF."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)
    return path


class SlicingTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf(self.root / "print-book.pdf", 20)

    def _book(self):
        return import_artifact()

    def test_book_pdf_path_finds_the_file(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertEqual(printing.book_pdf_path(self._book()),
                             self.root / "print-book.pdf")

    def test_book_pdf_path_is_none_when_the_file_is_absent(self):
        (self.root / "print-book.pdf").unlink()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertIsNone(printing.book_pdf_path(self._book()))

    def test_slice_has_exactly_the_inclusive_page_count(self):
        from pypdf import PdfReader
        book = self._book()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            out = printing.section_pdf_path(book, book.sections.get(slug="alpha"))
        # [5, 9] inclusive = 5 pages
        self.assertEqual(len(PdfReader(str(out)).pages), 5)

    def test_the_cache_path_carries_the_source_hash(self):
        book = self._book()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            out = printing.section_pdf_path(book, book.sections.get(slug="alpha"))
        self.assertIn(book.print_sha256[:12], str(out))

    def test_a_repaginated_book_gets_a_fresh_cache_path(self):
        book = self._book()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            first = printing.section_pdf_path(
                book, book.sections.get(slug="alpha"))
            Book.objects.filter(pk=book.pk).update(print_sha256="d" * 64)
            book.refresh_from_db()
            second = printing.section_pdf_path(
                book, book.sections.get(slug="alpha"))
        self.assertNotEqual(first, second)

    def test_a_second_request_reuses_the_cached_slice(self):
        book = self._book()
        section = book.sections.get(slug="alpha")
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            first = printing.section_pdf_path(book, section)
            stamp = first.stat().st_mtime_ns
            second = printing.section_pdf_path(book, section)
        self.assertEqual(first, second)
        self.assertEqual(stamp, second.stat().st_mtime_ns)

    def test_a_section_with_no_range_has_no_slice(self):
        book = self._book()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertIsNone(printing.section_pdf_path(
                book, book.sections.get(slug="beta")))

    def test_a_range_past_the_end_of_the_pdf_is_clamped(self):
        from pypdf import PdfReader
        book = self._book()
        section = book.sections.get(slug="alpha")
        Section.objects.filter(pk=section.pk).update(print_pages=[19, 40])
        section.refresh_from_db()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            out = printing.section_pdf_path(book, section)
        self.assertEqual(len(PdfReader(str(out)).pages), 2)  # pages 19-20

    def test_no_print_root_means_no_slice(self):
        book = self._book()
        with override_settings(PARODY_WEB_PRINT_ROOT=""):
            self.assertIsNone(printing.section_pdf_path(
                book, book.sections.get(slug="alpha")))


class PdfPolicyTests(TestCase):
    def setUp(self):
        from django.test import RequestFactory
        self.rf = RequestFactory()
        self.book = import_artifact()

    def _policy(self):
        from parody_web.access import DefaultPolicy
        return DefaultPolicy()

    def _anon(self):
        from django.contrib.auth.models import AnonymousUser
        req = self.rf.get("/")
        req.user = AnonymousUser()
        return req

    def _owner(self):
        from django.contrib.auth import get_user_model
        req = self.rf.get("/")
        req.user = get_user_model()(username="owner")
        return req

    def test_a_full_sections_pdf_is_public(self):
        section = self.book.sections.get(slug="alpha")
        self.assertTrue(
            self._policy().can_download_section_pdf(self._anon(), section))

    def test_a_preview_sections_pdf_is_owner_only(self):
        section = self.book.sections.get(slug="alpha")
        Section.objects.filter(pk=section.pk).update(preview=True)
        section.refresh_from_db()
        self.assertFalse(
            self._policy().can_download_section_pdf(self._anon(), section))
        self.assertTrue(
            self._policy().can_download_section_pdf(self._owner(), section))

    def test_the_full_book_pdf_is_public_by_default(self):
        self.assertTrue(
            self._policy().can_download_book_pdf(self._anon(), self.book))

    def test_the_full_book_pdf_can_be_turned_off_for_a_site(self):
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=False):
            self.assertFalse(
                self._policy().can_download_book_pdf(self._anon(), self.book))
            # the owner always keeps it
            self.assertTrue(
                self._policy().can_download_book_pdf(self._owner(), self.book))


class PdfViewTests(TestCase):
    def setUp(self):
        from django.test import Client
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.client = Client()

    def _login(self):
        from django.contrib.auth import get_user_model
        get_user_model().objects.create_user("owner", password="pw")
        self.client.login(username="owner", password="pw")

    def _body(self, resp):
        return b"".join(resp.streaming_content) if resp.streaming else resp.content

    def test_section_pdf_downloads_with_the_right_page_count(self):
        import io

        from pypdf import PdfReader
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertEqual(len(PdfReader(io.BytesIO(self._body(resp))).pages), 5)

    def test_the_filename_names_the_section(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertIn("alpha", resp["Content-Disposition"].lower())
        self.assertIn(".pdf", resp["Content-Disposition"])

    def test_a_preview_sections_pdf_is_refused_to_the_public(self):
        # THE leak this whole design exists to prevent: the print PDF holds the
        # full text of a section the online artifact deliberately withholds.
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertEqual(resp.status_code, 404)

    def test_the_owner_still_gets_a_preview_sections_pdf(self):
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        self._login()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertEqual(resp.status_code, 200)

    def test_a_section_with_no_range_has_no_pdf(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertEqual(self.client.get("/one/beta/pdf/").status_code, 404)

    def test_full_book_pdf_is_served_by_default(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_full_book_pdf_can_be_withheld_from_the_public(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PUBLIC_BOOK_PDF=False):
            self.assertEqual(self.client.get("/pdf/").status_code, 404)
            self._login()
            self.assertEqual(self.client.get("/pdf/").status_code, 200)

    def test_a_missing_file_on_disk_is_a_404_not_a_500(self):
        (self.root / "print-book.pdf").unlink()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertEqual(self.client.get("/one/alpha/pdf/").status_code, 404)
            self.assertEqual(self.client.get("/pdf/").status_code, 404)

    def test_no_print_root_is_a_404_not_a_500(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=""):
            self.assertEqual(self.client.get("/one/alpha/pdf/").status_code, 404)

    def test_xaccel_delegates_streaming_to_nginx(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PRINT_XACCEL="/print-internal/"):
            resp = self.client.get("/one/alpha/pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["X-Accel-Redirect"].startswith("/print-internal/"))
        self.assertEqual(resp.content, b"")


class PdfViewerTests(TestCase):
    def setUp(self):
        from django.test import Client
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.client = Client()

    def test_the_viewer_renders_and_points_at_the_section_pdf(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/view/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("/one/alpha/pdf/", html)
        self.assertIn("Alpha", html)

    def test_the_viewer_exposes_the_annotation_seam(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        # the empty overlay a future annotation layer adopts, keyed the way
        # hosts already key their per-section records
        self.assertIn('class="pdf-annotation-layer"', html)
        self.assertIn('data-section-key="al"', html)

    def test_the_viewer_offers_a_way_back_to_the_section(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/pdf/view/").content.decode()
        self.assertIn('href="/one/alpha/"', html)

    def test_a_refused_section_has_no_viewer(self):
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            resp = self.client.get("/one/alpha/pdf/view/")
        self.assertEqual(resp.status_code, 404)

    def test_a_section_with_no_pdf_has_no_viewer(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            self.assertEqual(
                self.client.get("/one/beta/pdf/view/").status_code, 404)


class SectionRailTests(TestCase):
    def setUp(self):
        from django.test import Client
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        make_pdf(self.root / "print-book.pdf", 20)
        self.book = import_artifact()
        self.client = Client()

    def test_the_rail_offers_the_section_pdf(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/").content.decode()
        self.assertIn('class="util-rail"', html)
        self.assertIn('data-util="pdf"', html)
        self.assertIn("/one/alpha/pdf/", html)
        self.assertIn("/one/alpha/pdf/view/", html)

    def test_the_rail_states_the_page_count(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/").content.decode()
        self.assertIn("5 pages", html)

    def test_the_rail_is_absent_when_the_section_has_no_pdf(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/beta/").content.decode()
        self.assertNotIn('class="util-rail"', html)

    def test_the_rail_is_absent_without_a_print_root(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=""):
            html = self.client.get("/one/alpha/").content.decode()
        self.assertNotIn('class="util-rail"', html)

    def test_a_preview_section_offers_the_public_no_pdf(self):
        Section.objects.filter(book=self.book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/").content.decode()
        self.assertNotIn("/one/alpha/pdf/", html)

    def test_the_rail_works_without_javascript(self):
        # the trigger is a real link to the viewer, progressively enhanced
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/alpha/").content.decode()
        self.assertIn('<a class="util-rail-trigger"', html)

    def test_the_chapter_page_offers_the_lead_in_pdf(self):
        # The lead-in is the chapter title + intro prose unit. It is rendered
        # on the chapter landing page, not at /one/lead-in/, so this is the
        # only place its PDF can be offered.
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/").content.decode()
        self.assertIn('class="util-rail"', html)
        self.assertIn("/one/lead-in/pdf/", html)
        self.assertIn("3 pages", html)  # [3, 5] inclusive

    def test_a_chapter_with_no_lead_in_has_no_rail(self):
        Section.objects.filter(book=self.book, slug="lead-in").delete()
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/one/").content.decode()
        self.assertNotIn('class="util-rail"', html)

    def test_the_home_page_offers_the_full_book(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root)):
            html = self.client.get("/").content.decode()
        self.assertIn('href="/pdf/"', html)

    def test_the_home_page_hides_a_withheld_full_book(self):
        with override_settings(PARODY_WEB_PRINT_ROOT=str(self.root),
                               PARODY_WEB_PUBLIC_BOOK_PDF=False):
            html = self.client.get("/").content.decode()
        self.assertNotIn('href="/pdf/"', html)


class PublicBookPdfWarningTests(TestCase):
    def test_a_gated_book_with_a_public_full_pdf_warns(self):
        book = import_artifact()
        Section.objects.filter(book=book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=True):
            warnings = printing.public_book_pdf_warnings()
        self.assertEqual(len(warnings), 1)
        self.assertIn("print-book", warnings[0])
        self.assertIn("PARODY_WEB_PUBLIC_BOOK_PDF", warnings[0])

    def test_a_fully_public_book_does_not_warn(self):
        import_artifact()
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=True):
            self.assertEqual(printing.public_book_pdf_warnings(), [])

    def test_no_warning_once_the_setting_is_off(self):
        book = import_artifact()
        Section.objects.filter(book=book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=False):
            self.assertEqual(printing.public_book_pdf_warnings(), [])

    def test_a_book_with_no_print_pdf_never_warns(self):
        data = json.loads(json.dumps(ARTIFACT))
        del data["print"]
        book = import_artifact(data)
        Section.objects.filter(book=book, slug="alpha").update(preview=True)
        with override_settings(PARODY_WEB_PUBLIC_BOOK_PDF=True):
            self.assertEqual(printing.public_book_pdf_warnings(), [])
