"""Book-host: artifact import, native Django rendering, and auth gating.

The host imports the FULL artifact; the public sees only online-only sections,
the private parts are gated behind login (only the owner has an account)."""
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from parody_web.models import Book, Section
from parody_web.templatetags.parody_web import render_book

ARTIFACT = {
    "schema_version": 2,
    "slug": "demo-book",
    "title": "Demo Book",
    "author": ["A. Author"],
    "book": {"name": "Demo", "editions": [{"id": "0", "isbn": "978-test"}]},
    "chapters": [{
        "title": "Hardware", "slug": "hardware", "hash": "h1",
        "sections": [
            {"title": "Specific T1 (public)", "slug": "specific-t1", "hash": "ef",
             "online_only": True,
             "html": '<p>The myRIO via {% media \'notebooks/x.jpg\' %}.</p>'
                     '<details><summary>Specs</summary>'
                     '<div class="version-list-item">SoC: Xilinx</div></details>',
             "online_resources": '<p>Extra: {% cite \'knuth1997\' %}.</p>'},
            {"title": "Licensed Chapter (private)", "slug": "licensed", "hash": "lz",
             "html": "<p>Copyrighted prose.</p>"},
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
class BookHostGatingTests(TestCase):
    def setUp(self):
        _import()
        self.owner = get_user_model().objects.create_superuser(
            "owner", "owner@example.com", "pw")
        self.anon = Client()
        self.signed_in = Client()
        self.signed_in.force_login(self.owner)

    def test_import_stored_fields(self):
        book = Book.objects.get(slug="demo-book")
        self.assertEqual(book.book_metadata["editions"][0]["isbn"], "978-test")
        self.assertTrue(Section.objects.get(slug="specific-t1").online_only)
        self.assertFalse(Section.objects.get(slug="licensed").online_only)

    def test_public_index_lists_only_online_only(self):
        r = self.anon.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Specific T1 (public)")
        self.assertNotContains(r, "Licensed Chapter (private)")

    def test_owner_index_lists_everything(self):
        r = self.signed_in.get("/")
        self.assertContains(r, "Specific T1 (public)")
        self.assertContains(r, "Licensed Chapter (private)")

    def test_public_section_renders_with_tags_resolved(self):
        r = self.anon.get("/hardware/specific-t1/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("/media/notebooks/x.jpg", html)
        self.assertNotIn("{%", html)
        self.assertIn("<details>", html)
        self.assertIn("Online resources", html)  # online_resources rendered

    def test_private_section_redirects_anonymous_to_login(self):
        r = self.anon.get("/hardware/licensed/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts/login", r["Location"])

    def test_owner_sees_private_section(self):
        r = self.signed_in.get("/hardware/licensed/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Copyrighted prose")

    def test_reimport_is_idempotent(self):
        before = Section.objects.count()
        _import()
        self.assertEqual(Section.objects.count(), before)
