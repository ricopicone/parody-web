"""Per-section print PDFs: import, slicing, gating, and chrome."""
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

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
