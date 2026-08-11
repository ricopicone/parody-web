# parody-web Host-Integration Seams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give parody-web four documented seams — imported solutions/problems, a pluggable access policy, per-user overlay include points, and a stable section join key — so a course site can serve books from parody-web without parody-web learning anything about enrollment or due dates.

**Architecture:** A new `parody_web/access.py` holds a `DefaultPolicy` whose methods reproduce today's inline gating verbatim; `views.py` is rewritten to call the policy instead of inlining the rules, and `PARODY_WEB_ACCESS_POLICY` names a replacement class by dotted path (validated at boot in `apps.py`, mirroring `PARODY_WEB_THEME`). `Section` gains solutions/problems JSON fields plus a `key` property, and `section.html` gains four empty include partials a host can shadow.

**Tech Stack:** Django 5 app (`parody_web`), sqlite for tests, `python runtests.py` as the suite runner, `uv` for the lockfile.

## Global Constraints

- Everything is **additive**: with neither `PARODY_WEB_ACCESS_POLICY` nor any host template override configured, every existing behaviour and every existing test must be unchanged.
- Policy hooks take `request`, never `user`. `request` may be `None` (some helpers are called without one); every default hook must tolerate `request=None`.
- Exercise ids contain colons (`exe:z3-agent`), so URL patterns use `<str:>`, never `<slug:>`.
- Release is parody-web **0.34.0**; `uv.lock` is committed in the same commit as the `pyproject.toml` version bump (the lock pins the project's own version).
- The suite is run with `python runtests.py` from the repo root. It must be green at the end of every task.
- Never `git add -A` — this repo is shared with concurrent sessions. Every commit lists its files explicitly.
- Cross-reference and citation resolution inside solution/problem content is **out of scope** (it lives in `number_artifact`'s per-section second pass, shared with rtcbook rendering). It is documented as a known limitation in Task 7.

## File Structure

| File | Responsibility |
|---|---|
| `parody_web/access.py` | **new** — `DefaultPolicy` + `get_policy()` + `validate_policy()` |
| `parody_web/models.py` | **modify** — `Section` solutions/problems fields, `solution_for`/`problem_for`, `key` property, `hash` index |
| `parody_web/migrations/0009_section_solutions.py` | **new** — the schema change |
| `parody_web/management/commands/import_artifact.py` | **modify** — carry the three artifact keys onto `Section` |
| `parody_web/apps.py` | **modify** — validate the policy setting at boot |
| `parody_web/views.py` | **modify** — route all gating through the policy; add `solution_detail` |
| `parody_web/urls.py` | **modify** — the solution route |
| `parody_web/templates/parody_web/solution.html` | **new** — the granted solution page |
| `parody_web/templates/parody_web/solution_denied.html` | **new** — the denial page |
| `parody_web/templates/parody_web/_section_head.html` | **new** — empty overlay include |
| `parody_web/templates/parody_web/_section_toolbar.html` | **new** — empty overlay include |
| `parody_web/templates/parody_web/_section_foot.html` | **new** — empty overlay include |
| `parody_web/templates/parody_web/_section_overlay.html` | **new** — empty overlay include |
| `parody_web/templates/parody_web/section.html` | **modify** — the four includes |
| `parody_web/tests.py` | **modify** — tests for every task |
| `docs/host-integration.md` | **new** — the host-facing contract |
| `pyproject.toml`, `uv.lock` | **modify** — 0.34.0 |

---

### Task 1: Section solutions/problems fields and the join key

**Files:**
- Modify: `parody_web/models.py:75-98` (the `Section` model)
- Create: `parody_web/migrations/0009_section_solutions.py`
- Test: `parody_web/tests.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Section.has_solutions: bool`, `Section.solutions: dict`, `Section.problems: dict`, `Section.solution_for(exercise_id) -> dict | None`, `Section.problem_for(exercise_id) -> dict | None`, `Section.key -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `parody_web/tests.py`:

```python
class SectionSolutionFieldsTests(TestCase):
    """Section carries the artifact's per-exercise solutions/problems and
    offers one stable identity for host-side records to key on."""

    def setUp(self):
        _import()
        self.section = Section.objects.get(slug="specific-t1")

    def test_solutions_default_empty(self):
        self.assertFalse(self.section.has_solutions)
        self.assertEqual(self.section.solutions, {})
        self.assertEqual(self.section.problems, {})

    def test_solution_for_returns_entry_or_none(self):
        self.section.solutions = {"exe:a": {"title": "A", "content": "<p>x</p>"}}
        self.assertEqual(self.section.solution_for("exe:a")["title"], "A")
        self.assertIsNone(self.section.solution_for("exe:missing"))

    def test_problem_for_returns_entry_or_none(self):
        self.section.problems = {"exe:a": {"title": "A", "content": "<p>p</p>"}}
        self.assertEqual(self.section.problem_for("exe:a")["content"], "<p>p</p>")
        self.assertIsNone(self.section.problem_for("exe:missing"))

    def test_key_prefers_authored_hash(self):
        # ARTIFACT authors hash "ef" for this section
        self.assertEqual(self.section.key, "ef")

    def test_key_falls_back_to_slug_pair(self):
        # Course books (e.g. the EAI golden artifact) author no hashes at all,
        # so hash alone would key every section to "".
        self.section.hash = ""
        self.assertEqual(self.section.key, "hardware/specific-t1")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python runtests.py 2>&1 | tail -20`
Expected: FAIL — `AttributeError: 'Section' object has no attribute 'has_solutions'`.

- [ ] **Step 3: Add the fields, accessors, and key property**

In `parody_web/models.py`, inside `Section`, after the `anchors` field:

```python
    # Per-exercise solutions/problems from the artifact, {exercise_id: {"title",
    # "content"}}. Commercial/partial artifacts carry none and import as {};
    # course books carry both. Storing them is not exposing them — the access
    # policy decides who may read a solution (see parody_web/access.py).
    has_solutions = models.BooleanField(default=False)
    solutions = models.JSONField(default=dict, blank=True)
    problems = models.JSONField(default=dict, blank=True)
```

Change the `hash` field to carry an index:

```python
    hash = models.CharField(max_length=100, blank=True, default="", db_index=True)
```

And after `Meta`:

```python
    def solution_for(self, exercise_id):
        """The stored solution entry for one exercise, or None."""
        return (self.solutions or {}).get(exercise_id)

    def problem_for(self, exercise_id):
        """The stored problem statement for one exercise, or None."""
        return (self.problems or {}).get(exercise_id)

    @property
    def key(self):
        """The stable identity a host keys its own per-section records to.

        The authored short hash when there is one — it survives renames and
        reorganization, and parody build-checks it for uniqueness within a book.
        parody only emits a hash when the source authors one in front matter, and
        course books generally do not, so fall back to the (always present)
        chapter/section slug pair rather than keying everything to "".
        """
        return self.hash or f"{self.chapter.slug}/{self.slug}"
```

- [ ] **Step 4: Generate the migration**

Run: `python -c "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','tests.settings'); django.setup(); from django.core.management import call_command; call_command('makemigrations','parody_web','-n','section_solutions')"`
Expected: creates `parody_web/migrations/0009_section_solutions.py` adding three fields and altering `hash`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python runtests.py 2>&1 | tail -5`
Expected: OK, with the whole pre-existing suite still green.

- [ ] **Step 6: Commit**

```bash
git add parody_web/models.py parody_web/migrations/0009_section_solutions.py parody_web/tests.py
git commit -m "models: carry per-exercise solutions/problems and a stable section key (task #549)"
```

---

### Task 2: Import solutions and problems

**Files:**
- Modify: `parody_web/management/commands/import_artifact.py:157-172`
- Test: `parody_web/tests.py`

**Interfaces:**
- Consumes: `Section.has_solutions`, `Section.solutions`, `Section.problems` from Task 1.
- Produces: an importer that populates them from the artifact's per-section `has_solutions`, `solutions`, `problems` keys.

- [ ] **Step 1: Write the failing test**

Append to `parody_web/tests.py`:

```python
SOLUTIONS_ARTIFACT = {
    "schema_version": 2,
    "slug": "course-book",
    "title": "Course Book",
    "chapters": [{
        "title": "Agents", "slug": "agents",
        "sections": [
            {"title": "Problems", "slug": "problems",
             "html": '<div id="exe:reflex" class="exercise">Do the thing.</div>',
             "has_solutions": True,
             "solutions": {"exe:reflex": {"title": "Simple Reflex Agent",
                                          "content": "<p>SOLUTIONBODY</p>"}},
             "problems": {"exe:reflex": {"title": "Simple Reflex Agent",
                                         "content": "<p>PROBLEMBODY</p>"}}},
            {"title": "Prose", "slug": "prose", "html": "<p>Words.</p>"},
        ],
    }],
}


def _import_solutions(slug="course-book"):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, "a.json")
        p.write_text(json.dumps(SOLUTIONS_ARTIFACT))
        call_command("import_artifact", str(p), "--slug", slug)


class SolutionImportTests(TestCase):
    def test_solutions_and_problems_land_on_section(self):
        _import_solutions()
        sec = Section.objects.get(book__slug="course-book", slug="problems")
        self.assertTrue(sec.has_solutions)
        self.assertEqual(sec.solution_for("exe:reflex")["content"],
                         "<p>SOLUTIONBODY</p>")
        self.assertEqual(sec.problem_for("exe:reflex")["title"],
                         "Simple Reflex Agent")

    def test_section_without_solutions_imports_empty(self):
        _import_solutions()
        sec = Section.objects.get(book__slug="course-book", slug="prose")
        self.assertFalse(sec.has_solutions)
        self.assertEqual(sec.solutions, {})
        self.assertEqual(sec.problems, {})

    def test_artifact_without_solutions_still_imports(self):
        # every commercial/partial artifact today
        _import()
        self.assertFalse(Section.objects.get(slug="specific-t1").has_solutions)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python runtests.py 2>&1 | tail -20`
Expected: FAIL — `test_solutions_and_problems_land_on_section` asserts `True` but `has_solutions` is `False` (the importer never reads the key).

- [ ] **Step 3: Read the keys in the importer**

In `parody_web/management/commands/import_artifact.py`, inside the
`Section.objects.update_or_create(...)` `defaults` dict, after `"anchors"`:

```python
                        "anchors": sec.get("anchors", []),
                        # Per-exercise solutions/problems ride through untouched;
                        # who may read them is the access policy's call, not the
                        # importer's.
                        "has_solutions": bool(sec.get("has_solutions", False)),
                        "solutions": sec.get("solutions") or {},
                        "problems": sec.get("problems") or {},
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python runtests.py 2>&1 | tail -5`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add parody_web/management/commands/import_artifact.py parody_web/tests.py
git commit -m "import: carry per-section solutions and problems through (task #549)"
```

---

### Task 3: The access policy module

**Files:**
- Create: `parody_web/access.py`
- Modify: `parody_web/apps.py`
- Test: `parody_web/tests.py`

**Interfaces:**
- Consumes: `Section` from Task 1.
- Produces: `parody_web.access.DefaultPolicy` (methods `is_owner(request)`, `can_view_section(request, section)`, `section_is_preview(request, section)`, `can_view_solution(request, section, exercise_id)`, `solution_denied_context(request, section, exercise_id)`), plus `get_policy()` and `validate_policy(path)`.

- [ ] **Step 1: Write the failing tests**

Append to `parody_web/tests.py`:

```python
class AccessPolicyTests(TestCase):
    """The default policy reproduces the gating that used to be inlined in
    views.py; a host swaps in its own class by dotted path."""

    def setUp(self):
        _import()
        self.user = get_user_model().objects.create_user("u", "u@e.com", "pw")
        self.factory = RequestFactory()

    def _request(self, authed):
        r = self.factory.get("/")
        r.user = self.user if authed else AnonymousUser()
        return r

    def test_default_owner_is_authenticated(self):
        policy = DefaultPolicy()
        self.assertTrue(policy.is_owner(self._request(True)))
        self.assertFalse(policy.is_owner(self._request(False)))

    def test_default_owner_tolerates_no_request(self):
        self.assertFalse(DefaultPolicy().is_owner(None))

    def test_default_can_view_section_is_open(self):
        section = Section.objects.get(slug="licensed")
        self.assertTrue(DefaultPolicy().can_view_section(
            self._request(False), section))

    def test_default_preview_gates_anonymous_only(self):
        policy = DefaultPolicy()
        licensed = Section.objects.get(slug="licensed")   # preview=True
        public = Section.objects.get(slug="specific-t1")  # preview=False
        self.assertTrue(policy.section_is_preview(self._request(False), licensed))
        self.assertFalse(policy.section_is_preview(self._request(True), licensed))
        self.assertFalse(policy.section_is_preview(self._request(False), public))

    def test_default_solution_is_owner_only(self):
        policy = DefaultPolicy()
        section = Section.objects.get(slug="specific-t1")
        self.assertTrue(policy.can_view_solution(
            self._request(True), section, "exe:a"))
        self.assertFalse(policy.can_view_solution(
            self._request(False), section, "exe:a"))

    def test_default_denied_context_shape(self):
        section = Section.objects.get(slug="specific-t1")
        ctx = DefaultPolicy().solution_denied_context(
            self._request(False), section, "exe:a")
        self.assertIsNone(ctx["available_after"])
        self.assertIn("message", ctx)

    def test_get_policy_returns_default_when_unset(self):
        self.assertIsInstance(get_policy(), DefaultPolicy)

    @override_settings(PARODY_WEB_ACCESS_POLICY="parody_web.tests.OpenPolicy")
    def test_get_policy_loads_configured_class(self):
        self.assertIsInstance(get_policy(), OpenPolicy)

    def test_validate_policy_rejects_bad_path(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_policy("nope.NotAPolicy")

    def test_validate_policy_rejects_non_class(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_policy("parody_web.access.get_policy")

    def test_validate_policy_accepts_default(self):
        validate_policy("parody_web.access.DefaultPolicy")  # no raise
```

Also add, at module level in `tests.py` (a policy the tests point settings at):

```python
class OpenPolicy(DefaultPolicy):
    """Test double: everyone may read every solution."""

    def can_view_solution(self, request, section, exercise_id):
        return True


class DueDatePolicy(DefaultPolicy):
    """Test double for the course case: solutions are refused, and the denial
    page is told when they open."""

    def can_view_solution(self, request, section, exercise_id):
        return False

    def solution_denied_context(self, request, section, exercise_id):
        return {"available_after": "2026-09-01",
                "message": "Solutions open after the assignment is due."}
```

And extend the imports at the top of `tests.py`:

```python
from django.contrib.auth.models import AnonymousUser
from django.test import Client, RequestFactory, TestCase, override_settings

from parody_web.access import DefaultPolicy, get_policy, validate_policy
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python runtests.py 2>&1 | tail -20`
Expected: FAIL — `ModuleNotFoundError: No module named 'parody_web.access'`.

- [ ] **Step 3: Write `parody_web/access.py`**

```python
"""Pluggable access control.

parody-web's own gating is commercial publishing: an owner (the authenticated
account) sees everything, the public sees full sections and a teaser for the
in-print ones. A host project serving the same book to a class needs a
different question answered — "may *this* student see the solution to *this*
exercise *yet*" — which depends on enrollment, assignments, and due dates that
parody-web has no business knowing about.

So the rules live behind one object, and a deployment names a replacement:

    PARODY_WEB_ACCESS_POLICY = "courses.policy.CoursePolicy"

Subclass `DefaultPolicy` and override only the hooks you care about; anything
you leave alone keeps parody-web's own behaviour. The setting is validated at
startup (see apps.py) so a typo'd path fails on boot, not at first render.

Every hook takes the *request*, not the user: `request.user` is always
reachable from a request and the reverse is not. `request` may be None in
helper paths that have none, so every hook tolerates it.
"""

from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


class DefaultPolicy:
    """parody-web's own rules — the behaviour that used to be inlined in views."""

    def is_owner(self, request):
        """The book's owner: the only account a public book site has."""
        return bool(request and request.user.is_authenticated)

    def can_view_section(self, request, section):
        """Hard gate: may this reader have the section page at all?

        parody-web never refuses one — the table of contents and the prose are
        public, and restricted sections are *teased* rather than hidden (see
        `section_is_preview`). A host with genuinely restricted material (a
        notebook only enrolled students may open) overrides this.
        """
        return True

    def section_is_preview(self, request, section):
        """Soft gate: show a truncated excerpt and a sign-in call to action.

        This is `Section.preview` — in print, not fully online.
        """
        return bool(section.preview) and not self.is_owner(request)

    def can_view_solution(self, request, section, exercise_id):
        """May this reader read the worked solution to one exercise?"""
        return self.is_owner(request)

    def solution_denied_context(self, request, section, exercise_id):
        """Extra template context for the refusal page.

        `available_after` is what a course site fills in with the assignment's
        due date so the page can say when the solution opens; None means "no
        date to offer", which is all parody-web itself can say.
        """
        return {
            "available_after": None,
            "message": "Solutions are available to the book's owner.",
        }


def validate_policy(path):
    """Raise ImproperlyConfigured unless `path` names an importable class."""
    if not path:
        return
    if not isinstance(path, str):
        raise ImproperlyConfigured(
            f"PARODY_WEB_ACCESS_POLICY must be a dotted path string, "
            f"got {type(path).__name__}")
    try:
        policy = import_string(path)
    except ImportError as e:
        raise ImproperlyConfigured(
            f"PARODY_WEB_ACCESS_POLICY: could not import {path!r}: {e}")
    if not isinstance(policy, type):
        raise ImproperlyConfigured(
            f"PARODY_WEB_ACCESS_POLICY: {path!r} is not a class")


def get_policy():
    """The configured access policy instance (DefaultPolicy when unset).

    Resolved per call rather than cached at import: override_settings must take
    effect in tests, and a policy instance is cheap.
    """
    from django.conf import settings

    path = getattr(settings, "PARODY_WEB_ACCESS_POLICY", "")
    if not path:
        return DefaultPolicy()
    validate_policy(path)
    return import_string(path)()
```

- [ ] **Step 4: Validate the setting at boot**

Replace the body of `ready()` in `parody_web/apps.py`:

```python
    def ready(self):
        # Fail on a malformed PARODY_WEB_THEME or PARODY_WEB_ACCESS_POLICY at
        # startup rather than silently dropping it at first render.
        from django.conf import settings

        from .access import validate_policy
        from .theme import validate_theme
        validate_theme(getattr(settings, "PARODY_WEB_THEME", None))
        validate_policy(getattr(settings, "PARODY_WEB_ACCESS_POLICY", ""))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python runtests.py 2>&1 | tail -5`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add parody_web/access.py parody_web/apps.py parody_web/tests.py
git commit -m "access: pluggable policy object behind PARODY_WEB_ACCESS_POLICY (task #549)"
```

---

### Task 4: Route views through the policy

**Files:**
- Modify: `parody_web/views.py:50-51` (`_is_owner`), `:159-172` (`index`), `:258-284` (`search`), `:287-320` (`chapter_detail`), `:323-348` (`section_detail`)
- Test: `parody_web/tests.py`

**Interfaces:**
- Consumes: `get_policy()` and `DefaultPolicy` from Task 3.
- Produces: `views.py` with no inline gating — `_is_owner(request)` delegates to the policy, and every `public` / `preview` computation calls `section_is_preview` or `is_owner`.

- [ ] **Step 1: Write the failing test**

Append to `parody_web/tests.py`:

```python
class ClosedSectionPolicy(DefaultPolicy):
    """Test double: the licensed section is teased even from the owner, proving
    the view asks the policy rather than checking section.preview itself."""

    def section_is_preview(self, request, section):
        return section.slug == "licensed"


@override_settings(PARODY_WEB_ACCESS_POLICY="parody_web.tests.ClosedSectionPolicy")
class PolicyDrivenViewTests(TestCase):
    def setUp(self):
        _import()
        self.owner = get_user_model().objects.create_superuser(
            "owner2", "owner2@example.com", "pw")
        self.signed_in = Client()
        self.signed_in.force_login(self.owner)

    def test_section_view_honours_policy_over_preview_flag(self):
        # The owner would see full text under the default policy; this policy
        # says preview, so the view must show the teaser instead.
        r = self.signed_in.get("/hardware/licensed/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "This is a preview")
        self.assertNotContains(r, "Copyrighted prose")

    def test_chapter_view_honours_policy(self):
        r = self.signed_in.get("/hardware/")
        self.assertEqual(r.status_code, 200)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python runtests.py PolicyDrivenViewTests 2>&1 | tail -20`

(If that argument form is unsupported, run `python runtests.py 2>&1 | tail -30`.)
Expected: FAIL — `test_section_view_honours_policy_over_preview_flag` finds "Copyrighted prose", because `section_detail` still computes `section.preview and not request.user.is_authenticated` itself.

- [ ] **Step 3: Delegate to the policy in views.py**

Add the import near the top of `parody_web/views.py`:

```python
from .access import get_policy
```

Replace `_is_owner`:

```python
def _is_owner(request):
    """Whether this request is the book's owner — the access policy's call
    (PARODY_WEB_ACCESS_POLICY), so a host can redefine it."""
    return bool(get_policy().is_owner(request))
```

In `index`, replace `public = not request.user.is_authenticated` with:

```python
    public = not _is_owner(request)
```

In `search`, replace `"public": not request.user.is_authenticated,` with:

```python
        "public": not _is_owner(request),
```

In `chapter_detail`, replace `public = not request.user.is_authenticated` with:

```python
    public = not _is_owner(request)
```

and replace `preview = bool(leadin and leadin.preview and public)` with:

```python
    policy = get_policy()
    # A preview lead-in teases the public exactly like a preview section.
    preview = bool(leadin and policy.section_is_preview(request, leadin))
```

(delete the now-duplicated comment line above the old expression.)

In `section_detail`, replace the `preview = ...` line and its comment with:

```python
    policy = get_policy()
    if not policy.can_view_section(request, section):
        raise Http404("section not available")
    # Sections the policy calls preview (in-print but not fully online) show a
    # teaser + sign-in to the reader; everything else is full.
    preview = policy.section_is_preview(request, section)
```

- [ ] **Step 4: Run the whole suite to verify it passes**

Run: `python runtests.py 2>&1 | tail -5`
Expected: OK — the new test passes and every pre-existing gating test still passes, proving `DefaultPolicy` is behaviour-preserving.

- [ ] **Step 5: Commit**

```bash
git add parody_web/views.py parody_web/tests.py
git commit -m "views: route every gating decision through the access policy (task #549)"
```

---

### Task 5: The solution page

**Files:**
- Modify: `parody_web/views.py` (add `solution_detail`), `parody_web/urls.py:26`
- Create: `parody_web/templates/parody_web/solution.html`, `parody_web/templates/parody_web/solution_denied.html`
- Test: `parody_web/tests.py`

**Interfaces:**
- Consumes: `Section.solution_for` (Task 1), `get_policy()` (Task 3), the test doubles `OpenPolicy` and `DueDatePolicy` (Task 3), `_import_solutions()` (Task 2).
- Produces: URL name `parody_web:solution` taking `(chapter_slug, section_slug, exercise_id)`.

- [ ] **Step 1: Write the failing tests**

Append to `parody_web/tests.py`:

```python
class SolutionViewTests(TestCase):
    def setUp(self):
        _import_solutions()
        self.owner = get_user_model().objects.create_superuser(
            "owner3", "owner3@example.com", "pw")
        self.anon = Client()
        self.signed_in = Client()
        self.signed_in.force_login(self.owner)

    URL = "/agents/problems/solutions/exe:reflex/"

    def test_owner_reads_solution(self):
        r = self.signed_in.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SOLUTIONBODY")
        self.assertContains(r, "Simple Reflex Agent")

    def test_anonymous_is_denied_with_context(self):
        r = self.anon.get(self.URL)
        self.assertEqual(r.status_code, 403)
        self.assertNotContains(r, "SOLUTIONBODY", status_code=403)

    def test_unknown_exercise_404s(self):
        r = self.signed_in.get("/agents/problems/solutions/exe:nope/")
        self.assertEqual(r.status_code, 404)

    def test_section_without_solutions_404s(self):
        r = self.signed_in.get("/agents/prose/solutions/exe:reflex/")
        self.assertEqual(r.status_code, 404)

    def test_solution_urls_stay_out_of_the_sitemap(self):
        body = self.anon.get("/sitemap.xml").content.decode()
        self.assertNotIn("/solutions/", body)

    @override_settings(PARODY_WEB_ACCESS_POLICY="parody_web.tests.OpenPolicy")
    def test_host_policy_can_open_a_solution(self):
        r = self.anon.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SOLUTIONBODY")

    @override_settings(PARODY_WEB_ACCESS_POLICY="parody_web.tests.DueDatePolicy")
    def test_denial_page_shows_host_supplied_date(self):
        r = self.signed_in.get(self.URL)
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "2026-09-01", status_code=403)
        self.assertContains(r, "Solutions open after", status_code=403)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python runtests.py 2>&1 | tail -20`
Expected: FAIL — the URL 404s (no route), so `test_owner_reads_solution` gets 404 instead of 200.

- [ ] **Step 3: Add the view**

In `parody_web/views.py`, after `section_detail`:

```python
def solution_detail(request, chapter_slug, section_slug, exercise_id):
    """One exercise's worked solution, gated by the access policy.

    parody-web's own answer is "the owner, and nobody else"; a course site
    points PARODY_WEB_ACCESS_POLICY at a class that knows about enrollment and
    due dates. A refusal still renders a page (403) so the host can say when the
    solution opens — see DefaultPolicy.solution_denied_context.
    """
    book, editions = _resolve_book(request)
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    entry = section.solution_for(exercise_id)
    if not entry:
        raise Http404(f"no solution for {exercise_id!r}")

    policy = get_policy()
    base = {"book": book, "editions": editions, "section": section,
            "chapter": section.chapter, "exercise_id": exercise_id,
            "exercise_title": entry.get("title") or "Exercise",
            "canonical_url": request.build_absolute_uri(request.path)}
    if not policy.can_view_solution(request, section, exercise_id):
        ctx = dict(base)
        ctx.update(policy.solution_denied_context(request, section, exercise_id))
        return render(request, "parody_web/solution_denied.html", ctx,
                      status=403)
    return render(request, "parody_web/solution.html",
                  dict(base, solution_html=entry.get("content") or ""))
```

- [ ] **Step 4: Add the route**

In `parody_web/urls.py`, immediately before the `<slug:chapter_slug>/<slug:section_slug>/` pattern:

```python
    # One exercise's worked solution, gated by the access policy. <str:> not
    # <slug:> because exercise ids carry a colon ("exe:z3-agent"). Listed before
    # the bare section pattern so the reserved "solutions" segment reads first.
    path("<slug:chapter_slug>/<slug:section_slug>/solutions/<str:exercise_id>/",
         views.solution_detail, name="solution"),
```

- [ ] **Step 5: Add the two templates**

`parody_web/templates/parody_web/solution.html`:

```html
{% extends "parody_web/base.html" %}
{% load parody_web %}
{% block title %}Solution — {{ exercise_title|cut:"`" }} — {{ book.title }}{% endblock %}
{% block head_extra %}<meta name="robots" content="noindex">{% endblock %}
{% block body %}
<nav class="crumbs has-chapter"><a href="{% index_url book %}">{{ book.title }}</a><span class="crumb-sep">›</span><a class="crumb-trunc" href="{% chapter_url book chapter.slug %}" title="{{ chapter.title|cut:'`' }}">{{ chapter.title|code_spans }}</a><span class="crumb-sep">›</span><a class="crumb-trunc" href="{% section_url book chapter.slug section.slug %}">{{ section.title|code_spans }}</a></nav>

<h1>Solution: {{ exercise_title|code_spans }}</h1>

{{ solution_html|render_book }}

<nav class="pager">
  <a href="{% section_url book chapter.slug section.slug %}">← {{ section.title|code_spans }}</a>
  <span></span>
</nav>
{% endblock %}
```

`parody_web/templates/parody_web/solution_denied.html`:

```html
{% extends "parody_web/base.html" %}
{% load parody_web %}
{% block title %}Solution — {{ exercise_title|cut:"`" }} — {{ book.title }}{% endblock %}
{% block head_extra %}<meta name="robots" content="noindex">{% endblock %}
{% block body %}
<nav class="crumbs has-chapter"><a href="{% index_url book %}">{{ book.title }}</a><span class="crumb-sep">›</span><a class="crumb-trunc" href="{% chapter_url book chapter.slug %}" title="{{ chapter.title|cut:'`' }}">{{ chapter.title|code_spans }}</a><span class="crumb-sep">›</span><a class="crumb-trunc" href="{% section_url book chapter.slug section.slug %}">{{ section.title|code_spans }}</a></nav>

<h1>Solution: {{ exercise_title|code_spans }}</h1>

<div class="signin-gate">
  <p><strong>Not available yet.</strong> {{ message }}</p>
  {% if available_after %}<p>Available after {{ available_after }}.</p>{% endif %}
  <p class="note"><a href="{% section_url book chapter.slug section.slug %}">Back to {{ section.title|code_spans }}</a></p>
</div>
{% endblock %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python runtests.py 2>&1 | tail -5`
Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add parody_web/views.py parody_web/urls.py parody_web/templates/parody_web/solution.html parody_web/templates/parody_web/solution_denied.html parody_web/tests.py
git commit -m "views: policy-gated per-exercise solution page (task #549)"
```

---

### Task 6: Overlay include points

**Files:**
- Create: `parody_web/templates/parody_web/_section_head.html`, `_section_toolbar.html`, `_section_foot.html`, `_section_overlay.html`
- Modify: `parody_web/templates/parody_web/section.html`
- Test: `parody_web/tests.py`

**Interfaces:**
- Consumes: the `section_detail` context (Task 4).
- Produces: four overridable template names under `parody_web/`.

- [ ] **Step 1: Write the failing test**

Append to `parody_web/tests.py`:

```python
class OverlayIncludeTests(TestCase):
    """A host injects per-user features (annotations, data tables, an exam entry
    point) by shadowing small empty partials — never by copying section.html."""

    def setUp(self):
        _import()

    def test_empty_partials_render_nothing_by_default(self):
        r = self.client.get("/hardware/specific-t1/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "HOSTOVERLAY")

    def test_host_override_is_injected(self):
        with tempfile.TemporaryDirectory() as d:
            pw = Path(d, "parody_web")
            pw.mkdir()
            (pw / "_section_overlay.html").write_text(
                '<div id="HOSTOVERLAY" data-key="{{ section.key }}"></div>')
            (pw / "_section_toolbar.html").write_text("<p>HOSTTOOLBAR</p>")
            templates = [dict(settings.TEMPLATES[0])]
            templates[0]["DIRS"] = [d]
            with override_settings(TEMPLATES=templates):
                from django.template import engines
                engines._engines = {}
                r = self.client.get("/hardware/specific-t1/")
                html = r.content.decode()
            engines._engines = {}
        self.assertIn('id="HOSTOVERLAY"', html)
        self.assertIn('data-key="ef"', html)   # Section.key, the join key
        self.assertIn("HOSTTOOLBAR", html)
```

Add to the `tests.py` imports:

```python
from django.conf import settings
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python runtests.py 2>&1 | tail -20`
Expected: FAIL — `test_host_override_is_injected` finds no `id="HOSTOVERLAY"`, because `section.html` includes nothing.

- [ ] **Step 3: Create the four empty partials**

Each file contains only a comment, so a default deployment renders nothing.

`_section_head.html`:

```html
{# Host injection point: extra <head> content for a section page (overlay CSS
   and scripts). Ships empty; a host project shadows this template. #}
```

`_section_toolbar.html`:

```html
{# Host injection point: a per-section toolbar, rendered under the heading —
   e.g. an exam/print entry point. Ships empty; a host project shadows this
   template. Context: book, chapter, section, preview, editions. #}
```

`_section_foot.html`:

```html
{# Host injection point: content after the section body and before the pager —
   e.g. editable per-user data tables. Ships empty; a host project shadows this
   template. Context: book, chapter, section, preview, editions. #}
```

`_section_overlay.html`:

```html
{# Host injection point: the end of the section page — e.g. an annotation or
   drawing layer and the scripts that drive it. Ships empty; a host project
   shadows this template. Key host-side records to section.key. #}
```

- [ ] **Step 4: Wire them into section.html**

In `parody_web/templates/parody_web/section.html`:

Add to the end of the `head_extra` block, before `{% endblock %}`:

```html
{% include "parody_web/_section_head.html" %}
```

After the `{% if not title_in_html %}<h1>…</h1>{% endif %}` line:

```html
{% include "parody_web/_section_toolbar.html" %}
```

After the closing `{% endif %}` of the preview/full branch and before `<nav class="pager">`:

```html
{% include "parody_web/_section_foot.html" %}
```

After the `</nav>` closing the pager, before `{% endblock %}`:

```html
{% include "parody_web/_section_overlay.html" %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python runtests.py 2>&1 | tail -5`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add parody_web/templates/parody_web/_section_head.html parody_web/templates/parody_web/_section_toolbar.html parody_web/templates/parody_web/_section_foot.html parody_web/templates/parody_web/_section_overlay.html parody_web/templates/parody_web/section.html parody_web/tests.py
git commit -m "templates: four host overlay include points on the section page (task #549)"
```

---

### Task 7: Host-integration documentation

**Files:**
- Create: `docs/host-integration.md`
- Modify: `README.md` (link it)

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: the host-facing contract document.

- [ ] **Step 1: Write `docs/host-integration.md`**

Write a document with these sections, using the real names from Tasks 1–6:

1. **What this is** — parody-web serves the book; the host owns readers, courses, and per-user state. Four seams connect them.
2. **Solutions and problems** — `Section.has_solutions`, `.solutions`, `.problems` (shape `{exercise_id: {"title", "content"}}`), `.solution_for()`, `.problem_for()`. Note that storing is not exposing. Note the known limitation: cross-references and citations inside solution/problem content are **not** resolved at import — `number_artifact` rewrites only `section["html"]` — so a `[@key]` in a solution body renders literally; a host that needs them resolved must run its own pass.
3. **Access control** — `PARODY_WEB_ACCESS_POLICY`, the five hooks with their default behaviours in a table, why `request` and not `user`, why `can_view_section` and `section_is_preview` are separate, and a worked example:

```python
# courses/policy.py
from django.utils import timezone

from parody_web.access import DefaultPolicy

from .models import ChecklistItem


class CoursePolicy(DefaultPolicy):
    """Solutions open to enrolled students once the assignment is due."""

    def _due(self, section, exercise_id):
        items = ChecklistItem.objects.filter(
            exercise_id=exercise_id, section_key=section.key,
            assignment__is_published=True).select_related("assignment")
        dues = [i.assignment.due_date for i in items if i.assignment.due_date]
        return min(dues) if dues else None

    def can_view_solution(self, request, section, exercise_id):
        if self.is_owner(request):          # instructors
            return True
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated and is_enrolled(user, section)):
            return False
        due = self._due(section, exercise_id)
        return bool(due and due < timezone.now())

    def solution_denied_context(self, request, section, exercise_id):
        return {"available_after": self._due(section, exercise_id),
                "message": "Solutions open once the assignment is due."}
```

```python
# settings.py
PARODY_WEB_ACCESS_POLICY = "courses.policy.CoursePolicy"
```

4. **The solution URL** — `parody_web:solution` with `(chapter_slug, section_slug, exercise_id)`, 200 / 403 / 404 semantics, `noindex` and sitemap exclusion.
5. **Overlay include points** — the four-partial table from the spec, with a worked `_section_overlay.html` override, and the note that blocks were deliberately not used because Django cannot `{% extends %}` a template it is overriding.
6. **The join key** — key host records to `(book.slug, book.edition_id, section.key)`. Explain that `section.key` is the authored short hash when the book authors one and `chapter_slug/section_slug` otherwise, and why (course books author no hashes: 0 of 43 sections in the EAI golden artifact).
7. **Wearing your own chrome** — list the host app before `parody_web` in `INSTALLED_APPS`, or add a project `TEMPLATES["DIRS"]` entry, and shadow `parody_web/base.html` / `parody_web/_masthead.html`. This is ordinary Django app-directories resolution; nothing in parody-web special-cases it.

- [ ] **Step 2: Link it from the README**

Add a line to `README.md` under whatever section lists documentation (create a short "Documentation" section if there is none):

```markdown
- [Host integration](docs/host-integration.md) — serving a parody book from your
  own Django project: access policy, solutions, overlay hooks, join key.
```

- [ ] **Step 3: Verify the suite is still green**

Run: `python runtests.py 2>&1 | tail -5`
Expected: OK.

- [ ] **Step 4: Commit**

```bash
git add docs/host-integration.md README.md
git commit -m "docs: host-integration contract for the four seams (task #549)"
```

---

### Task 8: Release 0.34.0

**Files:**
- Modify: `pyproject.toml`, `uv.lock`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: parody-web 0.34.0.

- [ ] **Step 1: Confirm the version on main has not moved**

Run: `git fetch origin && git show origin/main:pyproject.toml | grep -m1 '^version'`
Expected: `version = "0.33.0"`. If it is higher, bump from *that* number instead — parody-web's main moves via parallel sessions, and shipping a duplicate version merges without conflict and silently ships nothing.

- [ ] **Step 2: Bump the version**

In `pyproject.toml`, set:

```toml
version = "0.34.0"
```

- [ ] **Step 3: Sync the lockfile**

Run: `uv lock`
Expected: `uv.lock` now pins `parody-web` at 0.34.0. The lock pins the project's own version, so a bump that touches only `pyproject.toml` leaves it stale.

- [ ] **Step 4: Confirm the package ships the new templates**

Run: `grep -n "package-data" -A 12 pyproject.toml`
Expected: templates are included by a pattern that already covers `parody_web/templates/parody_web/*.html`. If templates are enumerated individually, add the four new partials and the two solution templates — parody-web ships static/template assets only if the package-data patterns list them, and a missing entry produces a wheel with no template.

- [ ] **Step 5: Run the full suite one last time**

Run: `python runtests.py 2>&1 | tail -5`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "0.34.0: host-integration seams (task #549)"
```

---

## Self-Review

**Spec coverage:** Seam 1 → Tasks 1–2. Seam 2 → Tasks 3–4. Seam 2b → Task 5. Seam 3 → Task 6. Seam 4 → Task 1 (`Section.key`, `hash` index) + Task 7 §6. Host chrome → Task 7 §7. Docs → Task 7. Testing → tests in every task. Release → Task 8.

**Placeholders:** none — every code step carries the literal code, every test step the literal test.

**Type consistency:** `solution_for`/`problem_for`/`key` are defined in Task 1 and used under those names in Tasks 5, 6, and 7. The five policy hooks are defined in Task 3 and called under those names in Tasks 4, 5, and 7. `_import_solutions()` and `SOLUTIONS_ARTIFACT` are defined in Task 2 and used in Task 5. `OpenPolicy`/`DueDatePolicy` are defined in Task 3 and used in Task 5. `ClosedSectionPolicy` is defined and used in Task 4.
