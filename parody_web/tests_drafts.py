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
                "html": f"<p>Body of {title}.</p>",
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
