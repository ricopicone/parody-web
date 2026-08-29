"""Per-section draft mode.

The chapter is not always the right unit of release. A section carries its own
draft status, resolved against its chapter's by `parody` before the artifact is
written — so everything here gates on the SECTION, and a chapter is visible when
it is released **or still holds a released section**.

The negative cases are the deliverable, and they run under the `StudentPolicy`
of tests_drafts: `DefaultPolicy.is_owner` returns True for any authenticated
user, so a test without a course-shaped policy passes for the wrong reason.

See docs/superpowers/specs/2026-08-29-section-level-drafts-design.md
"""
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from parody_web.models import Section

POLICY = "parody_web.tests_drafts.StudentPolicy"

# chapter one is released, chapter two is a draft. Section titles are distinct
# words so a "not on the page" assertion cannot pass on a substring of another.
LAYOUT = {
    "one": [("one-a", "Alpha", "oa"), ("one-b", "Bravo", "ob")],
    "two": [("two-a", "Charlie", "ta"), ("two-b", "Delta", "tb")],
}


def _artifact(chapter_drafts=("two",), section_drafts=None):
    """Two chapters of two sections.

    `section_drafts` maps "<ch>/<sec>" to the EFFECTIVE flag, exactly as parody
    resolves it into the artifact — the web side never sees the tri-state.
    """
    section_drafts = section_drafts or {}
    chapters = []
    for ch, secs in LAYOUT.items():
        sections = []
        for slug, title, h in secs:
            sec = {
                "title": title, "slug": slug, "hash": h,
                "html": (f'<p>Body of {title}. Token{slug}quokka. '
                         f'<span class="keyword">{title}term</span></p>'),
                # A section-level cross-reference target, as the writer
                # synthesizes it from the front-matter id.
                "anchors": [{"type": "heading", "level": 2, "is_section": True,
                             "id": slug, "hash": h, "title": title}],
            }
            # Exactly what parody emits: the key on every section of a DRAFT
            # chapter (true or false, because silence there means a pre-0.55.0
            # artifact), and only when true elsewhere.
            effective = section_drafts.get(f"{ch}/{slug}", ch in chapter_drafts)
            if effective or ch in chapter_drafts:
                sec["draft"] = bool(effective)
            sections.append(sec)
        entry = {"title": ch.title(), "slug": ch, "hash": ch[:2],
                 "sections": sections}
        if ch in chapter_drafts:
            entry["draft"] = True
        chapters.append(entry)
    return {"schema_version": 2, "slug": "sbook", "title": "S Book",
            "author": ["A. Author"], "chapters": chapters}


def _import(art=None):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, "a.json")
        p.write_text(json.dumps(art if art is not None else _artifact()))
        call_command("import_artifact", str(p), "--slug", "sbook")


class _Readers(TestCase):
    """Three clients, because the requirement turns on the middle one."""

    def setUp(self):
        User = get_user_model()
        self.anon = Client()
        self.as_student = Client()
        self.as_student.force_login(
            User.objects.create_user("stu", "stu@example.com", "pw"))
        self.as_staff = Client()
        self.as_staff.force_login(
            User.objects.create_superuser("boss", "boss@example.com", "pw"))

    def _readers(self):
        return (("anonymous", self.anon), ("student", self.as_student))


@override_settings(BOOK_SLUG="sbook")
class SectionDraftImportTests(TestCase):

    def test_the_flag_is_stored(self):
        _import(_artifact(chapter_drafts=(), section_drafts={"one/one-b": True}))
        by = {s.slug: s for s in Section.objects.all()}
        self.assertTrue(by["one-b"].draft)
        self.assertFalse(by["one-a"].draft)

    def test_an_absent_key_imports_as_not_draft(self):
        _import(_artifact(chapter_drafts=()))
        self.assertFalse(any(s.draft for s in Section.objects.all()))

    def test_a_draft_chapters_sections_arrive_marked(self):
        """parody resolved the inheritance; the web side re-derives nothing."""
        _import()
        by = {s.slug: s for s in Section.objects.all()}
        self.assertTrue(by["two-a"].draft and by["two-b"].draft)
        self.assertFalse(by["one-a"].draft or by["one-b"].draft)

    def test_a_published_section_of_a_draft_chapter(self):
        _import(_artifact(section_drafts={"two/two-a": False}))
        by = {s.slug: s for s in Section.objects.all()}
        self.assertFalse(by["two-a"].draft)
        self.assertTrue(by["two-b"].draft)
        # The chapter keeps its own flag — it still drives the staff badge.
        self.assertTrue(by["two-a"].chapter.draft)


@override_settings(BOOK_SLUG="sbook", PARODY_WEB_ACCESS_POLICY=POLICY)
class SectionDraftSurfaceTests(_Readers):
    """One draft section in a released chapter (one-b), one released section in
    a draft chapter (two-a). Every surface, for all three readers."""

    def setUp(self):
        super().setUp()
        _import(_artifact(section_drafts={"one/one-b": True,
                                          "two/two-a": False}))

    def test_the_contents_hides_a_draft_section(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                resp = c.get("/")
                self.assertContains(resp, "Alpha")
                self.assertNotContains(resp, "Bravo")

    def test_the_contents_shows_a_released_section_of_a_draft_chapter(self):
        """And so lists its chapter, which would otherwise be unreachable: no
        TOC line, no chapter page and no nav path into it."""
        for who, c in self._readers():
            with self.subTest(who=who):
                resp = c.get("/")
                self.assertContains(resp, "Charlie")
                self.assertNotContains(resp, "Delta")

    def test_staff_see_every_section(self):
        resp = self.as_staff.get("/")
        for title in ("Alpha", "Bravo", "Charlie", "Delta"):
            self.assertContains(resp, title)

    def test_a_draft_section_is_404_not_403(self):
        """404, never 403 — a 403 confirms the section exists."""
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/one/one-b/").status_code, 404)
                self.assertEqual(c.get("/two/two-b/").status_code, 404)
        self.assertEqual(self.as_staff.get("/one/one-b/").status_code, 200)

    def test_a_released_section_of_a_draft_chapter_is_reachable(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                resp = c.get("/two/two-a/")
                self.assertEqual(resp.status_code, 200)
                self.assertContains(resp, "Tokentwo-aquokka")

    def test_a_released_section_is_still_reachable(self):
        """The gate must not be over-broad."""
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/one/one-a/").status_code, 200)

    def test_a_partly_released_chapter_lists_only_what_is_released(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                resp = c.get("/two/")
                self.assertEqual(resp.status_code, 200)
                self.assertContains(resp, "Charlie")
                self.assertNotContains(resp, "Delta")

    def test_search_does_not_return_a_draft_section(self):
        """Assert on the RESULT LINK, not the word: the search page echoes the
        query back, so the token is on the page either way."""
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertNotContains(c.get("/search/?q=Tokenone-bquokka"),
                                       "/one/one-b/")
                self.assertNotContains(c.get("/search/?q=Tokentwo-bquokka"),
                                       "/two/two-b/")
        self.assertContains(self.as_staff.get("/search/?q=Tokenone-bquokka"),
                            "/one/one-b/")

    def test_search_still_finds_released_sections(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertContains(c.get("/search/?q=Tokenone-aquokka"),
                                    "/one/one-a/")
                self.assertContains(c.get("/search/?q=Tokentwo-aquokka"),
                                    "/two/two-a/")

    def test_the_subject_index_omits_a_draft_section(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                resp = c.get("/index/")
                self.assertContains(resp, "Alphaterm")
                self.assertNotContains(resp, "Bravoterm")
                self.assertNotContains(resp, "Deltaterm")

    def test_the_sitemap_omits_a_draft_section(self):
        body = self.anon.get("/sitemap.xml").content.decode()
        self.assertIn("/one/one-a/", body)
        self.assertIn("/two/two-a/", body)
        self.assertNotIn("/one/one-b/", body)
        self.assertNotIn("/two/two-b/", body)

    def test_a_short_code_for_a_draft_section_does_not_resolve(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/ob").status_code, 404)
                self.assertEqual(c.get("/tb").status_code, 404)

    def test_a_released_section_code_still_redirects(self):
        resp = self.anon.get("/ta")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/two/two-a/", resp["Location"])

    def test_staff_can_still_follow_a_draft_code(self):
        resp = self.as_staff.get("/ob")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/one/one-b/", resp["Location"])

    def test_the_section_pdf_of_a_draft_is_404(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/one/one-b/pdf/").status_code, 404)
                self.assertEqual(
                    c.get("/one/one-b/pdf/view/").status_code, 404)

    def test_the_nav_does_not_walk_into_a_draft_section(self):
        """prev/next is built from the visible list, so the link out of one-a
        must skip one-b entirely."""
        body = self.anon.get("/one/one-a/").content.decode()
        self.assertNotIn("/one/one-b/", body)


@override_settings(BOOK_SLUG="sbook", PARODY_WEB_ACCESS_POLICY=POLICY)
class WhollyDraftChapterTests(_Readers):
    """A chapter with nothing released behaves exactly as it did before this
    feature — the whole-chapter case is now derived, not special-cased."""

    def setUp(self):
        super().setUp()
        _import()   # chapter two draft, both its sections inheriting

    def test_the_chapter_is_absent_from_the_contents(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                resp = c.get("/")
                self.assertNotContains(resp, "Charlie")
                self.assertNotContains(resp, "Delta")

    def test_the_chapter_page_is_404(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/two/").status_code, 404)
        self.assertEqual(self.as_staff.get("/two/").status_code, 200)

    def test_visible_chapters_hides_it(self):
        from parody_web.models import Book
        from parody_web.views import visible_chapters
        book = Book.objects.get(slug="sbook")
        self.assertEqual([c.slug for c in visible_chapters(book, None)], ["one"])


@override_settings(BOOK_SLUG="sbook")
class SectionDraftCrossRefTests(TestCase):
    """A reference into a draft SECTION keeps its number and loses its link,
    exactly as one into a draft chapter does.

    This cannot vary by reader: number_artifact runs at IMPORT and its output is
    stored in Section.html, so staff see plain text too and reach the section
    through the contents.
    """

    def _import_with_ref(self, target_hash, **kw):
        art = _artifact(**kw)
        art["chapters"][0]["sections"][0]["html"] = (
            f'<p>See <span class="hashref">{target_hash}</span>.</p>')
        _import(art)
        return Section.objects.get(slug="one-a").html

    def test_a_reference_into_a_draft_section_has_the_number_but_no_link(self):
        html = self._import_with_ref(
            "ob", chapter_drafts=(), section_drafts={"one/one-b": True})
        self.assertIn("section 1.2", html)          # right number: it holds it
        self.assertNotIn('<a class="xref"', html)   # but nothing to follow
        self.assertIn('<span class="xref"', html)
        self.assertNotIn("/one/one-b/", html)       # and no url leaked

    def test_a_reference_into_a_released_section_is_still_a_link(self):
        html = self._import_with_ref("ob", chapter_drafts=())
        self.assertIn("section 1.2", html)
        self.assertIn('<a class="xref"', html)
        self.assertIn("/one/one-b/", html)

    def test_a_reference_to_a_partly_released_chapter_enters_at_a_released_section(self):
        """A chapter reference points at the chapter's first section — which
        must be the first RELEASED one, or the link lands on a 404."""
        html = self._import_with_ref("tw", section_drafts={"two/two-b": False})
        self.assertIn("/two/two-b/", html)          # two-a is still draft
        self.assertNotIn("/two/two-a/", html)


@override_settings(BOOK_SLUG="sbook", PARODY_WEB_ACCESS_POLICY=POLICY)
class SectionDraftMarkerTests(_Readers):
    """Staff see the draft material; they must be told which of it is draft."""

    def setUp(self):
        super().setUp()
        _import(_artifact(chapter_drafts=(), section_drafts={"one/one-b": True}))

    def test_the_contents_marks_the_draft_section(self):
        body = self.as_staff.get("/").content.decode()
        self.assertEqual(body.count("draft-tag"), 1)

    def test_the_section_page_says_so(self):
        self.assertContains(self.as_staff.get("/one/one-b/"), "draft-banner")

    def test_a_released_section_says_nothing(self):
        self.assertNotContains(self.as_staff.get("/one/one-a/"), "draft-banner")

    def test_a_student_sees_no_marker_because_they_see_no_draft(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertNotContains(c.get("/"), "draft-tag")


@override_settings(BOOK_SLUG="sbook")
class OlderArtifactTests(TestCase):
    """An artifact built before 0.55.0 marks a draft CHAPTER and says nothing
    about its sections. parody now says so on every section of a draft chapter,
    so silence there can only mean an older artifact — and the importer has to
    inherit for it, or a book pinned to an older parody would publish every
    unreleased chapter it has on the next deploy.
    """

    def test_a_draft_chapter_with_unmarked_sections_still_hides_them(self):
        art = _artifact()
        for sec in art["chapters"][1]["sections"]:
            sec.pop("draft")          # as a pre-0.55.0 build wrote it
        _import(art)
        by = {s.slug: s for s in Section.objects.all()}
        self.assertTrue(by["two-a"].draft and by["two-b"].draft)
        self.assertFalse(by["one-a"].draft or by["one-b"].draft)


@override_settings(BOOK_SLUG="sbook", PARODY_WEB_ACCESS_POLICY=POLICY)
class PartlyReleasedChapterMarkerTests(_Readers):
    """A partly released chapter is the case where the per-section marker is
    the only thing that can say which half is which — its own tag cannot."""

    def setUp(self):
        super().setUp()
        _import(_artifact(section_drafts={"two/two-a": False}))

    def test_the_contents_marks_the_draft_section_of_a_partly_released_chapter(self):
        body = self.as_staff.get("/").content.decode()
        # the chapter's own tag, plus one for its unreleased section
        self.assertEqual(body.count("draft-tag"), 2)

    def test_a_wholly_draft_chapter_says_it_once(self):
        _import()   # both of chapter two's sections inherit the draft
        body = self.as_staff.get("/").content.decode()
        self.assertEqual(body.count("draft-tag"), 1)

    def test_the_released_section_of_a_draft_chapter_is_not_called_a_draft(self):
        resp = self.as_staff.get("/two/two-a/")
        self.assertNotContains(resp, "This section is <strong>in development")
        self.assertContains(resp, "the section itself is released")


@override_settings(BOOK_SLUG="sbook")
class MigrationBackfillTests(TestCase):
    """`migrate` alone must be safe.

    The new column defaults to False and the views gate on it, so a deploy that
    migrated without re-importing would publish every unreleased chapter in the
    database. The data migration inherits the chapter's flag for the rows that
    existed before it — which is exactly right, since none of them could carry
    a per-section flag.
    """

    def test_the_backfill_gives_a_draft_chapters_sections_its_flag(self):
        import importlib

        from django.apps import apps as django_apps

        mod = importlib.import_module(
            "parody_web.migrations.0014_section_draft")

        _import()                       # chapter two draft, sections marked
        # Undo it, standing in for rows written before the column existed.
        Section.objects.update(draft=False)

        mod.inherit_the_chapters_flag(django_apps, None)

        by = {s.slug: s for s in Section.objects.all()}
        self.assertTrue(by["two-a"].draft and by["two-b"].draft)
        self.assertFalse(by["one-a"].draft or by["one-b"].draft)


@override_settings(BOOK_SLUG="sbook", PARODY_WEB_ACCESS_POLICY=POLICY)
class ChapterBannerAccuracyTests(_Readers):
    """A partly released chapter IS visible to readers, so the chapter banner
    must stop saying it is not."""

    def test_a_partly_released_chapter_does_not_claim_to_be_hidden(self):
        _import(_artifact(section_drafts={"two/two-a": False}))
        resp = self.as_staff.get("/two/")
        self.assertNotContains(resp, "not yet visible to readers")
        self.assertContains(resp, "readers can see them")

    def test_a_wholly_draft_chapter_still_says_it_is_hidden(self):
        _import()
        self.assertContains(self.as_staff.get("/two/"),
                            "not yet visible to readers")
