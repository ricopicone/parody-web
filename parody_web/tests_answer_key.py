"""The answer key: staff can show a section with its blanks filled; students
never receive a single answer.

The fixture pair below is shaped like real parody output (filter.lua's
`clozer`, `cloze_div` and `cloze_rewrite_math_text`), and covers every kind of
blank a book has: inline, an inline answer that is itself maths, a hidden
passage, a cloze inside display maths, a manual blank with no answer behind it,
and a rule the author typed into an equation by hand — which appears in BOTH
builds and is not a cloze at all (the system-dynamics Bode-plot section has
ten, which is why the import compares text rather than counting blanks).

The student-facing tests grep the whole response for every answer string, not
for the class name: a leak through any template path at all — the body, the
preview teaser, the meta description — fails them.
"""
import copy
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings

from parody_web import answerkey
from parody_web.models import Book, Section

ANSWERS = ["ANSWERELECTRIC", "ANSWERSQRT", "ANSWERPASSAGE", "ANSWERLEADIN"]
MATH_ANSWER = r"v(t) \cdot ANSWERPOWER"
ANSWERS_ALL = ANSWERS + ["ANSWERPOWER"]

AUTHORED_RULE = r"\underline{\hspace{1em}}"


def _student_html():
    return (
        '<h1 id="s">S</h1>'
        '<p>Voltage is the difference in '
        '<span class="cloze-blank" style="--cloze-w: 14.0em"></span> per charge.</p>'
        '<p>The frequency is '
        '<span class="cloze-blank" style="--cloze-w: 3.2em"></span>.</p>'
        '<div class="cloze-lines cloze-box" data-lines="2" '
        'style="--cloze-lines: 2"></div>'
        '<p>Power: <span class="math display">\\[P = '
        '\\underline{\\hspace{6.2em}}.\\]</span></p>'
        '<p>Write here: <span class="cloze-blank" style="--cloze-w: 5em"></span></p>'
        f'<p><span class="math display">\\[H(s) = \\frac{{{AUTHORED_RULE} s}}'
        '{s + 1}\\]</span></p>'
    )


def _key_html():
    return (
        '<h1 id="s">S</h1>'
        '<p>Voltage is the difference in '
        '<span class="cloze-key">ANSWERELECTRIC potential</span> per charge.</p>'
        '<p>The frequency is <span class="cloze-key"><span class="math inline">'
        '\\(\\sqrt{k/m}\\)</span> ANSWERSQRT</span>.</p>'
        '<div class="cloze-key-block">\n<p>ANSWERPASSAGE the whole passage.</p>\n'
        '</div>'
        f'<p>Power: <span class="math display">\\[P = '
        f'\\class{{cloze-key}}{{{MATH_ANSWER}}}.\\]</span></p>'
        '<p>Write here: <span class="cloze-blank" style="--cloze-w: 5em"></span></p>'
        f'<p><span class="math display">\\[H(s) = \\frac{{{AUTHORED_RULE} s}}'
        '{s + 1}\\]</span></p>'
    )


def _artifact(section_html, leadin_html, plain_html="<p>No blanks here.</p>"):
    return {
        "schema_version": 2, "slug": "kbook", "title": "K Book",
        "author": ["A. Author"], "source_commit": "abc123",
        "chapters": [{"title": "C", "slug": "c", "hash": "c1", "sections": [
            {"title": "Lead-in", "slug": "lead-in", "html": leadin_html},
            {"title": "S", "slug": "s", "hash": "sa", "html": section_html},
            {"title": "Plain", "slug": "plain", "hash": "pl",
             "html": plain_html},
        ]}],
    }


STUDENT = _artifact(
    _student_html(),
    '<p>Lead-in: <span class="cloze-blank" style="--cloze-w: 4em"></span>.</p>'
    '<div class="staff-only"><p>LEADINSTAFFNOTE</p></div>')
KEY = _artifact(
    _key_html(),
    '<p>Lead-in: <span class="cloze-key">ANSWERLEADIN</span>.</p>'
    '<div class="staff-only"><p>LEADINSTAFFNOTE</p></div>')


def _import(student=STUDENT, key=KEY):
    with tempfile.TemporaryDirectory() as d:
        s = Path(d, "kbook.json")
        s.write_text(json.dumps(student))
        args = [str(s), "--slug", "kbook"]
        if key is not None:
            k = Path(d, "kbook-key.json")
            k.write_text(json.dumps(key))
            args += ["--key", str(k)]
        call_command("import_artifact", *args, stdout=open("/dev/null", "w"))


class ReduceTests(TestCase):
    """The comparison the import rests on, on its own."""

    def test_the_fixture_pair_lines_up(self):
        self.assertEqual(answerkey.mismatches(STUDENT, KEY), [])

    def test_an_authored_rule_is_the_same_in_both_builds(self):
        self.assertIn(answerkey.MATH, answerkey.reduce_student(AUTHORED_RULE))
        self.assertEqual(answerkey.reduce_student(AUTHORED_RULE),
                         answerkey.reduce_key(AUTHORED_RULE))

    def test_a_nested_span_in_an_answer_is_replaced_whole(self):
        html = ('<span class="cloze-key"><span class="math inline">x</span>'
                ' y</span>!')
        self.assertEqual(answerkey.reduce_key(html), answerkey.INLINE + "!")

    def test_nested_braces_in_a_maths_answer(self):
        self.assertEqual(
            answerkey.reduce_key(r"a \class{cloze-key}{\frac{1}{\sqrt{2}}} b"),
            f"a {answerkey.MATH} b")

    def test_has_answers(self):
        self.assertTrue(answerkey.has_answers(_key_html()))
        self.assertTrue(answerkey.has_answers(r"\class{cloze-key}{x}"))
        self.assertFalse(answerkey.has_answers(_student_html()))
        self.assertFalse(answerkey.has_answers(""))


class ImportTests(TestCase):

    def test_the_key_is_stored_for_sections_with_answers_only(self):
        _import()
        self.assertIn("ANSWERELECTRIC", Section.objects.get(slug="s").key_html)
        self.assertIn("ANSWERLEADIN",
                      Section.objects.get(slug="lead-in").key_html)
        self.assertEqual(Section.objects.get(slug="plain").key_html, "")

    def test_the_student_columns_carry_no_answer(self):
        _import()
        for sec in Section.objects.all():
            for answer in ANSWERS_ALL:
                self.assertNotIn(answer, sec.html)
                self.assertNotIn(answer, sec.plain)

    def test_the_key_is_numbered_like_the_student_build(self):
        # Cross-references and heading numbers in the key must read the same
        # as on the page it is the key to.
        _import()
        sec = Section.objects.get(slug="s")
        self.assertEqual(answerkey.reduce_student(sec.html),
                         answerkey.reduce_key(sec.key_html))

    def test_an_import_without_a_key_clears_the_old_one(self):
        # A key from an earlier release must not outlive the page it fits.
        _import()
        _import(key=None)
        self.assertFalse(Section.objects.exclude(key_html="").exists())

    def _refused(self, key):
        with self.assertRaises(CommandError) as cm:
            _import(key=key)
        self.assertFalse(Book.objects.exists(),
                         "a refused key must leave nothing imported")
        return str(cm.exception)

    def test_a_section_missing_from_the_key_is_refused(self):
        key = copy.deepcopy(KEY)
        del key["chapters"][0]["sections"][2]
        self.assertIn("c/plain: missing from the key build", self._refused(key))

    def test_a_section_only_in_the_key_is_refused(self):
        key = copy.deepcopy(KEY)
        key["chapters"][0]["sections"].append(
            {"title": "X", "slug": "extra", "html": ""})
        self.assertIn("c/extra: in the key build only", self._refused(key))

    def test_a_key_whose_text_moved_on_is_refused(self):
        # The key to an older release: same sections, a sentence reworded.
        key = copy.deepcopy(KEY)
        sec = key["chapters"][0]["sections"][1]
        sec["html"] = sec["html"].replace("per charge", "per coulomb")
        self.assertIn("c/s: text differs", self._refused(key))

    def test_an_extra_blank_in_the_key_is_refused(self):
        key = copy.deepcopy(KEY)
        sec = key["chapters"][0]["sections"][2]
        sec["html"] = '<p>No <span class="cloze-key">x</span> here.</p>'
        self.assertIn("c/plain: text differs", self._refused(key))

    def test_another_books_key_is_refused(self):
        key = copy.deepcopy(KEY)
        key["slug"] = "other"
        self.assertIn("slug", self._refused(key))

    def test_another_commits_key_is_refused(self):
        key = copy.deepcopy(KEY)
        key["source_commit"] = "def456"
        self.assertIn("source_commit", self._refused(key))

    def test_an_unreadable_key_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            s = Path(d, "kbook.json")
            s.write_text(json.dumps(STUDENT))
            with self.assertRaises(CommandError):
                call_command("import_artifact", str(s), "--key",
                             str(Path(d, "nope.json")))
        self.assertFalse(Book.objects.exists())


@override_settings(BOOK_SLUG="kbook",
                   PARODY_WEB_ACCESS_POLICY=
                   "parody_web.tests_staff_only.StudentPolicy")
class ServingTests(TestCase):
    """Students: no answer, ever, by any route. Staff: all of them, on request."""

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

    def _assert_no_answer(self, response):
        body = response.content.decode()
        for needle in ANSWERS_ALL + ["cloze-key"]:
            self.assertFalse(needle in body, f"{needle!r} served")

    # --- students and the public ---

    def test_a_student_gets_blanks(self):
        for who in (None, "student"):
            with self.subTest(who=who):
                for url in ("/c/s/", "/c/"):
                    r = self._as(who).get(url)
                    self.assertEqual(r.status_code, 200)
                    self._assert_no_answer(r)
                    self.assertNotContains(r, "Show answers")

    def test_asking_for_answers_does_nothing_for_a_student(self):
        for who in (None, "student"):
            with self.subTest(who=who):
                c = self._as(who)
                for url in ("/c/s/?answers=on", "/c/?answers=on"):
                    r = c.get(url)
                    self.assertEqual(r.status_code, 200, "no redirect either")
                    self._assert_no_answer(r)
                self.assertNotIn(answerkey.SESSION_KEY, c.session)

    def test_the_session_flag_alone_does_not_open_the_key(self):
        # The flag is a preference, not a permission: a reader who is no longer
        # staff (or a session that somehow carries it) still gets blanks,
        # because the policy is asked on every request.
        c = self._as("student")
        session = c.session
        session[answerkey.SESSION_KEY] = True
        session.save()
        for url in ("/c/s/", "/c/"):
            self._assert_no_answer(c.get(url))

    def test_search_finds_no_answer(self):
        # The page echoes the query, so look for the miss rather than grep.
        # Snippets come from `plain`, which is the student build for everyone.
        for who in (None, "student", "staff"):
            with self.subTest(who=who):
                r = self._as(who).get("/search/?q=ANSWERELECTRIC")
                self.assertContains(r, "No matches")

    # --- staff ---

    def test_staff_see_blanks_and_the_offer_by_default(self):
        r = self._as("staff").get("/c/s/")
        self._assert_no_answer(r)
        self.assertContains(r, "Show answers")
        self.assertContains(r, 'href="/c/s/?answers=on"')

    def test_staff_switch_the_answers_on_and_see_every_kind(self):
        c = self._as("staff")
        r = c.get("/c/s/?answers=on")
        self.assertRedirects(r, "/c/s/", fetch_redirect_response=False)
        r = c.get("/c/s/")
        for answer in ANSWERS[:3]:
            self.assertContains(r, answer)
        # maths answers ride through as MathJax \class, which the page's
        # MathJax config loads the html extension for
        self.assertContains(r, "\\class{cloze-key}{" + MATH_ANSWER + "}")
        self.assertContains(r, 'class="cloze-key-block"')
        self.assertContains(r, "Answers shown")
        self.assertContains(r, "Hide answers")
        self.assertIn("no-store", r["Cache-Control"])

    def test_the_choice_follows_staff_from_page_to_page(self):
        c = self._as("staff")
        c.get("/c/s/?answers=on")
        self.assertContains(c.get("/c/"), "ANSWERLEADIN")

    def test_staff_switch_the_answers_off(self):
        c = self._as("staff")
        c.get("/c/s/?answers=on")
        r = c.get("/c/s/?answers=off")
        self.assertRedirects(r, "/c/s/", fetch_redirect_response=False)
        self._assert_no_answer(c.get("/c/s/"))

    def test_the_redirect_keeps_the_pages_other_parameters(self):
        r = self._as("staff").get("/c/s/?answers=on&utm=x")
        self.assertEqual(r["Location"], "/c/s/?utm=x")

    def test_a_page_without_blanks_offers_no_toggle(self):
        c = self._as("staff")
        c.get("/c/s/?answers=on")
        r = c.get("/c/plain/")
        self.assertNotContains(r, "Show answers")
        self.assertNotContains(r, "Answers shown")

    def test_no_store_only_when_the_answers_are_shown(self):
        r = self._as("staff").get("/c/s/")
        self.assertNotIn("no-store", r.get("Cache-Control", ""))


@override_settings(BOOK_SLUG="kbook",
                   PARODY_WEB_ACCESS_POLICY=
                   "parody_web.tests_staff_only.StudentPolicy")
class LeadInStaffOnlyTests(TestCase):
    """A chapter lead-in's .staff-only block reached every reader until the
    lead-in went through the same per-reader path as a section (0.99.0)."""

    def setUp(self):
        _import(key=None)
        get_user_model().objects.create_user("student", password="pw")
        get_user_model().objects.create_superuser("staff", "s@example.com", "pw")

    def test_a_student_does_not_get_the_lead_ins_staff_note(self):
        c = Client()
        c.login(username="student", password="pw")
        for client in (Client(), c):
            self.assertNotContains(client.get("/c/"), "LEADINSTAFFNOTE")

    def test_staff_do(self):
        c = Client()
        c.login(username="staff", password="pw")
        self.assertContains(c.get("/c/"), "LEADINSTAFFNOTE")
