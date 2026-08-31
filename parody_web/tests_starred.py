"""A starred problem shows a star, and nothing else changes.

`starred` arrives on the anchor and on the `problems`/`solutions` entries (see
parody's writers/artifact.py). Here it becomes a mark on the run-in problem
label and on the solution page.

The assertions worth their keep are the negative ones. `lab` — the flag this
one sits beside — is a *kind* of exercise with its own counter, so the obvious
mistake is to give `starred` one too, which would silently renumber every
problem set that adopted it. Several tests below exist only to prove nothing
new counts.

See docs/superpowers/specs/2026-08-31-starred-and-staff-only-design.md in the
parody repo.
"""
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from parody_web.numbering import number_artifact

EXERCISE_HTML = (
    '<div id="{id}"\n'
    'class="exercise numbered-environment rounded border border-green-400'
    ' shadow-md my-4 bg-white scroll-mt-20{extra}"\n'
    'data-h="{id}" data-env-type="exercise"{extraattr}>\n'
    '<section\n'
    'class="text-lg font-semibold text-green-900 px-4 py-2 border-b'
    ' border-green-400 bg-green-50 rounded-t">\n'
    '<h3 class="text-lg font-semibold text-green-900">Exercise</h3>\n'
    '</section>\n'
    '<div class="px-4 py-3 text-sm text-gray-700">\n'
    '<p>Body of {id}.</p>\n'
    '</div>\n'
    '</div>\n'
)


class StarredNumberingTests(TestCase):
    def test_a_starred_problem_keeps_its_place_in_the_sequence(self):
        # The one that matters. `lab` runs a counter of its own; `starred` must
        # not, or adopting it renumbers the whole problem set.
        data = {"chapters": [{"title": "C", "slug": "c", "hash": "c1",
            "sections": [{"title": "S", "slug": "s", "anchors": [
                {"id": "p1", "type": "exercise", "hash": "p1"},
                {"id": "p2", "type": "exercise", "hash": "p2", "starred": True},
                {"id": "p3", "type": "exercise", "hash": "p3"},
            ], "html": ""}]}]}
        targets = number_artifact(data)
        self.assertEqual(targets["p1"]["label"], "Problem 1.1")
        self.assertEqual(targets["p2"]["label"], "Problem 1.2")
        self.assertEqual(targets["p3"]["label"], "Problem 1.3")

    def test_a_cross_reference_carries_no_star(self):
        # A star describes the problem; it is not part of its name. "See
        # Problem 1.1", never "See Problem 1.1 ★".
        data = {"chapters": [{"title": "C", "slug": "c", "hash": "c1",
            "sections": [{"title": "S", "slug": "s", "anchors": [
                {"id": "p1", "type": "exercise", "hash": "p1", "starred": True},
            ], "html": ""}]}]}
        targets = number_artifact(data)
        self.assertEqual(targets["p1"]["label"], "Problem 1.1")

    def test_starred_composes_with_lab(self):
        data = {"chapters": [{"title": "C", "slug": "c", "hash": "c1",
            "sections": [{"title": "S", "slug": "s", "anchors": [
                {"id": "l1", "type": "exercise", "hash": "l1", "lab": True,
                 "starred": True},
                {"id": "l2", "type": "exercise", "hash": "l2", "lab": True},
            ], "html": ""}]}]}
        targets = number_artifact(data)
        # still on the lab counter, still L-prefixed, still second is L1.2
        self.assertEqual(targets["l1"]["label"], "Lab problem L1.1")
        self.assertEqual(targets["l2"]["label"], "Lab problem L1.2")


class StarredBoxTests(TestCase):
    def _rendered(self, anchors, html):
        data = {"chapters": [{"title": "C", "slug": "c", "hash": "c1",
            "sections": [{"title": "S", "slug": "s", "anchors": anchors,
                          "html": html}]}]}
        number_artifact(data)
        return data["chapters"][0]["sections"][0]["html"]

    def test_the_box_carries_the_class_and_the_mark(self):
        out = self._rendered(
            [{"id": "p1", "type": "exercise", "hash": "p1", "starred": True}],
            EXERCISE_HTML.format(id="p1", extra="", extraattr=""))
        self.assertIn('class="exercise starred"', out)
        self.assertIn('class="problem-star"', out)
        self.assertIn('<div class="problem-label">Problem 1.1', out)

    def test_an_ordinary_problem_gets_neither(self):
        out = self._rendered(
            [{"id": "p1", "type": "exercise", "hash": "p1"}],
            EXERCISE_HTML.format(id="p1", extra="", extraattr=""))
        self.assertIn('class="exercise"', out)
        self.assertNotIn("starred", out)
        self.assertNotIn("problem-star", out)

    def test_a_starred_lab_problem_carries_both_classes(self):
        out = self._rendered(
            [{"id": "l1", "type": "exercise", "hash": "l1", "lab": True,
              "starred": True}],
            EXERCISE_HTML.format(id="l1", extra=" lab",
                                 extraattr=' data-lab="1"'))
        self.assertIn('class="exercise lab starred"', out)
        self.assertIn('<div class="problem-label">Problem L1.1', out)


def _import(artifact, slug="sbook"):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, "a.json")
        p.write_text(json.dumps(artifact))
        call_command("import_artifact", str(p), "--slug", slug)


@override_settings(BOOK_SLUG="sbook")
class StarredSolutionPageTests(TestCase):
    """The solution page shows the same mark the section page does."""

    def setUp(self):
        _import({
            "schema_version": 2, "slug": "sbook", "title": "S Book",
            "author": ["A. Author"],
            "chapters": [{"title": "C", "slug": "c", "hash": "c1",
                "sections": [{"title": "S", "slug": "s", "hash": "sa",
                    "html": "<p>Prose.</p>",
                    "anchors": [
                        {"id": "p1", "type": "exercise", "hash": "p1",
                         "starred": True},
                        {"id": "p2", "type": "exercise", "hash": "p2"},
                    ],
                    "solutions": {
                        "p1": {"content": "<p>Starred answer.</p>",
                               "title": "Screw axis", "starred": True},
                        "p2": {"content": "<p>Plain answer.</p>",
                               "title": "Twist", "starred": False},
                    }}]}]})
        # DefaultPolicy gates solutions to the owner: any authenticated user.
        from django.contrib.auth import get_user_model
        get_user_model().objects.create_user("owner", password="pw")
        self.client = Client()
        self.client.login(username="owner", password="pw")

    def test_the_starred_solution_page_shows_the_mark(self):
        r = self.client.get("/c/s/solutions/p1/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "problem-star")

    def test_the_plain_solution_page_does_not(self):
        r = self.client.get("/c/s/solutions/p2/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "problem-star")
