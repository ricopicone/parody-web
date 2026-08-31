"""`.staff-only` blocks stop at the reader who is not staff.

The block travels in the artifact — one artifact serves both audiences — and is
removed here, per reader, by `can_view_staff_notes`.

Four surfaces serve it, and only the first is the one anyone thinks of:

1. the solution page
2. the section body
3. the section's meta description, served to crawlers
4. the search index, whose snippets are matched against stored plain text

3 and 4 are the reason this lives in parody-web rather than in a host's
template. They are silent: nothing on the page says the description leaked, and
a search snippet is served to whoever typed the query.

`DefaultPolicy.is_owner` returns True for *any* authenticated user, so a test
that does not install a course-shaped policy passes for the wrong reason —
same trap as tests_drafts.py, and the same StudentPolicy answer.

See docs/superpowers/specs/2026-08-31-starred-and-staff-only-design.md in the
parody repo.
"""
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from parody_web.access import DefaultPolicy
from parody_web.models import Section
from parody_web.staffonly import strip_staff_only

BLOCK = ('<div class="staff-only"><p>Insist on the sign.</p></div>')
WHOLE = f'<p>Answer.</p>{BLOCK}<p>After.</p>'


class StripStaffOnlyTests(TestCase):
    """The scanner, on its own. Ported from the homepage-django stripper this
    replaces, whose cases were paid for in production."""

    def test_it_removes_the_block_and_keeps_the_rest(self):
        out = strip_staff_only(WHOLE)
        self.assertIn("<p>Answer.</p>", out)
        self.assertIn("<p>After.</p>", out)
        self.assertNotIn("Insist on the sign", out)
        self.assertNotIn("staff-only", out)

    def test_content_without_the_class_is_untouched(self):
        html = "<p>Ordinary.</p><div class='note'>Note.</div>"
        self.assertEqual(strip_staff_only(html), html)

    def test_every_block_goes_not_just_the_first(self):
        out = strip_staff_only(WHOLE + WHOLE)
        self.assertNotIn("Insist on the sign", out)
        self.assertEqual(out.count("<p>Answer.</p>"), 2)

    def test_a_nested_div_does_not_end_the_block_early(self):
        html = ('<p>A.</p><div class="staff-only">'
                '<div class="note">deep</div>shallow</div><p>B.</p>')
        out = strip_staff_only(html)
        self.assertNotIn("deep", out)
        self.assertNotIn("shallow", out)
        self.assertIn("<p>B.</p>", out)

    def test_other_attributes_and_classes_do_not_hide_it(self):
        # `.staff-only .grading-notes` is the shape books write: one class is
        # the access mark, the other is presentational.
        html = ('<div id="gn" class="prose staff-only grading-notes mt-4"'
                ' data-x="1">secret</div>')
        self.assertNotIn("secret", strip_staff_only(html))

    def test_an_unclosed_block_drops_the_remainder(self):
        # Fails closed. Half a page is a bug report; half an answer key is not
        # recoverable.
        html = '<p>Answer.</p><div class="staff-only"><p>secret</p>'
        out = strip_staff_only(html)
        self.assertIn("<p>Answer.</p>", out)
        self.assertNotIn("secret", out)

    def test_a_similar_class_is_not_matched(self):
        html = '<div class="staff-only-ish">keep</div>'
        self.assertIn("keep", strip_staff_only(html))

    def test_empty_and_none(self):
        self.assertEqual(strip_staff_only(""), "")
        self.assertIsNone(strip_staff_only(None))


class StudentPolicy(DefaultPolicy):
    """Signed in is not staff — what a course site's policy actually says."""

    def is_owner(self, request):
        return bool(request and getattr(request.user, "is_superuser", False))

    def can_view_solution(self, request, section, exercise_id):
        """The whole scenario, in one line: the due date has passed, so the
        solution is OPEN to the student. That is the point of posting it — and
        it is exactly when the marking notes at the end must not open too."""
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated)


ARTIFACT = {
    "schema_version": 2, "slug": "gbook", "title": "G Book",
    "author": ["A. Author"],
    "chapters": [{"title": "C", "slug": "c", "hash": "c1", "sections": [{
        "title": "S", "slug": "s", "hash": "sa",
        "html": ('<p>Public prose about quokkas.</p>'
                 '<div class="staff-only"><p>SECRETPROSE marking note.</p>'
                 '</div>'),
        "anchors": [{"id": "p1", "type": "exercise", "hash": "p1"}],
        "solutions": {"p1": {
            "title": "Screw axis",
            "content": ('<p>The answer is the contact point.</p>'
                        '<div class="staff-only"><p>SECRETNOTES half credit'
                        ' for the magnitude.</p></div>'),
        }},
    }]}],
}


def _import():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, "a.json")
        p.write_text(json.dumps(ARTIFACT))
        call_command("import_artifact", str(p), "--slug", "gbook")


@override_settings(BOOK_SLUG="gbook",
                   PARODY_WEB_ACCESS_POLICY=
                   "parody_web.tests_staff_only.StudentPolicy")
class StaffOnlySurfaceTests(TestCase):
    """All four surfaces, in both roles."""

    def setUp(self):
        _import()
        User = get_user_model()
        User.objects.create_user("student", password="pw")
        User.objects.create_superuser("staff", "s@example.com", "pw")

    def _as(self, who):
        c = Client()
        if who:
            c.login(username=who, password="pw")
        return c

    # --- 1. the solution page ---

    def test_a_student_gets_the_solution_without_the_notes(self):
        r = self._as("student").get("/c/s/solutions/p1/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "The answer is the contact point")
        self.assertNotContains(r, "SECRETNOTES")

    def test_staff_get_the_whole_solution(self):
        r = self._as("staff").get("/c/s/solutions/p1/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SECRETNOTES")

    # --- 2. the section body ---

    def test_a_student_gets_the_section_without_the_notes(self):
        r = self._as("student").get("/c/s/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Public prose about quokkas")
        self.assertNotContains(r, "SECRETPROSE")

    def test_staff_get_the_whole_section(self):
        r = self._as("staff").get("/c/s/")
        self.assertContains(r, "SECRETPROSE")

    # --- 3. the meta description, served to crawlers ---

    def test_the_meta_description_never_carries_staff_notes(self):
        # Not per-reader: it is served to crawlers, so it is the public text
        # even when the reader in front of us is staff.
        for who in (None, "student", "staff"):
            with self.subTest(who=who):
                r = self._as(who).get("/c/s/")
                head = r.content.decode().split("</head>")[0]
                self.assertNotIn("SECRETPROSE", head)

    # --- 4. the search index ---

    def test_staff_notes_are_kept_out_of_the_search_index(self):
        # Snippets come from a stored column with no per-reader variant, so
        # the strip happens at import. Staff lose search over their own notes;
        # nobody gets them in a highlighted snippet.
        plain = Section.objects.get(slug="s").plain
        self.assertIn("quokkas", plain)
        self.assertNotIn("SECRETPROSE", plain)

    def test_search_returns_no_staff_snippet(self):
        for who in (None, "student", "staff"):
            with self.subTest(who=who):
                r = self._as(who).get("/search/?q=SECRETPROSE")
                self.assertNotContains(r, "marking note")


@override_settings(BOOK_SLUG="gbook")
class StaffOnlyDefaultPolicyTests(TestCase):
    """Without an override, the hook follows is_owner — parody-web's own rule."""

    def setUp(self):
        _import()
        get_user_model().objects.create_user("owner", password="pw")

    def test_the_owner_sees_the_notes(self):
        c = Client()
        c.login(username="owner", password="pw")
        self.assertContains(c.get("/c/s/"), "SECRETPROSE")

    def test_the_public_does_not(self):
        self.assertNotContains(Client().get("/c/s/"), "SECRETPROSE")
