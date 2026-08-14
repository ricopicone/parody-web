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
