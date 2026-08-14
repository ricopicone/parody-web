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
