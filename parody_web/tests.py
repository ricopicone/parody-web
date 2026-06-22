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


def _edition_artifact(edition_id, title, default, *, body, extra_section=False):
    sections = [{"title": "Overview", "slug": "overview", "hash": "o" + edition_id,
                 "html": f"<p>{body}</p>"}]
    if extra_section:
        sections.append({"title": "What's new", "slug": "whatsnew",
                         "hash": "w" + edition_id, "html": "<p>new here</p>"})
    return {
        "schema_version": 2, "slug": "vbook", "title": "V Book",
        "author": ["A. Author"],
        "edition": {"id": edition_id, "title": title,
                    "tracks": {"ts": edition_id.upper()}, "default": default},
        "editions": [{"id": "ed1", "title": "First", "default": False},
                     {"id": "ed2", "title": "Second", "default": True}],
        "chapters": [{"title": "Ch", "slug": "ch", "hash": "c1",
                      "sections": sections}],
    }


def _import_edition(art):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, "a.json")
        p.write_text(json.dumps(art))
        call_command("import_artifact", str(p), "--slug", "vbook")


@override_settings(BOOK_SLUG="vbook")
class EditionTests(TestCase):
    def setUp(self):
        _import_edition(_edition_artifact("ed1", "First", False, body="ed1 body"))
        _import_edition(_edition_artifact("ed2", "Second", True, body="ed2 body",
                                          extra_section=True))
        self.client = Client()

    def test_each_edition_is_its_own_book_row(self):
        self.assertEqual(Book.objects.filter(slug="vbook").count(), 2)
        ed2 = Book.objects.get(slug="vbook", edition_id="ed2")
        self.assertTrue(ed2.edition_default)
        self.assertEqual(ed2.edition_title, "Second")

    def test_root_serves_default_edition(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        # default = ed2 (latest); its extra section appears in the TOC
        self.assertContains(r, "What&#x27;s new")

    def test_default_section_at_root(self):
        r = self.client.get("/ch/overview/")
        self.assertContains(r, "ed2 body")
        self.assertNotContains(r, "ed1 body")

    def test_non_default_edition_under_prefix(self):
        r = self.client.get("/editions/ed1/")
        self.assertEqual(r.status_code, 200)
        rs = self.client.get("/editions/ed1/ch/overview/")
        self.assertContains(rs, "ed1 body")

    def test_edition_only_section_absent_from_other_edition(self):
        self.assertEqual(self.client.get("/ch/whatsnew/").status_code, 200)
        self.assertEqual(
            self.client.get("/editions/ed1/ch/whatsnew/").status_code, 404)

    def test_unknown_edition_404(self):
        self.assertEqual(self.client.get("/editions/nope/").status_code, 404)

    def test_switcher_links_to_other_edition(self):
        r = self.client.get("/")
        self.assertContains(r, "edition-switcher")
        self.assertContains(r, '/editions/ed1/')

    def test_prefixed_pages_keep_edition_in_links(self):
        # breadcrumb + TOC links from an ed1 page stay under /editions/ed1/
        r = self.client.get("/editions/ed1/ch/overview/")
        self.assertContains(r, 'href="/editions/ed1/"')  # breadcrumb to ed1 TOC

    def test_sitemap_includes_all_editions(self):
        r = self.client.get("/sitemap.xml")
        body = r.content.decode()
        self.assertIn("/ch/overview/", body)            # default at root
        self.assertIn("/editions/ed1/ch/overview/", body)

    def test_single_edition_book_unprefixed(self):
        # a book with no edition metadata keeps the bare root URLs
        _import()  # demo-book, no edition
        with override_settings(BOOK_SLUG="demo-book"):
            self.assertEqual(self.client.get("/").status_code, 200)
            book = Book.objects.get(slug="demo-book")
            self.assertTrue(book.is_default_edition)
            self.assertEqual(book.edition_id, "")


PARTS_ARTIFACT = {
    "schema_version": 2, "slug": "pbook", "title": "P Book",
    "author": ["A. Author"],
    "parts": [{
        "track": "ts", "version": "T1", "title": "T1 target system",
        "description": "The T1 system.",
        "components": [{
            "subsystem": "target-computer", "subsystem_title": "Target computer",
            "name": "NI myRIO 1900", "kind": "single-board computer",
            "description": "An SBC.", "hash": "tc", "quantity": "1",
            "specs": [["System on a chip (SoC)", "Xilinx Z-7010"]],
            "suppliers": [{"name": "NI", "url": "https://ni.com"}],
            "choices": [{"kind": "specific", "name": "Grayhill 88BB2",
                         "description": "A keypad.", "hash": "g8", "fields": [],
                         "suppliers": [{"name": "Digi-Key",
                                        "url": "https://digikey.com/x"}]}],
        }],
    }],
    "chapters": [{"title": "Ch", "slug": "ch", "hash": "c1", "sections": [
        {"title": "Overview", "slug": "overview", "hash": "o1",
         "html": "<p>body</p>"}]}],
}


@override_settings(BOOK_SLUG="pbook")
class SystemsTests(TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "a.json")
            p.write_text(json.dumps(PARTS_ARTIFACT))
            call_command("import_artifact", str(p), "--slug", "pbook")
        self.client = Client()

    def test_parts_stored_on_book(self):
        book = Book.objects.get(slug="pbook")
        self.assertEqual(book.parts[0]["version"], "T1")

    def test_systems_page_renders_components_and_suppliers(self):
        r = self.client.get("/systems/T1/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "NI myRIO 1900")
        self.assertContains(r, "Xilinx Z-7010")
        self.assertContains(r, "https://ni.com")
        # specific device choice + its supplier link
        self.assertContains(r, "Grayhill 88BB2")
        self.assertContains(r, "https://digikey.com/x")

    def test_unknown_system_404(self):
        self.assertEqual(self.client.get("/systems/T9/").status_code, 404)

    def test_index_links_to_systems(self):
        r = self.client.get("/")
        self.assertContains(r, "Hardware systems")
        self.assertContains(r, "/systems/T1/")

    def test_sitemap_includes_systems(self):
        r = self.client.get("/sitemap.xml")
        self.assertIn("/systems/T1/", r.content.decode())

    def test_book_without_parts_has_no_systems_section(self):
        _import()  # demo-book, no parts
        with override_settings(BOOK_SLUG="demo-book"):
            r = self.client.get("/")
            self.assertNotContains(r, "Hardware systems")
            self.assertEqual(self.client.get("/systems/T1/").status_code, 404)
