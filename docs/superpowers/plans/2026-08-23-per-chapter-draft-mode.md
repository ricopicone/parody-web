# Per-chapter Draft Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a chapter be marked `draft: true` in `parody.yaml` so it keeps its chapter number but is invisible to every reader except course staff and superusers.

**Architecture:** Import-time gating. The artifact carries every chapter; `parody-web` filters draft ones at each surface through one helper; `parody` omits them from the print PDF while stepping the chapter counter so numbering never moves.

**Tech Stack:** Python 3.12, Django 5, pytest (parody), Django `TestCase` (parody-web), LaTeX/memoir (print).

**Spec:** `docs/superpowers/specs/2026-08-23-per-chapter-draft-mode-design.md` (in the parody-web repo)

## Global Constraints

- Three repos, three worktrees: **parody** `/Users/picone/pd-drafts`, **parody-web** `/Users/picone/pw-drafts`, **homepage-django** — branch from `origin/main` in a fresh worktree, never the shared checkout.
- **Never `git add -A`** in parody or parody-web; those trees are shared with concurrent sessions. Stage named paths.
- A version bump must commit **both** `pyproject.toml` and `uv.lock`.
- Re-derive the version against `origin/main` at merge time — both mains move under parallel sessions. As of 2026-08-23: parody `0.53.0`, parody-web `0.68.0`.
- Draft gating must **fail closed**: a surface that forgets to filter is a leak, so every gate defaults to hiding.
- Direct URL access to a draft chapter/section is **404, never 403** — a 403 confirms existence.
- The `draft` key is emitted **unconditionally**, not under `if with_hashes`. The `appendix` flag was written only under schema 2 and was silently dropped for a year (project memory `appendix-flag-needs-schema-2`).

---

### Task 1: `draft` flows from parody.yaml into the artifact

**Files:**
- Modify: `/Users/picone/pd-drafts/parody/config.py:34` (dataclass), `:135-146` (parse)
- Modify: `/Users/picone/pd-drafts/parody/build.py:448-452` (emit)
- Test: `/Users/picone/pd-drafts/tests/test_draft_chapters.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `Chapter.draft: bool` on the config dataclass; artifact chapter objects carry `"draft": True` when set, and omit the key when not.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_draft_chapters.py
import json
import subprocess
import sys
from pathlib import Path

import yaml

from parody.config import load_project


def _book(tmp_path, drafts=()):
    """A two-chapter book; `drafts` names the chapters marked draft."""
    root = tmp_path / "bk"
    (root / "chapters" / "one").mkdir(parents=True)
    (root / "chapters" / "two").mkdir(parents=True)
    for ch in ("one", "two"):
        (root / "chapters" / ch / f"{ch}-a.md").write_text(
            f"---\ntitle: {ch.title()} A\nslug: {ch}-a\n---\nProse in {ch}.\n")
    chapters = []
    for ch in ("one", "two"):
        entry = {"slug": ch, "title": ch.title(), "sections": [f"{ch}-a"]}
        if ch in drafts:
            entry["draft"] = True
        chapters.append(entry)
    (root / "parody.yaml").write_text(yaml.safe_dump({
        "title": "Bk", "slug": "bk", "authors": ["A"], "schema": 2,
        "chapters": chapters,
    }, sort_keys=False))
    return root


def test_config_parses_draft(tmp_path):
    project = load_project(_book(tmp_path, drafts=("two",)))
    by = {c.slug: c for c in project.chapters}
    assert by["one"].draft is False
    assert by["two"].draft is True


def test_artifact_carries_draft(tmp_path):
    root = _book(tmp_path, drafts=("two",))
    out = tmp_path / "bk.json"
    subprocess.run([sys.executable, "-m", "parody", "build", str(root), str(out)],
                   check=True, capture_output=True)
    chapters = json.loads(out.read_text())["chapters"]
    by = {c["slug"]: c for c in chapters}
    assert by["two"]["draft"] is True
    # absent, not False — an older consumer must not see a new key it cannot read
    assert "draft" not in by["one"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd /Users/picone/pd-drafts && uv run pytest tests/test_draft_chapters.py -v`
Expected: FAIL — `AttributeError: 'Chapter' object has no attribute 'draft'`.

- [ ] **Step 3: Add the field and parse it**

In `parody/config.py`, in the `Chapter` dataclass after `appendix`:

```python
    appendix: bool = False  # renders after \appendix (A.1, B.1 numbering)
    draft: bool = False     # authored and numbered, but not yet released:
                            # omitted from print and hidden from readers who
                            # cannot view drafts (parody-web gates it)
```

In `load_project`, in the chapter loop:

```python
            appendix=bool(ch.get("appendix", False)),
            draft=bool(ch.get("draft", False)),
```

- [ ] **Step 4: Emit it into the artifact**

In `parody/build.py`, right after the `chapter_data` dict is built (~448):

```python
            chapter_data = {"title": chapter.title, "slug": chapter.slug, "sections": []}
            # Unconditional, NOT `if with_hashes` — that is how the appendix flag
            # came to be silently dropped for every schema-1 book for a year.
            if chapter.draft:
                chapter_data["draft"] = True
```

- [ ] **Step 5: Run the tests**

Run: `cd /Users/picone/pd-drafts && uv run pytest tests/test_draft_chapters.py -v`
Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/picone/pd-drafts
git add parody/config.py parody/build.py tests/test_draft_chapters.py
git commit -m "feat: a chapter can be marked draft in parody.yaml

Parsed onto Chapter.draft and emitted into the artifact. Written
unconditionally rather than under with_hashes, which is how the appendix
flag came to be dropped for every schema-1 book."
```

---

### Task 2: print omits draft chapters but keeps their numbers

**Files:**
- Modify: `/Users/picone/pd-drafts/parody/writers/latex.py:436-470` (chapter loop)
- Test: `/Users/picone/pd-drafts/tests/test_draft_chapters.py` (append)

**Interfaces:**
- Consumes: `Chapter.draft` from Task 1.
- Produces: LaTeX in which a draft chapter emits `\stepcounter{chapter}` and nothing else.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_draft_chapters.py`:

```python
from parody.writers.latex import build_latex_body  # adjust to the real entry point


def test_print_skips_draft_chapters_but_keeps_the_number(tmp_path, monkeypatch):
    """A draft chapter must not print, but chapter two must still be Chapter 2 —
    otherwise the printed book disagrees with the web and every reference to a
    later chapter silently shifts as chapters are released."""
    root = _book(tmp_path, drafts=("one",))
    monkeypatch.setenv("PARODY_PROJECT_DIR", str(root))
    project = load_project(root)
    tex = build_latex_body(project)          # returns the assembled chapter TeX
    assert "\\chapter{One}" not in tex       # the draft chapter does not print
    assert "\\label{one}" not in tex         # nor does it leave a label behind
    assert "\\stepcounter{chapter}" in tex   # but it consumes its number
    assert "\\chapter{Two}" in tex
```

> If `build_latex_body` is not the real entry point, read `parody/writers/latex.py`
> around line 400–500 and call whatever assembles `chapters_tex`; the assertions
> are what matter. Do not change the production signature to suit the test.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd /Users/picone/pd-drafts && uv run pytest tests/test_draft_chapters.py -k print -v`
Expected: FAIL — `\chapter{One}` is present.

- [ ] **Step 3: Skip drafts in the chapter loop**

In `parody/writers/latex.py`, inside `for chapter in project.chapters:`, immediately
after `sections = chapter.section_slugs` and **before** the `if section:` branch:

```python
            if chapter.draft and not section:
                # Authored but not released: emit no \chapter, no \label, no QR
                # and none of its sections — but still consume the number, so a
                # released later chapter keeps the number the web shows.
                #
                # The \appendix switch must still happen, because it resets the
                # counter to letter numbering; a draft appendix chapter that
                # skipped it would step the arabic counter instead.
                if chapter.appendix and not appendix_started:
                    chapters_tex.append("\\appendix")
                    appendix_started = True
                # \stepcounter, not \refstepcounter: nothing labels a draft
                # chapter, and refstep would leave \ref pointing at it.
                chapters_tex.append("\\stepcounter{chapter}")
                continue
```

- [ ] **Step 4: Run the tests**

Run: `cd /Users/picone/pd-drafts && uv run pytest tests/test_draft_chapters.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full parody suite for regressions**

Run: `cd /Users/picone/pd-drafts && uv run pytest -x -q`
Expected: PASS. The golden artifacts are byte-pinned; if any golden test fails,
a non-draft book's output changed and the guard above is wrong — fix it rather
than re-recording the golden.

- [ ] **Step 6: Commit**

```bash
cd /Users/picone/pd-drafts
git add parody/writers/latex.py tests/test_draft_chapters.py
git commit -m "feat: print omits draft chapters, stepping the chapter counter

Closes the whole-book PDF, the section PDF, the annotator and read-along
in one move: all four resolve through the print page map, so a chapter
absent from the PDF has no page range to slice."
```

---

### Task 3: `Chapter.draft` in parody-web

**Files:**
- Modify: `/Users/picone/pw-drafts/parody_web/models.py:67-78`
- Create: `/Users/picone/pw-drafts/parody_web/migrations/00XX_chapter_draft.py` (generated)
- Modify: `/Users/picone/pw-drafts/parody_web/management/commands/import_artifact.py:162-169`
- Test: `/Users/picone/pw-drafts/parody_web/tests_drafts.py` (create)

**Interfaces:**
- Consumes: the artifact `"draft"` key from Task 1.
- Produces: `Chapter.draft: bool`, and the test helpers `_draft_artifact()` / `_import_drafts()` that Tasks 4–6 reuse.

- [ ] **Step 1: Write the failing test**

```python
# parody_web/tests_drafts.py
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from parody_web.models import Book, Chapter


def _draft_artifact():
    """Three chapters; the middle one is a draft. Chapter three exists so the
    tests can prove a draft does not renumber what follows it."""
    def ch(slug, title, draft=False):
        entry = {"title": title, "slug": slug, "hash": slug[:2],
                 "sections": [{"title": f"{title} A", "slug": f"{slug}-a",
                               "hash": slug[:2] + "a",
                               "html": f"<p>Body of {title}.</p>"}]}
        if draft:
            entry["draft"] = True
        return entry
    return {
        "schema_version": 2, "slug": "dbook", "title": "D Book",
        "author": ["A. Author"],
        "chapters": [ch("one", "One"), ch("two", "Two", draft=True),
                     ch("three", "Three")],
    }


def _import_drafts(art=None):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d, "a.json")
        p.write_text(json.dumps(art or _draft_artifact()))
        call_command("import_artifact", str(p), "--slug", "dbook")


@override_settings(BOOK_SLUG="dbook")
class ChapterDraftImportTests(TestCase):
    def setUp(self):
        _import_drafts()

    def test_draft_flag_is_stored(self):
        book = Book.objects.get(slug="dbook")
        by = {c.slug: c for c in book.chapters.all()}
        self.assertFalse(by["one"].draft)
        self.assertTrue(by["two"].draft)
        self.assertFalse(by["three"].draft)

    def test_absent_key_imports_as_not_draft(self):
        """Artifacts built before this feature must import unchanged."""
        art = _draft_artifact()
        for c in art["chapters"]:
            c.pop("draft", None)
        _import_drafts(art)
        self.assertEqual(Chapter.objects.filter(draft=True).count(), 0)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd /Users/picone/pw-drafts && uv run python -m pytest parody_web/tests_drafts.py -v` (or the project's `manage.py test parody_web.tests_drafts`)
Expected: FAIL — `Chapter has no field named 'draft'`.

- [ ] **Step 3: Add the field**

In `parody_web/models.py`, in `Chapter`, after `appendix`:

```python
    appendix = models.BooleanField(default=False)
    # draft = authored and numbered, but not released. Hidden from every reader
    # the access policy's can_view_drafts() says no to — INCLUDING signed-in
    # students. Kept in the database (rather than withheld from the artifact) so
    # chapter numbering does not move as chapters are released.
    draft = models.BooleanField(default=False)
```

- [ ] **Step 4: Set it on import**

In `import_artifact.py`, in the `Chapter.objects.update_or_create` defaults:

```python
                    "appendix": bool(ch.get("appendix", False)),
                    "draft": bool(ch.get("draft", False)),
```

- [ ] **Step 5: Generate the migration**

```bash
cd /Users/picone/pw-drafts && uv run python -m django makemigrations parody_web --name chapter_draft
```

- [ ] **Step 6: Run the tests**

Run the same command as Step 2. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/picone/pw-drafts
git add parody_web/models.py parody_web/migrations/ \
        parody_web/management/commands/import_artifact.py parody_web/tests_drafts.py
git commit -m "feat: Chapter.draft, imported from the artifact

Defaults False when the key is absent so artifacts built before this
feature import unchanged."
```

---

### Task 4: `can_view_drafts` policy hook and the `visible_chapters` helper

**Files:**
- Modify: `/Users/picone/pw-drafts/parody_web/access.py` (after `is_owner`, ~36)
- Modify: `/Users/picone/pw-drafts/parody_web/views.py` (after `_is_owner`, ~60)
- Test: `/Users/picone/pw-drafts/parody_web/tests_drafts.py` (append)

**Interfaces:**
- Consumes: `Chapter.draft` (Task 3).
- Produces:
  - `DefaultPolicy.can_view_drafts(request) -> bool`
  - `parody_web.views._can_view_drafts(request) -> bool`
  - `parody_web.views.visible_chapters(book, request) -> QuerySet[Chapter]`

- [ ] **Step 1: Write the failing test**

Append to `parody_web/tests_drafts.py`:

```python
from parody_web.access import DefaultPolicy


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

    def test_visible_chapters_hides_drafts_from_a_non_owner(self):
        from parody_web.views import visible_chapters
        book = Book.objects.get(slug="dbook")

        class NoOwner(DefaultPolicy):
            def is_owner(self, request):
                return False

        with override_settings(
                PARODY_WEB_ACCESS_POLICY=f"{NoOwner.__module__}.{NoOwner.__name__}"):
            pass  # policy is resolved per call; see the request-level tests below

        slugs = [c.slug for c in visible_chapters(book, None)]
        self.assertEqual(slugs, ["one", "three"])
```

> `get_policy()` resolves per call, so the request-level assertions live in
> Task 5 where a real `Client` exists. This task's test pins the default
> behaviour: with no request, `DefaultPolicy.is_owner` is False, so drafts hide.

- [ ] **Step 2: Run it and watch it fail**

Expected: FAIL — `DefaultPolicy has no attribute 'can_view_drafts'`.

- [ ] **Step 3: Add the policy hook**

In `parody_web/access.py`, immediately after `is_owner`:

```python
    def can_view_drafts(self, request):
        """Who may see chapters marked draft — authored and numbered, but not
        released.

        Defaults to is_owner, which on a standalone book site is the book's one
        account. A host with real users MUST override this: DefaultPolicy's
        is_owner returns True for any authenticated user, which for a course
        site means every enrolled student.
        """
        return self.is_owner(request)
```

- [ ] **Step 4: Add the view helpers**

In `parody_web/views.py`, after `_is_owner`:

```python
def _can_view_drafts(request):
    """Whether this request may see unreleased chapters."""
    return bool(get_policy().can_view_drafts(request))


def visible_chapters(book, request):
    """The book's chapters this request may see, in reading order.

    One helper rather than a filter repeated at nine call sites: a surface that
    forgets to filter leaks unreleased material, so there should be exactly one
    obvious thing for a new surface to call.
    """
    qs = book.chapters.all()
    if _can_view_drafts(request):
        return qs
    return qs.filter(draft=False)
```

- [ ] **Step 5: Run the tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/picone/pw-drafts
git add parody_web/access.py parody_web/views.py parody_web/tests_drafts.py
git commit -m "feat: can_view_drafts policy hook and visible_chapters helper

One helper for nine call sites: a surface that forgets to filter leaks
unreleased material."
```

---

### Task 5: gate every surface

**Files:**
- Modify: `/Users/picone/pw-drafts/parody_web/views.py` — `index` (~170), `_chapter_nav` (~110), chapter detail, section detail, `search` (~297), `book_index` (~194), `sitemap_xml` (~714), `section_pdf` (~485), `section_pdf_view` (~508)
- Test: `/Users/picone/pw-drafts/parody_web/tests_drafts.py` (append)

**Interfaces:**
- Consumes: `visible_chapters`, `_can_view_drafts` (Task 4).
- Produces: nothing new; every listed view honours the gate.

- [ ] **Step 1: Write the failing tests — the negatives are the deliverable**

Append to `parody_web/tests_drafts.py`:

```python
@override_settings(BOOK_SLUG="dbook",
                   PARODY_WEB_ACCESS_POLICY="parody_web.tests_drafts.StudentPolicy")
class DraftSurfaceTests(TestCase):
    """Every surface, for the reader the requirement turns on: a signed-in
    student. DefaultPolicy.is_owner returns True for ANY authenticated user, so
    without an explicit policy these tests would pass for the wrong reason."""

    def setUp(self):
        _import_drafts()
        User = get_user_model()
        self.student = User.objects.create_user("stu", "stu@example.com", "pw")
        self.staff = User.objects.create_superuser("boss", "boss@example.com", "pw")
        self.anon = Client()
        self.as_student = Client()
        self.as_student.force_login(self.student)
        self.as_staff = Client()
        self.as_staff.force_login(self.staff)

    def _assert_hidden(self, client, url, needle="Two"):
        resp = client.get(url)
        self.assertNotContains(resp, needle, status_code=resp.status_code)

    def test_toc_hides_draft_from_anonymous_and_student(self):
        for c in (self.anon, self.as_student):
            resp = c.get("/")
            self.assertContains(resp, "One")
            self.assertContains(resp, "Three")
            self.assertNotContains(resp, "Two")

    def test_toc_shows_draft_to_staff(self):
        self.assertContains(self.as_staff.get("/"), "Two")

    def test_direct_chapter_url_is_404_not_403(self):
        for c in (self.anon, self.as_student):
            self.assertEqual(c.get("/two/").status_code, 404)
        self.assertEqual(self.as_staff.get("/two/").status_code, 200)

    def test_direct_section_url_is_404(self):
        for c in (self.anon, self.as_student):
            self.assertEqual(c.get("/two/two-a/").status_code, 404)

    def test_search_does_not_return_draft_text(self):
        for c in (self.anon, self.as_student):
            self.assertNotContains(c.get("/search/?q=Body+of+Two"), "Two")

    def test_sitemap_omits_draft(self):
        self.assertNotContains(self.anon.get("/sitemap.xml"), "/two/")

    def test_subject_index_omits_draft(self):
        for c in (self.anon, self.as_student):
            self.assertNotContains(c.get("/index/"), "Two")

    def test_section_pdf_of_a_draft_is_404(self):
        for c in (self.anon, self.as_student):
            self.assertEqual(c.get("/two/two-a/pdf/").status_code, 404)

    def test_next_link_skips_the_draft_chapter(self):
        """Chapter one's next-link must jump to three, not walk into two."""
        resp = self.as_student.get("/one/one-a/")
        self.assertNotContains(resp, "/two/")

    def test_numbering_is_unchanged_by_drafts(self):
        """The regression that would silently break every cross-reference."""
        book = Book.objects.get(slug="dbook")
        by = {c.slug: c.number for c in book.chapters.all()}
        self.assertEqual(by["three"], "3")


class StudentPolicy(DefaultPolicy):
    """A course-shaped policy: signed in is not staff."""

    def is_owner(self, request):
        return bool(request and getattr(request.user, "is_superuser", False))

    def can_view_drafts(self, request):
        return self.is_owner(request)
```

- [ ] **Step 2: Run and watch them fail**

Expected: most FAIL — draft chapter listed, reachable, searchable.

- [ ] **Step 3: Apply the gate at every site**

Replace each `book.chapters.all()` with `visible_chapters(book, request)`:

```python
# index (~174)
    for ch in visible_chapters(book, request):

# sitemap_xml (~725)
    for ch in visible_chapters(book, request):
```

For chapter and section detail, after resolving the chapter:

```python
    if chapter.draft and not _can_view_drafts(request):
        raise Http404          # 404, not 403 — a 403 confirms it exists
```

For `_chapter_nav`, thread the request through (it is called from the section
view, which has one) and filter its chapter lookups the same way. For `search`
and `book_index`, add `chapter__draft=False` to the section queryset unless
`_can_view_drafts(request)`. For `section_pdf` / `section_pdf_view`, add the
same `raise Http404` guard on `section.chapter.draft`.

- [ ] **Step 4: Run the tests**

Expected: all PASS.

- [ ] **Step 5: Run the whole parody-web suite**

Run: `cd /Users/picone/pw-drafts && uv run python -m pytest parody_web -q`
Expected: PASS — in particular `tests.py`'s existing gating tests, which must be
unaffected for books with no drafts.

- [ ] **Step 6: Commit**

```bash
cd /Users/picone/pw-drafts
git add parody_web/views.py parody_web/tests_drafts.py
git commit -m "feat: hide draft chapters at every surface

TOC, chapter and section detail, prev/next nav, search, subject index,
sitemap and section PDF. 404 rather than 403 on direct access: a 403
confirms the chapter exists.

The load-bearing tests are the negatives for a SIGNED-IN STUDENT --
DefaultPolicy.is_owner returns True for any authenticated user, so a
test without an explicit policy would pass for the wrong reason."
```

---

### Task 6: cross-references into a draft chapter render as plain text

**Files:**
- Modify: `/Users/picone/pw-drafts/parody_web/numbering.py` — target registration and the `<a class="xref">` emission
- Test: `/Users/picone/pw-drafts/parody_web/tests_drafts.py` (append)

**Interfaces:**
- Consumes: the artifact's chapter `draft` key — `number_artifact` reads the artifact, not the database.
- Produces: targets inside a draft chapter carry `url == ""`; the renderer emits `<span class="xref">` for those.

- [ ] **Step 1: Write the failing test**

```python
@override_settings(BOOK_SLUG="dbook")
class DraftCrossRefTests(TestCase):
    def test_reference_into_a_draft_chapter_has_the_number_but_no_link(self):
        """Baked at import, so it cannot vary by reader — staff see plain text
        too, and reach the chapter through the table of contents."""
        art = _draft_artifact()
        art["chapters"][0]["sections"][0]["html"] = (
            '<p>See <span class="hashref">th</span>.</p>')
        _import_drafts(art)
        from parody_web.models import Section
        html = Section.objects.get(slug="one-a").html
        self.assertIn("Chapter 3", html)     # released target: still a link
        self.assertIn("<a", html)

        art["chapters"][0]["sections"][0]["html"] = (
            '<p>See <span class="hashref">tw</span>.</p>')
        _import_drafts(art)
        html = Section.objects.get(slug="one-a").html
        self.assertIn("Chapter 2", html)     # right number
        self.assertNotIn('<a class="xref"', html)   # but no link
        self.assertIn('<span class="xref"', html)
        self.assertNotIn("Two", html)        # and no title leak
```

- [ ] **Step 2: Run and watch it fail**

Expected: FAIL — the draft target renders as a link.

- [ ] **Step 3: Register draft targets with an empty url**

In `numbering.py`, where chapter targets are registered (`targets[ch["hash"]] = {...}`),
set `"url": ""` when `ch.get("draft")`, and propagate that to the sections inside it.
Where the anchor is emitted, branch on the empty url:

```python
def _xref_html(target, label):
    """A target in a draft chapter has no url: emit a span, not a dead link.

    Numbering runs at IMPORT and its output is stored in Section.html, so this
    cannot vary by reader — course staff see plain text too and navigate via the
    contents. Storing two variants per section costs far more than it returns.
    """
    if not target.get("url"):
        return f'<span class="xref">{label}</span>'
    return f'<a class="xref" href="{target["url"]}">{label}</a>'
```

Route the existing emission sites (`resolve_cite`, `resolve_any_cite`,
`resolve_plaincite`, `_render_refs`) through it.

- [ ] **Step 4: Run the tests**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/picone/pw-drafts
git add parody_web/numbering.py parody_web/tests_drafts.py
git commit -m "feat: a cross-ref into a draft chapter is plain text, not a link

Correct number, no link, no title. Baked at import, so it cannot vary by
reader -- staff see plain text too and reach drafts via the contents."
```

---

### Task 7: release parody and parody-web

**Files:**
- Modify: `pyproject.toml` + `uv.lock` in both worktrees
- Modify: `CHANGELOG.md` in both, if present

- [ ] **Step 1: Re-derive both versions against `origin/main`**

```bash
cd /Users/picone/pd-drafts && git fetch origin && git log --oneline origin/main -3
cd /Users/picone/pw-drafts && git fetch origin && git log --oneline origin/main -3
```

Both mains move under parallel sessions. Take the version from `origin/main`
**now**, not from this plan. As of writing: parody 0.53.0 → **0.54.0**;
parody-web 0.68.0 → **0.69.0**. Minor bumps: this is a feature.

- [ ] **Step 2: Bump, committing pyproject.toml AND uv.lock together**

`uv.lock` pins the project's own version; a bump touching only `pyproject.toml`
leaves the lock stale.

- [ ] **Step 3: Merge each branch to main and publish**

```bash
cd /Users/picone/pd-drafts && git push origin HEAD:main
uv build && uvx twine upload dist/*      # credentials live in ~/.pypirc
```

Same for parody-web. `uv publish` 403s — it reads the keyring, which has no token.

- [ ] **Step 4: Wait for PyPI, checking from the BOX and not from here**

Your PyPI edge is not the box's. Poll over SSM:

```bash
aws ssm send-command --region us-west-2 --instance-ids i-0ed702541a200396d \
  --document-name AWS-RunShellScript \
  --parameters commands='curl -s https://pypi.org/simple/parody-web/ | grep -c parody_web-0.69.0'
```

Budget ten-plus minutes. A premature deploy fails cleanly at `pip install`,
before migrate/import/collectstatic, so the site keeps serving.

---

### Task 8: `CoursePolicy.can_view_drafts` in homepage-django

**Files:**
- Modify: `~/homepage-django/teaching/parody_policy.py` (after `is_owner`, ~59)
- Modify: `~/homepage-django/requirements.txt` — pin the new parody-web
- Test: `~/homepage-django/teaching/tests.py` (append)

**Interfaces:**
- Consumes: `DefaultPolicy.can_view_drafts` (Task 4).
- Produces: drafts visible to superusers and course staff only.

- [ ] **Step 1: Write the failing test**

```python
def test_can_view_drafts_is_staff_or_superuser(self):
    from teaching.parody_policy import CoursePolicy
    policy = CoursePolicy()

    student = User.objects.create_user("s", "s@stmartin.edu", "pw")
    boss = User.objects.create_superuser("b", "b@stmartin.edu", "pw")
    instructor = User.objects.create_user("i", "i@stmartin.edu", "pw")
    CourseStaff.objects.create(course_version=self.cv, user=instructor,
                               role=ROLE_INSTRUCTOR)

    self.assertFalse(policy.can_view_drafts(_req(None)))
    self.assertFalse(policy.can_view_drafts(_req(student)))
    self.assertTrue(policy.can_view_drafts(_req(boss)))
    self.assertTrue(policy.can_view_drafts(_req(instructor)))
```

Use whatever request stub `teaching/tests.py` already uses for policy tests; if
there is none, `RequestFactory().get("/")` with `request.user` assigned.

- [ ] **Step 2: Run and watch it fail**

Expected: FAIL — the inherited hook defers to `is_owner`, which excludes superusers.

- [ ] **Step 3: Implement**

```python
    def can_view_drafts(self, request):
        """Unreleased chapters: teaching staff, plus superusers.

        Superusers are deliberately NOT part of is_owner — that exclusion
        replaced a global-flag test which handed every course's solutions to
        anyone holding is_staff. Re-admitting them here is scoped to drafts.
        """
        user = self._user(request)
        return bool(user and (user.is_superuser or user_teaches_any_course(user)))
```

- [ ] **Step 4: Run the tests**

Run: `cd ~/homepage-django && .venv/bin/python manage.py test teaching -v1`
Expected: PASS.

- [ ] **Step 5: Commit and deploy**

Bump `parody-web[print,readalong]` in `requirements.txt` to the version from
Task 7, commit both, push `main` → `deploy-ec2.yml`.

**The deploy lock is usually real.** "Another deployment is already in progress"
generally means another session is mid-deploy — check `gh run list` before
touching `/tmp/homepage-django-deploy.lock`, wait, then re-dispatch with
`gh workflow run deploy-ec2.yml`. Note also that the deploy does
`git reset --hard origin/main` **on the box**, so it ships whatever is on main
when it runs, not the commit that triggered it.

---

### Task 9: roll the Robotics book out chapter by chapter

**Files:**
- Modify: `~/mr-integrate/parody.yaml`
- Modify: `~/homepage-django/teaching/content-manifest.json`

- [ ] **Step 1: Mark chapters 2–11 draft**

In `parody.yaml`, add `draft: true` to every chapter after `intro`. Leave the
appendices as they are — decide separately whether the ROS material ships now.

- [ ] **Step 2: Build locally and verify before releasing**

```bash
cd ~/mr-integrate && uv run --project ~/pd-drafts parody build . /tmp/rb.json
```

Assert in the artifact: chapter `intro` has no `draft` key; `ch02` has
`"draft": true`; and **every chapter's `number` is what it was before** — that is
the regression that silently breaks every cross-reference.

- [ ] **Step 3: Tag, repin, sync media, ship the print PDF, deploy**

The full chain, including the two manual side steps the deploy will not do:
`aws s3 sync media/ s3://homepagerico/media/`, and copying
`modern-robotics.pdf` from `print.zip` into
`teaching/notebooks_data/`. See project memory
`robotics-ricopic-one-release-chain`.

- [ ] **Step 4: Verify on the live origin as a student, not as yourself**

The origin IP changes — re-read it from `describe-instances` rather than reusing
one. Then, signed in as a **non-staff account**, confirm chapters 2–11 are absent
from the TOC, 404 on direct URL, absent from search, and that the whole-book PDF
contains only chapter 1.

Being signed in as yourself proves nothing: you are course staff.

---

## Self-Review

**Spec coverage.** Requirement 1 → Task 1. Requirement 2 (invisible to students)
→ Tasks 4, 5, 8, with the student case explicit in every surface test.
Requirement 3 (superusers + staff) → Task 8. Requirement 4 (numbers hold) →
Task 2 for print, Task 3 for the web (all chapters imported, so numbering is
untouched), asserted in Task 5's `test_numbering_is_unchanged_by_drafts` and
Task 9 Step 2. Requirement 5 (cross-refs) → Task 6. Print §→ Task 2. Surfaces
table → Task 5. Tests § → the negatives throughout.

**Placeholders.** One soft spot, flagged inline rather than hidden: Task 2's
entry point (`build_latex_body`) is named from a read of `latex.py` and may
differ; the step says to find the real assembler and keep the assertions. Task 5
describes the `search`/`book_index` query change rather than quoting both
querysets, because their current shape must be read first — the guard itself is
given verbatim.

**Type consistency.** `can_view_drafts(request)` is the name in Tasks 4, 5, 6, 8.
`visible_chapters(book, request)` in Tasks 4, 5. `Chapter.draft` in Tasks 1, 3,
5. `_draft_artifact()` / `_import_drafts()` defined in Task 3 and reused in 4–6.
