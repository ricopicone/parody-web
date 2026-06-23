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
from parody_web.numbering import number_artifact
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
            {"title": "Hardware", "slug": "lead-in", "hash": "li",
             "online_only": True,
             "html": "<p>This chapter introduces the LEADINPROSE.</p>"},
            {"title": "Specific T1 (public)", "slug": "specific-t1", "hash": "ef",
             "online_only": True,
             "html": '<p>The myRIO via {% media \'notebooks/x.jpg\' %}.</p>'
                     '<details><summary>Specs</summary>'
                     '<div class="version-list-item">SoC: Xilinx</div></details>',
             "online_resources": '<p>Extra: {% cite \'knuth1997\' %}.</p>'},
            {"title": "Licensed Chapter (private)", "slug": "licensed", "hash": "lz",
             "preview": True, "html": "<p>Copyrighted prose.</p>"},
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

    def test_code_spans_wraps_backticks_and_escapes(self):
        from parody_web.templatetags.parody_web import code_spans
        out = code_spans("Function `sos2header()` for <C>")
        self.assertEqual(out, "Function <code>sos2header()</code> for &lt;C&gt;")
        # titles with no backticks are just escaped, unchanged otherwise
        self.assertEqual(code_spans("Plain title"), "Plain title")


class CrossRefResolutionTests(TestCase):
    """number_artifact resolves hashref spans, including the comma-separated
    multi-target form ([a,b,c]{.hashref}) the print build emits for \\cref{a,b,c}."""

    def _book(self):
        # two chapters so chapter hashes resolve to "Chapter 1"/"Chapter 2"
        return {
            "chapters": [
                {"title": "One", "slug": "one", "hash": "c1",
                 "sections": [{"title": "S", "slug": "s1", "hash": "s1",
                               "anchors": [], "html": ""}]},
                {"title": "Two", "slug": "two", "hash": "c2",
                 "sections": [{"title": "T", "slug": "t1", "hash": "t1",
                               "anchors": [], "html": ""}]},
            ]
        }

    def test_single_hashref_resolves(self):
        data = self._book()
        data["chapters"][0]["sections"][0]["html"] = (
            '<p>see <span class="hashref">c2</span></p>')
        number_artifact(data)
        html = data["chapters"][0]["sections"][0]["html"]
        self.assertIn('<a class="xref" href="/two/t1/">Chapter 2</a>', html)

    def test_comma_multitarget_groups_and_links_each(self):
        data = self._book()
        data["chapters"][0]["sections"][0]["html"] = (
            '<p>see <span class="hashref">c1,c2</span></p>')
        number_artifact(data)
        html = data["chapters"][0]["sections"][0]["html"]
        # shared word factored out + pluralized, each number a link, "and" join
        self.assertIn('Chapters <a class="xref" href="/one/s1/">1</a> and '
                      '<a class="xref" href="/two/t1/">2</a>', html)

    def test_edition_query_baked_into_xref_urls(self):
        # a non-default edition bakes ?ed=<id> into its cross-ref links so
        # in-edition navigation stays on that edition.
        data = self._book()
        data["chapters"][0]["sections"][0]["html"] = (
            '<p>see <span class="hashref">c2</span></p>')
        number_artifact(data, edition_query="?ed=ed1")
        html = data["chapters"][0]["sections"][0]["html"]
        self.assertIn('href="/two/t1/?ed=ed1"', html)

    def test_partial_multitarget_left_as_is(self):
        # if any member is unresolved we don't render a half-broken ref
        data = self._book()
        data["chapters"][0]["sections"][0]["html"] = (
            '<p>see <span class="hashref">c1,zz</span></p>')
        number_artifact(data)
        self.assertIn('<span class="hashref">c1,zz</span>',
                      data["chapters"][0]["sections"][0]["html"])

    def test_subfigure_float_shares_number_with_lettered_panels(self):
        # ::: {.subfigures #fig:multi} → one "Figure 1.2", panels (a)/(b);
        # a plain figure before it takes 1.1 (panels aren't counted as figures).
        data = {"chapters": [{"title": "C", "slug": "c", "hash": "c1",
            "sections": [{"title": "S", "slug": "s", "anchors": [
                {"id": "fig:solo", "type": "figure"},
                {"id": "fig:multi", "type": "figure"},
                {"id": "fig:pa", "type": "figure"},
                {"id": "fig:pb", "type": "figure"},
            ], "html":
                '<figure id="fig:solo" class="figure"><img>'
                '<figcaption class="figure-caption">Solo.</figcaption></figure>'
                '<p>see <span class="hashref">fig:multi</span> and '
                '<span class="hashref">fig:pb</span></p>'
                '<figure id="fig:multi" class="figure subfigures" data-rows="1">'
                '<figure id="fig:pa" class="subfigure"><img>'
                '<figcaption>First.</figcaption></figure>'
                '<figure id="fig:pb" class="subfigure"><img>'
                '<figcaption>Second.</figcaption></figure>'
                '<figcaption class="subfigures-caption">Both.</figcaption></figure>'}]}]}
        targets = number_artifact(data)
        self.assertEqual(targets["fig:solo"]["label"], "Figure 1.1")
        self.assertEqual(targets["fig:multi"]["label"], "Figure 1.2")
        self.assertEqual(targets["fig:pa"]["label"], "Figure 1.2a")
        self.assertEqual(targets["fig:pb"]["label"], "Figure 1.2b")
        html = data["chapters"][0]["sections"][0]["html"]
        # refs resolve; captions get the shared number + panel letters injected.
        # lowercase keys ([fig:…]) render lowercase labels (task #296).
        self.assertIn('<a class="xref" href="/c/s/#fig:multi">figure 1.2</a>', html)
        self.assertIn('<a class="xref" href="/c/s/#fig:pb">figure 1.2b</a>', html)
        self.assertIn('<span class="fignum">Figure 1.2:</span>', html)
        self.assertIn('<span class="subfignum">(a)</span> First.', html)

    def test_ref_label_follows_key_case(self):
        # task #296: lookup is case-insensitive but the label follows the key's
        # case — [@fig:x] -> "figure 1.1", [@Fig:x] -> "Figure 1.1". The
        # capitalized citation must resolve at all (it didn't before: the
        # target is keyed lowercase, so a case-sensitive .get missed it).
        data = {"chapters": [{"title": "C", "slug": "c", "hash": "c1",
            "sections": [{"title": "S", "slug": "s", "anchors": [
                {"id": "fig:plot", "type": "figure"}], "html":
                '<p>lower <span class="citation" data-cites="fig:plot">'
                '[@fig:plot]</span>, upper <span class="citation" '
                'data-cites="Fig:plot">[@Fig:plot]</span>, hashref '
                '<span class="hashref">Fig:plot</span>.</p>'}]}]}
        targets = number_artifact(data)
        # the stored label is canonical (capitalized); case is applied per-ref
        self.assertEqual(targets["fig:plot"]["label"], "Figure 1.1")
        html = data["chapters"][0]["sections"][0]["html"]
        self.assertIn('href="/c/s/#fig:plot">figure 1.1</a>', html)  # [@fig:…]
        self.assertIn('href="/c/s/#fig:plot">Figure 1.1</a>', html)  # [@Fig:…]

    def test_equation_refs_are_parenthesized(self):
        # task #296 follow-up: equation cross-refs read "equation (3.2)".
        data = {"chapters": [{"title": "C", "slug": "c", "hash": "c1",
            "sections": [{"title": "S", "slug": "s", "anchors": [
                {"id": "eq:euler", "type": "equation"}], "html":
                '<p>see <span class="citation" data-cites="eq:euler">'
                '[@eq:euler]</span> and <span class="citation" '
                'data-cites="Eq:euler">[@Eq:euler]</span>.</p>'}]}]}
        targets = number_artifact(data)
        self.assertEqual(targets["eq:euler"]["label"], "Equation (1.1)")
        html = data["chapters"][0]["sections"][0]["html"]
        self.assertIn('href="/c/s/#eq:euler">equation (1.1)</a>', html)
        self.assertIn('href="/c/s/#eq:euler">Equation (1.1)</a>', html)

    def _rights_book(self, preview):
        return {"chapters": [{"title": "C", "slug": "c", "hash": "c1",
            "sections": [{"title": "S", "slug": "s", "preview": preview, "anchors": [
                {"id": "fig:ni", "type": "figure"}], "html":
                '<figure id="fig:ni" class="figure" data-permission="permission">'
                "<img src='/media/ni.svg'>"
                '<figcaption class="figure-caption">NI figure.</figcaption></figure>'}]}]}

    def test_rights_figure_placeholdered_on_public_page(self):
        data = self._rights_book(preview=None)  # public-facing section
        number_artifact(data)
        html = data["chapters"][0]["sections"][0]["html"]
        self.assertNotIn("<img", html)               # image withheld
        self.assertIn("rights-placeholder", html)
        self.assertIn('<span class="fignum">Figure 1.1:</span>', html)  # still numbered

    def test_rights_figure_shown_on_preview_page(self):
        data = self._rights_book(preview=True)       # gated section → show normally
        number_artifact(data)
        html = data["chapters"][0]["sections"][0]["html"]
        self.assertIn("<img", html)
        self.assertNotIn("rights-placeholder", html)


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

    def test_public_index_lists_all_sections(self):
        # The full TOC is public; gating is per-section at view time (a preview
        # section is teased, not hidden from the index).
        r = self.anon.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Specific T1 (public)")
        self.assertContains(r, "Licensed Chapter (private)")
        self.assertContains(r, "preview")  # the preview section is flagged

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

    def test_preview_section_gates_anonymous(self):
        # A preview section shows the public a teaser + sign-in gate (200, not a
        # redirect); the owner sees the full text.
        r = self.anon.get("/hardware/licensed/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "This is a preview")
        self.assertContains(r, "Instructor login")

    def test_owner_sees_private_section(self):
        r = self.signed_in.get("/hardware/licensed/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Copyrighted prose")

    def test_reimport_is_idempotent(self):
        before = Section.objects.count()
        _import()
        self.assertEqual(Section.objects.count(), before)

    def test_index_links_chapter_and_omits_leadin_line(self):
        # The chapter heading links to its landing page, and the lead-in is no
        # longer a TOC line under the chapter.
        r = self.anon.get("/")
        self.assertContains(r, 'href="/hardware/"')
        self.assertNotContains(r, 'href="/hardware/lead-in/"')

    def test_chapter_page_shows_leadin_contents_and_continue(self):
        r = self.anon.get("/hardware/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("LEADINPROSE", html)               # lead-in prose shown
        self.assertIn("Specific T1 (public)", html)      # contents listed
        self.assertNotIn("{%", html)                     # tags resolved
        # continue button into the first content section
        self.assertIn('class="continue-button"', html)
        self.assertIn('href="/hardware/specific-t1/"', html)

    def test_chapter_page_404_for_unknown_slug(self):
        self.assertEqual(self.anon.get("/no-such-chapter/").status_code, 404)


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

    def test_non_default_edition_via_query(self):
        r = self.client.get("/?ed=ed1")
        self.assertEqual(r.status_code, 200)
        rs = self.client.get("/ch/overview/?ed=ed1")
        self.assertContains(rs, "ed1 body")

    def test_edition_only_section_absent_from_other_edition(self):
        self.assertEqual(self.client.get("/ch/whatsnew/").status_code, 200)
        self.assertEqual(
            self.client.get("/ch/whatsnew/?ed=ed1").status_code, 404)

    def test_unknown_edition_404(self):
        self.assertEqual(self.client.get("/?ed=nope").status_code, 404)

    def test_switcher_links_to_other_edition(self):
        r = self.client.get("/")
        self.assertContains(r, "edition-switcher")
        self.assertContains(r, '?ed=ed1')

    def test_query_pages_keep_edition_in_links(self):
        # breadcrumb + TOC links from an ed1 page stay on ?ed=ed1
        r = self.client.get("/ch/overview/?ed=ed1")
        self.assertContains(r, 'href="/?ed=ed1"')  # breadcrumb to ed1 TOC

    def test_sitemap_includes_all_editions(self):
        r = self.client.get("/sitemap.xml")
        body = r.content.decode()
        self.assertIn("/ch/overview/", body)            # default at root
        self.assertIn("/ch/overview/?ed=ed1", body)

    # ---- printed short codes (/q9-style QR targets) ----------------------
    def test_code_resolves_to_latest_edition_that_has_it(self):
        # ed2 is the default (latest); its overview hash → bare URL
        r = self.client.get("/oed2")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/ch/overview/")

    def test_code_only_in_older_edition_keeps_ed_query(self):
        # oed1 exists only in ed1 (non-default) → resolves with ?ed=ed1
        r = self.client.get("/oed1")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/ch/overview/?ed=ed1")

    def test_code_lookup_is_case_insensitive(self):
        self.assertEqual(
            self.client.get("/OED1")["Location"], "/ch/overview/?ed=ed1")

    def test_chapter_hash_code_resolves_to_chapter_page(self):
        # chapter hash c1 is in both editions → latest (ed2, default)
        self.assertEqual(self.client.get("/c1")["Location"], "/ch/")

    def test_code_with_trailing_slash_also_resolves(self):
        self.assertEqual(self.client.get("/oed1/")["Location"],
                         "/ch/overview/?ed=ed1")

    def test_unknown_code_404(self):
        self.assertEqual(self.client.get("/zzzz").status_code, 404)

    def test_bare_chapter_without_slash_redirects_to_chapter_page(self):
        # /ch (no code match, but a real chapter slug) behaves like /ch/
        r = self.client.get("/ch")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/ch/")

    def test_go_box_redirects_to_resolved_code(self):
        r = self.client.get("/go/?code=oed1")
        self.assertEqual(r["Location"], "/ch/overview/?ed=ed1")

    def test_go_box_bounces_to_index_on_miss(self):
        self.assertEqual(self.client.get("/go/?code=nope")["Location"], "/")

    def test_single_edition_book_unprefixed(self):
        # a book with no edition metadata keeps the bare root URLs
        _import()  # demo-book, no edition
        with override_settings(BOOK_SLUG="demo-book"):
            self.assertEqual(self.client.get("/").status_code, 200)
            book = Book.objects.get(slug="demo-book")
            self.assertTrue(book.is_default_edition)
            self.assertEqual(book.edition_id, "")


@override_settings(BOOK_SLUG="abook")
class CodeAnchorTests(TestCase):
    """A code can be a sub-section / figure / exercise anchor inside a section;
    it resolves to the section URL plus a #fragment to scroll to."""

    def setUp(self):
        art = {
            "schema_version": 2, "slug": "abook", "title": "A Book",
            "chapters": [{"title": "Ch", "slug": "ch", "hash": "c1", "sections": [
                {"title": "S", "slug": "sec", "hash": "se",
                 "anchors": [{"id": "fig:bode", "type": "figure", "hash": "fb"}],
                 "html": '<figure id="fig:bode" class="figure"><img>'
                         '<figcaption class="figure-caption">Bode.</figcaption>'
                         '</figure>'}]}],
        }
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "a.json")
            p.write_text(json.dumps(art))
            call_command("import_artifact", str(p), "--slug", "abook")
        self.client = Client()

    def test_anchor_hash_resolves_to_fragment(self):
        self.assertEqual(self.client.get("/fb")["Location"], "/ch/sec/#fig:bode")

    def test_anchor_id_resolves_to_fragment(self):
        self.assertEqual(
            self.client.get("/fig:bode")["Location"], "/ch/sec/#fig:bode")

    def test_section_hash_resolves_without_fragment(self):
        self.assertEqual(self.client.get("/se")["Location"], "/ch/sec/")


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


def _draft_artifact(edition_id, title, default, draft, body):
    return {
        "schema_version": 2, "slug": "dbook", "title": "D Book",
        "author": ["A. Author"],
        "edition": {"id": edition_id, "title": title, "default": default,
                    "draft": draft},
        "editions": [{"id": "ed1", "title": "First", "default": True,
                      "draft": False},
                     {"id": "ed2", "title": "Second", "default": False,
                      "draft": True}],
        "chapters": [{"title": "Ch", "slug": "ch", "hash": "c1", "sections": [
            {"title": "Overview", "slug": "overview", "hash": "o" + edition_id,
             "html": f"<p>{body}</p>"}]}],
    }


@override_settings(BOOK_SLUG="dbook")
class DraftEditionTests(TestCase):
    def setUp(self):
        for art in (_draft_artifact("ed1", "First", True, False, "ed1 body"),
                    _draft_artifact("ed2", "Second", False, True, "ed2 body")):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d, "a.json")
                p.write_text(json.dumps(art))
                call_command("import_artifact", str(p), "--slug", "dbook")
        self.owner = get_user_model().objects.create_superuser(
            "owner", "owner@example.com", "pw")
        self.anon = Client()
        self.signed_in = Client()
        self.signed_in.force_login(self.owner)

    def test_draft_flag_stored(self):
        self.assertTrue(Book.objects.get(slug="dbook", edition_id="ed2").draft)
        self.assertFalse(Book.objects.get(slug="dbook", edition_id="ed1").draft)

    def test_public_cannot_see_draft(self):
        # the default (public) edition is served at the root; draft is hidden
        self.assertContains(self.anon.get("/ch/overview/"), "ed1 body")
        self.assertNotContains(self.anon.get("/"), "(in development)")
        # draft pages 404 for the public
        self.assertEqual(self.anon.get("/?ed=ed2").status_code, 404)
        self.assertEqual(
            self.anon.get("/ch/overview/?ed=ed2").status_code, 404)

    def test_owner_can_see_draft(self):
        r = self.signed_in.get("/?ed=ed2")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "in development")    # banner
        self.assertContains(r, "(in development)")  # switcher flag
        # and the draft edition's actual content
        self.assertContains(
            self.signed_in.get("/ch/overview/?ed=ed2"), "ed2 body")

    def test_sitemap_excludes_draft(self):
        body = self.anon.get("/sitemap.xml").content.decode()
        self.assertIn("/ch/overview/", body)         # ed1 (default, root)
        self.assertNotIn("ed=ed2", body)

    def test_publish_edition_command_makes_it_public(self):
        call_command("publish_edition", "ed2", "--slug", "dbook")
        self.assertFalse(Book.objects.get(slug="dbook", edition_id="ed2").draft)
        self.assertEqual(self.anon.get("/?ed=ed2").status_code, 200)

    def test_unpublish_edition_command_hides_it(self):
        call_command("publish_edition", "ed2", "--slug", "dbook")
        call_command("unpublish_edition", "ed2", "--slug", "dbook")
        self.assertTrue(Book.objects.get(slug="dbook", edition_id="ed2").draft)
        self.assertEqual(self.anon.get("/?ed=ed2").status_code, 404)
