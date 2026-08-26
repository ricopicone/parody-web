"""Per-chapter draft mode.

A chapter can be authored and numbered but not yet released. It must be
invisible to every reader the access policy excludes — **including signed-in
students**, which is the requirement this whole feature turns on:
`DefaultPolicy.is_owner` returns True for *any* authenticated user, so a test
that does not install a course-shaped policy passes for the wrong reason.

See docs/superpowers/specs/2026-08-23-per-chapter-draft-mode-design.md
"""
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from parody_web.access import DefaultPolicy
from parody_web.models import Book, Chapter


class StudentPolicy(DefaultPolicy):
    """A course-shaped policy: being signed in is not being staff.

    DefaultPolicy treats any authenticated user as the owner, which on a course
    site would mean every enrolled student. This is what homepage-django's
    CoursePolicy does in miniature.
    """

    def is_owner(self, request):
        return bool(request and getattr(request.user, "is_superuser", False))

    def can_view_drafts(self, request):
        return self.is_owner(request)


def _draft_artifact(draft_slugs=("two",)):
    """Three chapters, the middle one draft by default.

    Chapter three exists so a test can prove a draft does not renumber what
    follows it — the regression that would silently break every cross-reference.
    """
    def ch(slug, title):
        entry = {
            "title": title, "slug": slug, "hash": slug[:2],
            "sections": [{
                "title": f"{title} A", "slug": f"{slug}-a",
                "hash": slug[:2] + "a",
                "html": f"<p>Body of {title}. Token{slug}quokka.</p>",
            }],
        }
        if slug in draft_slugs:
            entry["draft"] = True
        return entry

    return {
        "schema_version": 2, "slug": "dbook", "title": "D Book",
        "author": ["A. Author"],
        "chapters": [ch("one", "One"), ch("two", "Two"), ch("three", "Three")],
    }


def _import_drafts(art=None):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, "a.json")
        p.write_text(json.dumps(art if art is not None else _draft_artifact()))
        call_command("import_artifact", str(p), "--slug", "dbook")


@override_settings(BOOK_SLUG="dbook")
class ChapterDraftImportTests(TestCase):
    def test_draft_flag_is_stored(self):
        _import_drafts()
        by = {c.slug: c for c in Book.objects.get(slug="dbook").chapters.all()}
        self.assertFalse(by["one"].draft)
        self.assertTrue(by["two"].draft)
        self.assertFalse(by["three"].draft)

    def test_absent_key_imports_as_not_draft(self):
        """Artifacts built before this feature must import unchanged."""
        _import_drafts(_draft_artifact(draft_slugs=()))
        self.assertEqual(Chapter.objects.filter(draft=True).count(), 0)

    def test_a_draft_does_not_renumber_the_chapters_after_it(self):
        _import_drafts(_draft_artifact(draft_slugs=()))
        plain = {c.slug: c.number for c in Chapter.objects.all()}
        _import_drafts(_draft_artifact(draft_slugs=("two",)))
        drafted = {c.slug: c.number for c in Chapter.objects.all()}
        self.assertEqual(plain, drafted)


@override_settings(BOOK_SLUG="dbook")
class DraftPolicyTests(TestCase):
    def setUp(self):
        _import_drafts()

    def test_default_policy_defers_to_is_owner(self):
        class YesOwner(DefaultPolicy):
            def is_owner(self, request):
                return True

        class NoOwner(DefaultPolicy):
            def is_owner(self, request):
                return False

        self.assertTrue(YesOwner().can_view_drafts(None))
        self.assertFalse(NoOwner().can_view_drafts(None))

    @override_settings(
        PARODY_WEB_ACCESS_POLICY="parody_web.tests_drafts.StudentPolicy")
    def test_visible_chapters_hides_drafts_from_a_non_owner(self):
        from parody_web.views import visible_chapters
        book = Book.objects.get(slug="dbook")
        self.assertEqual([c.slug for c in visible_chapters(book, None)],
                         ["one", "three"])

    def test_visible_chapters_shows_everything_to_an_owner(self):
        """DefaultPolicy with no request is not an owner, so pin the positive
        case with a policy that is."""
        from parody_web.views import visible_chapters
        book = Book.objects.get(slug="dbook")
        with override_settings(
                PARODY_WEB_ACCESS_POLICY="parody_web.tests_drafts.AlwaysOwner"):
            self.assertEqual([c.slug for c in visible_chapters(book, None)],
                             ["one", "two", "three"])


class AlwaysOwner(DefaultPolicy):
    def is_owner(self, request):
        return True


@override_settings(BOOK_SLUG="dbook",
                   PARODY_WEB_ACCESS_POLICY="parody_web.tests_drafts.StudentPolicy")
class DraftSurfaceTests(TestCase):
    """Every surface, for the reader the requirement turns on: a SIGNED-IN
    STUDENT. Without StudentPolicy these would pass for the wrong reason —
    DefaultPolicy.is_owner admits any authenticated user."""

    def setUp(self):
        _import_drafts()
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

    def test_toc_hides_draft_but_keeps_the_rest(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                resp = c.get("/")
                self.assertContains(resp, "One")
                self.assertContains(resp, "Three")
                self.assertNotContains(resp, "Two")

    def test_toc_shows_draft_to_staff(self):
        self.assertContains(self.as_staff.get("/"), "Two")

    def test_direct_chapter_url_is_404_not_403(self):
        """404, never 403 — a 403 confirms the chapter exists."""
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/two/").status_code, 404)
        self.assertEqual(self.as_staff.get("/two/").status_code, 200)

    def test_direct_section_url_is_404(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/two/two-a/").status_code, 404)
        self.assertEqual(self.as_staff.get("/two/two-a/").status_code, 200)

    def test_search_does_not_return_draft_text(self):
        """Assert on the RESULT LINK, not the word: the search page echoes the
        query back in its title and input, so a draft chapter's name is on the
        page either way."""
        for who, c in self._readers():
            with self.subTest(who=who):
                resp = c.get("/search/?q=Tokentwoquokka")
                self.assertNotContains(resp, "/two/two-a/")
                self.assertContains(resp, "No matches")
        staff = self.as_staff.get("/search/?q=Tokentwoquokka")
        self.assertContains(staff, "/two/two-a/")

    def test_search_still_finds_released_chapters(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertContains(c.get("/search/?q=Tokenthreequokka"),
                                    "/three/three-a/")

    def test_sitemap_omits_draft(self):
        self.assertNotContains(self.anon.get("/sitemap.xml"), "/two/")

    def test_subject_index_omits_draft(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertNotContains(c.get("/index/"), "Two")

    def test_section_pdf_of_a_draft_is_404(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/two/two-a/pdf/").status_code, 404)
                self.assertEqual(c.get("/two/two-a/pdf/view/").status_code, 404)

    def test_a_released_chapter_is_still_reachable(self):
        """The gate must not be over-broad."""
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/one/").status_code, 200)
                self.assertEqual(c.get("/one/one-a/").status_code, 200)
                self.assertEqual(c.get("/three/").status_code, 200)


@override_settings(BOOK_SLUG="dbook")
class DraftCrossRefTests(TestCase):
    """A released chapter may forward-reference a draft one — normal during a
    chapter-by-chapter rollout. The reference keeps its (correct) number and
    loses its link.

    This cannot vary by reader: number_artifact runs at IMPORT and its output is
    stored in Section.html, so staff see plain text too and reach the chapter
    through the contents.
    """

    def _import_with_ref(self, target_hash):
        art = _draft_artifact()
        art["chapters"][0]["sections"][0]["html"] = (
            f'<p>See <span class="hashref">{target_hash}</span>.</p>')
        _import_drafts(art)
        from parody_web.models import Section
        return Section.objects.get(slug="one-a").html

    def test_reference_to_a_released_chapter_is_still_a_link(self):
        html = self._import_with_ref("th")
        # lowercase: the label is recased for its position in the sentence
        self.assertIn("chapter 3", html)
        self.assertIn('<a class="xref"', html)

    def test_reference_into_a_draft_chapter_has_the_number_but_no_link(self):
        html = self._import_with_ref("tw")
        self.assertIn("chapter 2", html)          # right number: drafts hold theirs
        self.assertNotIn('<a class="xref"', html)  # but nothing to follow
        self.assertIn('<span class="xref"', html)
        self.assertNotIn("/two/", html)            # and no url leaked


@override_settings(BOOK_SLUG="dbook",
                   PARODY_WEB_ACCESS_POLICY="parody_web.tests_drafts.StudentPolicy")
class DraftShortCodeTests(TestCase):
    """The printed short code, which is the one surface that forgot to filter.

    `_resolve_code` walked `book.sections` unfiltered while the CHAPTER branch
    directly above it used visible_chapters — so a code printed against a
    section of an unreleased chapter redirected a student straight at it. The
    section view then answered 404, so no prose escaped; what escaped was the
    fact that the code resolves at all, and to which chapter slug.
    """

    def setUp(self):
        _import_drafts()
        User = get_user_model()
        self.anon = Client()
        self.as_student = Client()
        self.as_student.force_login(
            User.objects.create_user("stu", "stu@example.com", "pw"))
        self.as_staff = Client()
        self.as_staff.force_login(
            User.objects.create_superuser("boss", "boss@example.com", "pw"))

    def test_a_code_for_a_draft_section_does_not_resolve(self):
        # "twa" is chapter two's section hash; two is the draft chapter.
        for who, c in (("anonymous", self.anon), ("student", self.as_student)):
            with self.subTest(who=who):
                self.assertEqual(c.get("/twa").status_code, 404)

    def test_a_code_for_a_draft_chapter_does_not_resolve(self):
        for who, c in (("anonymous", self.anon), ("student", self.as_student)):
            with self.subTest(who=who):
                self.assertEqual(c.get("/tw").status_code, 404)

    def test_a_released_section_code_still_redirects(self):
        """The filter must not cost the feature its point."""
        resp = self.anon.get("/ona")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/one/one-a/", resp["Location"])

    def test_staff_can_still_follow_a_draft_code(self):
        resp = self.as_staff.get("/twa")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/two/two-a/", resp["Location"])


@override_settings(BOOK_SLUG="dbook",
                   PARODY_WEB_ACCESS_POLICY="parody_web.tests_drafts.StudentPolicy")
class DraftIndicatorTests(TestCase):
    """Staff see drafts, and must be able to TELL they are drafts.

    A chapter that is invisible to readers looks, to the one person who can see
    it, exactly like a published one — so the only person who can act on it is
    the one with no way to know. Everything asserted here is staff-only by
    construction: a reader who cannot see the chapter cannot see its marker.
    """

    def setUp(self):
        _import_drafts()
        User = get_user_model()
        self.as_staff = Client()
        self.as_staff.force_login(
            User.objects.create_superuser("boss", "boss@example.com", "pw"))
        self.as_student = Client()
        self.as_student.force_login(
            User.objects.create_user("stu", "stu@example.com", "pw"))

    def test_the_contents_marks_a_draft_chapter(self):
        self.assertContains(self.as_staff.get("/"), "draft-tag")

    def test_the_contents_marks_only_the_draft_chapter(self):
        """One tag, not one per chapter — the marker has to mean something."""
        self.assertEqual(self.as_staff.get("/").content.count(b"draft-tag"), 1)

    def test_the_chapter_page_says_so(self):
        page = self.as_staff.get("/two/")
        self.assertContains(page, "draft-tag")
        self.assertContains(page, "not yet visible to readers")

    def test_the_section_page_says_so(self):
        page = self.as_staff.get("/two/two-a/")
        self.assertContains(page, "not yet visible to readers")

    def test_a_released_section_says_nothing(self):
        page = self.as_staff.get("/one/one-a/")
        self.assertNotContains(page, "not yet visible to readers")
        self.assertNotContains(page, "draft-tag")

    def test_a_released_chapter_says_nothing(self):
        self.assertNotContains(self.as_staff.get("/one/"), "draft-tag")

    def test_a_student_sees_no_marker_because_they_see_no_draft(self):
        page = self.as_student.get("/")
        self.assertNotContains(page, "draft-tag")
        self.assertNotContains(page, "Two")
