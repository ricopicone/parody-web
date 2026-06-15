"""Book-host: artifact import + Django-native rendering of the flavored html."""
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from book.models import Book, Section
from book.templatetags.book_tags import render_book

ARTIFACT = {
    "schema_version": 2,
    "slug": "demo-book",
    "title": "Demo Book",
    "author": ["A. Author"],
    "book": {"name": "Demo", "editions": [{"id": "0", "isbn": "978-test"}]},
    "chapters": [{
        "title": "Hardware", "slug": "hardware", "hash": "h1",
        "sections": [
            {"title": "Specific T1", "slug": "specific-t1", "hash": "ef",
             "online_only": True,
             "html": '<p>The myRIO via {% media \'notebooks/x.jpg\' %}.</p>'
                     '<details><summary>Specs</summary>'
                     '<div class="version-list-item">SoC: Xilinx</div></details>',
             "anchors": []},
            {"title": "Licensed Section", "slug": "licensed", "hash": "lz",
             "online_resources": '<p>Extra: {% cite \'knuth1997\' %}.</p>'},
        ],
    }],
}


def _import(slug="demo-book"):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, "a.json")
        p.write_text(json.dumps(ARTIFACT))
        call_command("import_artifact", str(p), "--slug", slug)


class RenderBookFilterTests(TestCase):
    def test_resolves_media_and_strips_unknown(self):
        out = render_book("<img src=\"{% media 'a/b.png' %}\"> {% csrf_token %}")
        self.assertIn("/media/a/b.png", out)
        self.assertNotIn("{%", out)

    def test_cite_and_details_pass_through(self):
        out = render_book("{% cite 'k' %} <details><summary>s</summary>x</details>")
        self.assertIn('class="citation"', out)
        self.assertIn("<details>", out)


@override_settings(BOOK_SLUG="demo-book")
class BookHostViewTests(TestCase):
    def setUp(self):
        _import()
        self.c = Client()

    def test_import_stored_fields(self):
        book = Book.objects.get(slug="demo-book")
        self.assertEqual(book.book_metadata["editions"][0]["isbn"], "978-test")
        self.assertTrue(Section.objects.get(slug="specific-t1").online_only)
        self.assertTrue(Section.objects.get(slug="licensed").online_resources)

    def test_index_lists_book(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Demo Book")
        self.assertContains(r, "978-test")

    def test_online_only_section_renders_with_tags_resolved(self):
        r = self.c.get("/hardware/specific-t1/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("/media/notebooks/x.jpg", html)
        self.assertNotIn("{%", html)
        self.assertIn("<details>", html)
        self.assertIn("Xilinx", html)

    def test_online_resources_render(self):
        r = self.c.get("/hardware/licensed/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Online resources")
        self.assertContains(r, "citation")  # {% cite %} resolved

    def test_reimport_is_idempotent(self):
        before = Section.objects.count()
        _import()
        self.assertEqual(Section.objects.count(), before)
