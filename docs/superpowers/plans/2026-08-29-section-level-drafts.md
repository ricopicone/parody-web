# Section-Level Drafts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A section can be marked draft in its own front matter; absent means inherit the chapter, and an explicit flag overrides the chapter in both directions.

**Architecture:** The inheritance is resolved once in `parody`, so the artifact carries an *effective* `draft` flag per section and `parody-web` gates on the section alone. Chapter visibility becomes derived — a chapter is visible when it is released *or* still holds a released section. Print skips draft sections but steps the section counter in their place, so numbers never move.

**Tech Stack:** Python 3.11, pytest (parody); Django 5, Django test runner (parody-web); pandoc 3.6.1 / LaTeX for the print path.

**Spec:** `docs/superpowers/specs/2026-08-29-section-level-drafts-design.md` (in the parody-web repo), which extends `docs/superpowers/specs/2026-08-23-per-chapter-draft-mode-design.md`.

## Global Constraints

- **Two repos.** `parody` worktree: `/Users/picone/parody/.claude-worktrees/calm-maple` (branch `calm-maple`, from `origin/main` at 0.54.4). `parody-web` worktree: `/Users/picone/parody-web-worktrees/section-drafts` (branch `section-drafts`, from `origin/main` at 0.95.0).
- **Never `git add -A`.** Both working trees are shared with concurrent agent sessions; stage named paths only (project memory `never-git-add-dash-a-in-shared-worktrees`).
- **Version bumps commit `uv.lock` too** — it pins the project's own version (project memory `version-bumps-must-commit-uv-lock`). Re-derive the version against `origin/main` at merge time, not now.
- **Artifact keys are emitted unconditionally**, never under `if with_hashes` — that is how `appendix` was silently dropped for a year (project memory `appendix-flag-needs-schema-2`).
- **The artifact stays byte-identical for books with no drafts**: emit `"draft": true`, never `"draft": false` (the `chapter_start` / `cloze_mode` convention).
- **Tests that gate on a reader must install `StudentPolicy`** from `parody_web/tests_drafts.py`: `DefaultPolicy.is_owner` returns True for *any* authenticated user, so a test without a course-shaped policy passes for the wrong reason.
- **Refusals are 404, never 403.** A 403 confirms the thing exists.

---

## File Structure

**parody** (`/Users/picone/parody/.claude-worktrees/calm-maple`)

| file | responsibility |
|---|---|
| `parody/writers/artifact.py` | `resolve_section_draft()` — the single inheritance rule, shared by both producers; `load_section` reads the tri-state |
| `parody/build.py` | writes the effective flag onto the artifact's section object |
| `parody/writers/latex.py` | `section_prints_a_heading()` predicate; skips draft sections, steps the counter, derives the whole-chapter skip |
| `tests/test_section_drafts.py` | new — the whole parody-side surface |

**parody-web** (`/Users/picone/parody-web-worktrees/section-drafts`)

| file | responsibility |
|---|---|
| `parody_web/models.py` | `Section.draft` |
| `parody_web/migrations/0014_section_draft.py` | new |
| `parody_web/management/commands/import_artifact.py` | imports the flag |
| `parody_web/views.py` | `visible_sections()`; every enumeration filters on the section |
| `parody_web/numbering.py` | a target inside a draft section carries its label and no link |
| `parody_web/templates/parody_web/{index,chapter,section,_chapter_nav}.html` | the staff "Draft" badge, one level down |
| `parody_web_readaloud/management/commands/generate_readalong.py` | does not voice a draft section |
| `parody_web/tests_section_drafts.py` | new — the per-surface negative sweep |

---

### Task 1: The inheritance rule, and the artifact carries it

**Files:**
- Modify: `parody/writers/artifact.py` (near `load_section`, ~837)
- Modify: `parody/build.py` (~466, the section loop inside `build_project`)
- Test: `tests/test_section_drafts.py` (create)

**Interfaces:**
- Produces: `parody.writers.artifact.resolve_section_draft(declared, chapter_draft) -> bool` where `declared` is `bool | None`; `load_section(...)` returns a dict carrying `"draft": True|False` **only when the section declared one** (key absent = inherit).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_section_drafts.py`. Model the book helper on `tests/test_draft_chapters.py::_book`, but let each section carry its own front-matter flag:

```python
"""A section can be authored and numbered but not yet released.

The chapter is not always the right unit: a chapter can be finished but for
one section, and a chapter still in development can hold one section that is
ready and wanted. `draft:` in a section's front matter says so; absent, the
section inherits its chapter.

See docs/superpowers/specs/2026-08-29-section-level-drafts-design.md (parody-web).
"""
import pytest
import yaml

from parody.build import build_project
from parody.writers.artifact import resolve_section_draft
from parody.writers.latex import build_pdf


def _book(tmp_path, chapter_drafts=(), section_drafts=None):
    """A two-chapter book, two sections each.

    `chapter_drafts` names chapters marked draft in parody.yaml;
    `section_drafts` maps "<ch>/<sec>" to the explicit front-matter value.
    """
    section_drafts = section_drafts or {}
    root = tmp_path / "bk"
    layout = {"one": ("one-a", "one-b"), "two": ("two-a", "two-b")}
    for ch, secs in layout.items():
        (root / "chapters" / ch).mkdir(parents=True)
        for sec in secs:
            fm = {"title": sec.replace("-", " ").title(), "slug": sec}
            declared = section_drafts.get(f"{ch}/{sec}")
            if declared is not None:
                fm["draft"] = declared
            (root / "chapters" / ch / f"{sec}.md").write_text(
                "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n"
                f"Prose in {sec}.\n")
    chapters = []
    for ch, secs in layout.items():
        entry = {"slug": ch, "title": ch.title(), "sections": list(secs)}
        if ch in chapter_drafts:
            entry["draft"] = True
        chapters.append(entry)
    (root / "parody.yaml").write_text(yaml.safe_dump({
        "title": "Bk", "slug": "bk", "authors": ["A. Author"], "schema": 2,
        "chapters": chapters,
    }, sort_keys=False))
    return root


def _sections(art, chapter):
    ch = next(c for c in art["chapters"] if c["slug"] == chapter)
    return {s["slug"]: s for s in ch["sections"]}


def test_resolve_is_the_one_rule():
    """Absent inherits; declared overrides, in both directions."""
    assert resolve_section_draft(None, False) is False
    assert resolve_section_draft(None, True) is True
    assert resolve_section_draft(True, False) is True    # hide out of a release
    assert resolve_section_draft(False, True) is False   # publish out of a draft


def test_a_declared_draft_section_is_marked(tmp_path):
    root = _book(tmp_path, section_drafts={"one/one-b": True})
    art = build_project(root, tmp_path / "bk.json", convert_jupytext=False)
    secs = _sections(art, "one")
    assert secs["one-b"]["draft"] is True
    # Absent rather than False, so a book that marks nothing draft produces a
    # byte-identical artifact and an older consumer meets no key it cannot read.
    assert "draft" not in secs["one-a"]


def test_sections_inherit_a_draft_chapter(tmp_path):
    root = _book(tmp_path, chapter_drafts=("two",))
    art = build_project(root, tmp_path / "bk.json", convert_jupytext=False)
    assert all(s["draft"] is True for s in _sections(art, "two").values())
    assert all("draft" not in s for s in _sections(art, "one").values())


def test_a_published_section_survives_a_draft_chapter(tmp_path):
    """The override that makes the feature worth having: one ready section
    released out of a chapter still in development."""
    root = _book(tmp_path, chapter_drafts=("two",),
                 section_drafts={"two/two-a": False})
    art = build_project(root, tmp_path / "bk.json", convert_jupytext=False)
    secs = _sections(art, "two")
    assert "draft" not in secs["two-a"]
    assert secs["two-b"]["draft"] is True
    # The chapter keeps its own flag: it still drives the staff badge and
    # print's whole-chapter skip.
    ch = next(c for c in art["chapters"] if c["slug"] == "two")
    assert ch["draft"] is True


def test_a_draft_section_does_not_renumber_the_book(tmp_path):
    """The regression that would silently break every cross-reference: every
    section is present, in order, whether or not it is a draft."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    orders = []
    for base, drafts in ((a, {}), (b, {"one/one-a": True, "two/two-b": True})):
        art = build_project(_book(base, section_drafts=drafts),
                            base / "bk.json", convert_jupytext=False)
        orders.append([(c["slug"], [s["slug"] for s in c["sections"]])
                       for c in art["chapters"]])
    assert orders[0] == orders[1]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_section_drafts.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'resolve_section_draft'`.

- [ ] **Step 3: Implement**

In `parody/writers/artifact.py`, above `load_section`:

```python
def resolve_section_draft(declared, chapter_draft):
    """Whether a section is effectively a draft.

    One rule, in one place, because BOTH producers need it — the artifact
    writer and the print writer — and a second copy is how they drift.
    `declared` is the section's own front-matter `draft:` (None when it says
    nothing): absent inherits the chapter, an explicit value overrides it in
    either direction, so a draft section can sit in a released chapter and a
    released section in a draft one.
    """
    return bool(chapter_draft) if declared is None else bool(declared)
```

In `load_section`, beside the existing front-matter reads (near the `hash` block, ~909), record the tri-state on the section dict — the *declaration*, not the resolution, since `load_section` does not know the chapter:

```python
    # The section's own `draft:`, if it declared one. Left ABSENT when it did
    # not, so build_project can tell "inherit" from "explicitly published" —
    # the difference between them is the whole feature.
    if meta.get('draft') is not None:
        section_data['draft'] = bool(meta['draft'])
```

(Place it with the other `section_data[...]` assignments, so it survives whichever return path the function takes.)

In `parody/build.py`, in the section loop right after `section_data = load_section(...)`:

```python
                # Resolve the section's draft status against its chapter's, and
                # emit the flag only when the section is effectively a draft:
                # `false` never reaches the artifact, so a book that marks
                # nothing draft stays byte-identical (as with chapter_start).
                if resolve_section_draft(section_data.pop("draft", None),
                                         chapter.draft):
                    section_data["draft"] = True
```

Import `resolve_section_draft` alongside the existing `load_section` import.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_section_drafts.py -q`
Expected: 5 passed.

- [ ] **Step 5: Check nothing else moved**

Run: `uv run pytest tests/test_draft_chapters.py tests/test_golden_artifacts.py tests/test_editions.py -q`
Expected: all pass. The golden artifacts must be unchanged — no golden book marks a section draft, so no `draft` key may appear. If a golden diff appears, the emit is not conditional; fix the code, never the golden.

- [ ] **Step 6: Commit**

```bash
git add parody/writers/artifact.py parody/build.py tests/test_section_drafts.py
git commit -m "A section's draft status inherits its chapter's unless it says otherwise"
```

---

### Task 2: Print skips a draft section and steps the counter

**Files:**
- Modify: `parody/writers/latex.py` (the chapter loop, ~489–581)
- Test: `tests/test_section_drafts.py` (append)

**Interfaces:**
- Consumes: `resolve_section_draft` from Task 1.
- Produces: `parody.writers.latex.section_prints_a_heading(slug, meta, body) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_section_drafts.py`:

```python
@pytest.fixture
def no_tex(monkeypatch):
    """build_pdf writes the whole LaTeX tree before it calls latexmk, so the
    wiring is checkable by reading the generated sources with no TeX at all."""
    monkeypatch.setattr("parody.writers.latex.shutil.which", lambda *a, **k: None)


def test_print_omits_a_draft_section_but_keeps_its_number(tmp_path, no_tex):
    root = _book(tmp_path, section_drafts={"one/one-a": True})
    build_pdf(root)
    build = root / "build" / "print"
    main = (build / "main.tex").read_text()

    assert "\\chapter{One}" in main                        # the chapter prints
    assert "\\input{sections/one/one-b.tex}" in main
    assert "\\input{sections/one/one-a.tex}" not in main   # the draft does not
    assert not (build / "sections" / "one" / "one-a.tex").exists()
    assert "\\stepcounter{section}" in main                # but takes its number


def test_a_chapter_of_only_drafts_behaves_like_a_draft_chapter(tmp_path, no_tex):
    root = _book(tmp_path, section_drafts={"two/two-a": True, "two/two-b": True})
    build_pdf(root)
    main = (root / "build" / "print" / "main.tex").read_text()
    assert "\\chapter{Two}" not in main       # no heading
    assert "\\label{two}" not in main         # no label
    assert "\\stepcounter{chapter}" in main   # but it consumes its number


def test_a_published_section_prints_out_of_a_draft_chapter(tmp_path, no_tex):
    root = _book(tmp_path, chapter_drafts=("two",),
                 section_drafts={"two/two-a": False})
    build_pdf(root)
    main = (root / "build" / "print" / "main.tex").read_text()
    assert "\\chapter{Two}" in main
    assert "\\input{sections/two/two-a.tex}" in main
    assert "\\input{sections/two/two-b.tex}" not in main


def test_print_without_drafts_is_unchanged(tmp_path, no_tex):
    root = _book(tmp_path)
    build_pdf(root)
    main = (root / "build" / "print" / "main.tex").read_text()
    assert "\\stepcounter{section}" not in main
    assert "\\stepcounter{chapter}" not in main


def test_the_counter_steps_only_for_a_section_that_would_have_a_heading():
    """`\\stepcounter` in place of a section that never emitted a \\section
    would hand it a number it never had — synthesize_section_heading leaves a
    lead-in and a titleless, heading-less section alone."""
    from parody.writers.latex import section_prints_a_heading
    assert section_prints_a_heading("lead-in", {"title": "Intro"}, "text") is False
    assert section_prints_a_heading("s", {"title": "T"}, "text") is True
    assert section_prints_a_heading("s", {}, "text") is False
    assert section_prints_a_heading("s", {}, "# Own heading\n\ntext") is True
    assert section_prints_a_heading("s", {}, "## Own subheading\n\ntext") is True
    assert section_prints_a_heading("s", {}, "### Deeper only\n\ntext") is False


def test_a_draft_section_has_no_print_page_range(tmp_path, no_tex):
    """Which is what makes section_pdf 404 on the web without its own gate."""
    root = _book(tmp_path, section_drafts={"one/one-a": True})
    build_pdf(root, pagemap=True)
    main = (root / "build" / "print" / "main.tex").read_text()
    assert "\\parodypagemark{one/one-b}" in main
    assert "\\parodypagemark{one/one-a}" not in main
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_section_drafts.py -q -k "print or counter"`
Expected: FAIL — `section_prints_a_heading` does not exist, and the draft section still prints.

- [ ] **Step 3: Implement the predicate**

In `parody/writers/latex.py`, beside `synthesize_section_heading` (~219):

```python
# An ATX heading of level 1 or 2 at the start of a line: the section's own
# heading, which pandoc renders as \section (or \subsection, which
# _promote_own_heading raises when it claims the section's id).
_ATX_OWN_HEADING = re.compile(r"(?m)^#{1,2} \S")


def section_prints_a_heading(slug, meta, body):
    r"""Whether this section emits a ``\section`` — mirroring the branches of
    synthesize_section_heading, read off the SOURCE markdown.

    A draft section is skipped but must still consume its number, and the step
    is only right for a section that had one: a chapter lead-in emits no
    heading (the ``\chapter`` is its heading), and neither does a section
    carrying no front-matter title and no heading of its own. Stepping for one
    of those would hand the skipped section a number it never had, moving every
    section after it — the exact disagreement between print and web this
    feature must not introduce.
    """
    if slug == "lead-in":
        return False
    if _ATX_OWN_HEADING.search(body or ""):
        return True
    return bool(str((meta or {}).get("title") or "").strip())
```

- [ ] **Step 4: Implement the loop change**

In the chapter loop, replace the `if chapter.draft and not section:` block (~490–506) and the section iteration so that the skip is *derived*. After the `edition` filtering of `sections` and before `if sections and not section:`:

```python
            # Resolve each section's draft status against the chapter's. A
            # draft section does not print — and a chapter whose sections are
            # ALL drafts (which is every section of a draft chapter that says
            # nothing) prints nothing at all, which is the whole-chapter skip
            # this used to spell out against chapter.draft.
            #
            # An explicit `--section ch/sec` overrides: an author asking for one
            # section by name gets it, draft or not.
            drafts = {}
            if not section:
                for s in sections:
                    src_name = (_resolve_section_file(chapter.directory, s,
                                                      edition["id"])
                                if edition else f"{s}.md")
                    fm = section_frontmatter(chapter.directory / src_name)
                    drafts[s] = resolve_section_draft(fm.get("draft"),
                                                      chapter.draft)
            live = [s for s in sections if not drafts.get(s)]
            if not live and not section:
                # Nothing to print. Consume the chapter number so a chapter
                # released later keeps the number the web already shows it
                # under. The \appendix switch still has to happen first: it
                # resets the counter to letter numbering, so stepping before it
                # would advance the arabic counter instead.
                #
                # `chapter.draft or sections`: a chapter left empty by an
                # EDITION is absent from that edition entirely and consumes no
                # number, which is the behaviour immediately below.
                if chapter.draft or sections:
                    if chapter.appendix and not appendix_started:
                        chapters_tex.append("\\appendix")
                        appendix_started = True
                    # \stepcounter, not \refstepcounter: nothing labels a draft
                    # chapter, and refstep would leave \ref pointing at it.
                    chapters_tex.append("\\stepcounter{chapter}")
                continue
```

Change the chapter-heading guard and the first-section flag from `sections` to `live`:

```python
            if live and not section:
                ...                     # (was: if sections and not section:)
            first_in_chapter = bool(live) and not section
```

Then, at the top of the `for sec_slug in sections:` body, before `key = ...`:

```python
                if drafts.get(sec_slug):
                    # Skipped, but it keeps its number — only if it would have
                    # had one. Emitted in position, so the sections after it
                    # number exactly as they do on the web.
                    src = chapter.directory / (
                        _resolve_section_file(chapter.directory, sec_slug,
                                              edition["id"])
                        if edition else f"{sec_slug}.md")
                    if section_prints_a_heading(
                            sec_slug, section_frontmatter(src),
                            src.read_text(encoding="utf-8")):
                        chapters_tex.append("\\stepcounter{section}")
                    continue
```

Import `resolve_section_draft` from `.artifact` at the top of `latex.py` (check whether that import would be circular — `writers/artifact.py` does not import `writers/latex.py`, so a module-level import is fine; if it turns out to be, import inside the function and say why).

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_section_drafts.py -q`
Expected: 12 passed.

- [ ] **Step 6: Check the print path did not regress**

Run: `uv run pytest tests/test_draft_chapters.py tests/test_pagemap.py tests/test_pagemap_build.py tests/test_print_includes.py tests/test_editions.py -q`
Expected: all pass. `test_draft_chapters.py` is the load-bearing one — the whole-chapter skip is now derived and must behave identically.

- [ ] **Step 7: Commit**

```bash
git add parody/writers/latex.py tests/test_section_drafts.py
git commit -m "Print skips a draft section and steps the counter in its place"
```

---

### Task 3: parody-web stores and imports the flag

**Files:**
- Modify: `parody_web/models.py` (`Section`, ~89)
- Create: `parody_web/migrations/0014_section_draft.py`
- Modify: `parody_web/management/commands/import_artifact.py` (~172)
- Test: `parody_web/tests_section_drafts.py` (create)

**Interfaces:**
- Produces: `Section.draft` (BooleanField, default False) — the **effective** flag, already resolved by parody.

- [ ] **Step 1: Write the failing test**

Create `parody_web/tests_section_drafts.py`. Reuse the course-shaped policy from the chapter tests rather than redefining it:

```python
"""Per-section draft mode.

The chapter is not always the right unit of release. A section carries its own
draft status, resolved against its chapter's by `parody` before the artifact is
written — so everything here gates on the SECTION, and a chapter is visible
when it is released or still holds a released section.

The negative cases are the deliverable, and they run under StudentPolicy:
DefaultPolicy.is_owner returns True for any authenticated user, so a test
without a course-shaped policy passes for the wrong reason.

See docs/superpowers/specs/2026-08-29-section-level-drafts-design.md
"""
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from parody_web.models import Book, Section
from parody_web.tests_drafts import StudentPolicy

POLICY = "parody_web.tests_drafts.StudentPolicy"


def _artifact(chapter_drafts=(), section_drafts=None):
    """Two chapters of two sections. `section_drafts` maps "<ch>/<sec>" to the
    EFFECTIVE flag, exactly as parody resolves it into the artifact."""
    section_drafts = section_drafts or {}
    chapters = []
    for ch in ("one", "two"):
        sections = []
        for sec in (f"{ch}-a", f"{ch}-b"):
            entry = {
                "slug": sec, "title": sec.title(), "hash": sec[:1] + sec[-1],
                "html": f"<p>Prose in {sec}.</p>", "anchors": [],
            }
            if section_drafts.get(f"{ch}/{sec}", ch in chapter_drafts):
                entry["draft"] = True
            sections.append(entry)
        entry = {"slug": ch, "title": ch.title(), "hash": ch[:2],
                 "sections": sections}
        if ch in chapter_drafts:
            entry["draft"] = True
        chapters.append(entry)
    return {"schema_version": 2, "title": "Bk", "slug": "bk",
            "author": ["A. Author"], "chapters": chapters}


def _import(data):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bk.json"
        p.write_text(json.dumps(data))
        call_command("import_artifact", str(p), verbosity=0)
    return Book.objects.get(slug="bk")


class ImportTests(TestCase):
    def test_the_flag_is_stored(self):
        _import(_artifact(section_drafts={"one/one-b": True}))
        by = {s.slug: s for s in Section.objects.all()}
        self.assertTrue(by["one-b"].draft)
        self.assertFalse(by["one-a"].draft)

    def test_an_absent_key_imports_as_not_draft(self):
        _import(_artifact())
        self.assertFalse(any(s.draft for s in Section.objects.all()))

    def test_a_published_section_of_a_draft_chapter(self):
        _import(_artifact(chapter_drafts=("two",),
                          section_drafts={"two/two-a": False}))
        by = {s.slug: s for s in Section.objects.all()}
        self.assertFalse(by["two-a"].draft)
        self.assertTrue(by["two-b"].draft)
        # The chapter keeps its own flag — it still drives the staff badge.
        self.assertTrue(by["two-a"].chapter.draft)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/picone/parody-web-worktrees/section-drafts && uv run python -m django test parody_web.tests_section_drafts --settings=example_site.settings`
(If that settings path is wrong, use the invocation the repo's existing test runs use — check `.github/workflows/` for the exact command and use it verbatim for every test step in this plan.)
Expected: FAIL — `Section` has no field `draft`.

- [ ] **Step 3: Implement**

`parody_web/models.py`, in `Section`, immediately after `preview`:

```python
    # draft = authored and NUMBERED, but not released. The EFFECTIVE flag:
    # parody resolved the section's own front-matter `draft:` against its
    # chapter's before writing the artifact, so nothing here re-derives it and
    # every surface gates on the section alone. A draft chapter is simply one
    # whose sections all came back draft.
    draft = models.BooleanField(default=False)
```

Migration `parody_web/migrations/0014_section_draft.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('parody_web', '0013_chapter_draft'),
    ]

    operations = [
        migrations.AddField(
            model_name='section',
            name='draft',
            field=models.BooleanField(default=False),
        ),
    ]
```

`import_artifact.py`, in the `Section.objects.update_or_create` defaults, beside `"preview"`:

```python
                        "draft": bool(sec.get("draft", False)),
```

- [ ] **Step 4: Run to verify it passes**

Run the test command from Step 2, plus `makemigrations --check --dry-run` to prove the migration matches the model.
Expected: 3 passed; no missing migrations.

- [ ] **Step 5: Commit**

```bash
git add parody_web/models.py parody_web/migrations/0014_section_draft.py \
        parody_web/management/commands/import_artifact.py \
        parody_web/tests_section_drafts.py
git commit -m "A section carries its own draft flag"
```

---

### Task 4: Every surface gates on the section

**Files:**
- Modify: `parody_web/views.py` — `visible_chapters` (~68), `_all_sections_ordered` (~117), `_chapter_nav` (~138), `index` (~204), `chapter_detail` (~363), `section_detail` (~407), `search` (~341), `section_pdf` (~544), `section_pdf_view` (~573)
- Modify: `parody_web_readaloud/management/commands/generate_readalong.py` (~184)
- Test: `parody_web/tests_section_drafts.py` (append)

**Interfaces:**
- Consumes: `Section.draft` from Task 3.
- Produces: `parody_web.views.visible_sections(chapter, request) -> list[Section]`.

- [ ] **Step 1: Write the failing tests**

Append to `parody_web/tests_section_drafts.py`:

```python
@override_settings(PARODY_WEB_ACCESS_POLICY=POLICY)
class SurfaceTests(TestCase):
    """One draft section in a released chapter; one released section in a
    draft chapter. Every surface, for all three readers."""

    @classmethod
    def setUpTestData(cls):
        cls.book = _import(_artifact(
            chapter_drafts=("two",),
            section_drafts={"one/one-b": True, "two/two-a": False}))
        User = get_user_model()
        cls.student = User.objects.create_user("stu", password="x")
        cls.staff = User.objects.create_superuser("boss", password="x")

    def _client(self, who=None):
        c = Client()
        if who:
            c.force_login(who)
        return c

    def _readers(self):
        return [("anonymous", self._client()),
                ("student", self._client(self.student))]

    def test_the_contents_hides_a_draft_section(self):
        for who, c in self._readers():
            body = c.get("/").content.decode()
            with self.subTest(who=who):
                self.assertNotIn("One-B", body)
                self.assertIn("One-A", body)

    def test_the_contents_shows_a_released_section_of_a_draft_chapter(self):
        """And so lists the chapter, which would otherwise be unreachable."""
        for who, c in self._readers():
            body = c.get("/").content.decode()
            with self.subTest(who=who):
                self.assertIn("Two-A", body)
                self.assertNotIn("Two-B", body)

    def test_staff_see_everything(self):
        body = self._client(self.staff).get("/").content.decode()
        for title in ("One-A", "One-B", "Two-A", "Two-B"):
            self.assertIn(title, body)

    def test_a_draft_section_is_404(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/one/one-b/").status_code, 404)
                self.assertEqual(c.get("/two/two-b/").status_code, 404)

    def test_a_released_section_of_a_draft_chapter_is_reachable(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                r = c.get("/two/two-a/")
                self.assertEqual(r.status_code, 200)
                self.assertIn("Prose in two-a", r.content.decode())

    def test_a_partly_released_chapter_page_lists_only_what_is_released(self):
        for who, c in self._readers():
            r = c.get("/two/")
            with self.subTest(who=who):
                self.assertEqual(r.status_code, 200)
                self.assertIn("Two-A", r.content.decode())
                self.assertNotIn("Two-B", r.content.decode())

    def test_a_chapter_with_nothing_released_is_404(self):
        book = _import(_artifact(chapter_drafts=("two",)))
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/two/").status_code, 404)

    def test_search_does_not_return_draft_text(self):
        for who, c in self._readers():
            body = c.get("/search/?q=Prose").content.decode()
            with self.subTest(who=who):
                self.assertNotIn("one-b", body)
                self.assertNotIn("two-b", body)
                self.assertIn("one-a", body)

    def test_the_sitemap_omits_draft_sections(self):
        body = self._client().get("/sitemap.xml").content.decode()
        self.assertNotIn("/one/one-b/", body)
        self.assertIn("/one/one-a/", body)
        self.assertIn("/two/two-a/", body)

    def test_a_short_code_for_a_draft_section_does_not_resolve(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/ob").status_code, 404)   # one-b's hash
                self.assertEqual(c.get("/oa").status_code, 302)   # one-a's

    def test_the_section_pdf_of_a_draft_is_404(self):
        for who, c in self._readers():
            with self.subTest(who=who):
                self.assertEqual(c.get("/one/one-b/pdf/").status_code, 404)
```

Check the URL shapes against `parody_web/urls.py` before running — the short-code and PDF paths must be written exactly as the repo routes them, and `tests_drafts.py` already exercises both (`test_a_code_for_a_draft_section_does_not_resolve`, `test_section_pdf_of_a_draft_is_404`); copy their request paths.

- [ ] **Step 2: Run to verify it fails**

Run the Django test command for `parody_web.tests_section_drafts`.
Expected: FAIL — draft sections are listed and reachable.

- [ ] **Step 3: Implement**

`visible_chapters` — released, or still holding a released section:

```python
def visible_chapters(book, request):
    """The book's chapters this request may see, in reading order.

    A chapter is visible when it is released, or when it still holds a released
    section: a section marked `draft: false` inside a draft chapter must be
    reachable, and it has no TOC line, no chapter page and no nav path unless
    its chapter appears. Its sections are filtered as everywhere else, so the
    chapter shows only what is released.

    One helper rather than the same filter written out at nine call sites: a
    surface that forgets to filter leaks unreleased material to a class.
    """
    chapters = book.chapters.all()
    if _can_view_drafts(request):
        return chapters
    return chapters.filter(
        Q(draft=False) | Q(sections__draft=False)).distinct()
```

Add `from django.db.models import Q` to the imports.

`_all_sections_ordered` — the filter moves to the section (the effective flag already accounts for the chapter):

```python
    if not _can_view_drafts(request):
        qs = qs.exclude(draft=True)
```

New sibling, beside it:

```python
def visible_sections(chapter, request):
    """One chapter's sections this request may see, in reading order.

    The per-chapter counterpart of _all_sections_ordered, for the surfaces that
    walk a single chapter (the contents, the rail, the chapter page).
    """
    qs = chapter.sections.all()
    if not _can_view_drafts(request):
        qs = qs.exclude(draft=True)
    return list(qs)
```

Then route the raw walks through it. `_chapter_nav` takes a `request` (every caller has one):

```python
def _chapter_nav(book, chapter, current=None, request=None):
    out = []
    for s in visible_sections(chapter, request):
        ...
```

`index`: `sections = visible_sections(ch, request)`.

`chapter_detail`: replace the `chapter.draft` gate with a visibility test, and filter its own lists:

```python
    chapter = visible_chapters(book, request).filter(slug=chapter_slug).first()
```

(keeping the existing `if chapter is None:` short-code fallback and its 404), then:

```python
    sections = visible_sections(chapter, request)
```

and pass `request` to `_chapter_nav`. The lead-in is not a contents entry, so it is not filtered by the list comprehension — `visible_sections` covers it, since `leadin` is chosen from `sections`.

`section_detail`, `section_pdf`, `section_pdf_view`: `section.chapter.draft` → `section.draft`, comment unchanged in intent:

```python
    if section.draft and not _can_view_drafts(request):
        raise Http404("section not available")
```

`search`: `qs.exclude(chapter__draft=True)` → `qs.exclude(draft=True)`.

`generate_readalong.py`: `qs.exclude(chapter__draft=True)` → `qs.exclude(draft=True)`, and update the comment above it — "a DRAFT chapter is not released, so it is not voiced" becomes the section, noting that a draft chapter's sections are all draft so the chapter case still holds.

- [ ] **Step 4: Run to verify it passes**

Run the Django test command for `parody_web.tests_section_drafts`.
Expected: all pass.

- [ ] **Step 5: Run the whole suite — the chapter tests are the regression gate**

Run the repo's full test command (as used in CI), including `parody_web.tests_drafts`, `parody_web.tests`, `parody_web_readaloud`.
Expected: all pass. `tests_drafts.py` must pass **unmodified**: chapter drafts still behave exactly as they did, now by derivation.

- [ ] **Step 6: Commit**

```bash
git add parody_web/views.py parody_web/tests_section_drafts.py \
        parody_web_readaloud/management/commands/generate_readalong.py
git commit -m "Every surface gates on the section, and a chapter is visible when it still has one"
```

---

### Task 5: A reference into a draft section is a number, not a link

**Files:**
- Modify: `parody_web/numbering.py` — `_target_url` (~190), the chapter-target block (~1151), the per-section loop (~1169)
- Test: `parody_web/tests_section_drafts.py` (append)

**Interfaces:**
- Consumes: the artifact's per-section `draft` key (Task 1).
- Produces: target entries carrying `"draft": True`, which `_target_url` renders link-less.

- [ ] **Step 1: Write the failing test**

Append to `parody_web/tests_section_drafts.py`:

```python
class CrossReferenceTests(TestCase):
    """Numbering runs at IMPORT, so this cannot vary by reader — a reference
    into a draft section is plain text for everyone, staff included. Staff
    reach the section from the contents one click away."""

    def _import_with_ref(self, target_hash):
        data = _artifact(section_drafts={"one/one-b": True})
        ch = data["chapters"][0]
        ch["sections"][0]["html"] = (
            '<p>See <span class="hashref">%s</span>.</p>' % target_hash)
        for sec in ch["sections"]:
            sec["anchors"] = [{"type": "heading", "level": 1,
                               "is_section": True,
                               "hash": sec["hash"], "id": sec["slug"]}]
        return _import(data)

    def test_a_reference_into_a_draft_section_has_no_link(self):
        book = self._import_with_ref("ob")     # one-b, a draft
        html = book.sections.get(slug="one-a").html
        self.assertIn("Section 1.2", html)     # the number is right
        self.assertNotIn('href="/one/one-b/', html)

    def test_a_reference_into_a_released_section_is_still_a_link(self):
        book = self._import_with_ref("oa")     # one-a, released
        html = book.sections.get(slug="one-a").html
        self.assertIn('href="/one/one-a/', html)
```

Check the reference markup against `tests_drafts.py::test_reference_into_a_draft_chapter_has_the_number_but_no_link` and mirror whatever that test uses — the hashref span shape and the anchor dicts must match what `number_artifact` actually consumes, or the test passes vacuously by resolving nothing.

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — the draft section's target still carries its url, so the reference renders as an `<a>`.

- [ ] **Step 3: Implement**

`_target_url`, extending the existing draft rule one level down:

```python
def _target_url(t):
    """The href for a resolved target; chapter refs point at their first section.

    A target in a DRAFT section — which includes every target in a draft
    chapter, since its sections all resolve draft — gets "" — no href at all.
    The section is numbered but unreleased, so the reference keeps its number
    and _link renders it as a span. Checked here as well as at registration
    because this function RECONSTRUCTS a missing url from the chapter's
    sections, which would otherwise hand back a link into a 404.
    """
    chapter = t.get("chapter")
    if t.get("draft") or (chapter and chapter.get("draft")):
        return ""
    url = t.get("url")
    if url is None and chapter:
        secs = [s for s in chapter.get("sections", []) if not s.get("draft")]
        url = f"/{chapter['slug']}/{secs[0]['slug']}/" if secs else "#"
    return url or "#"
```

The chapter-target block: point a chapter reference at its first **released** section:

```python
        if ch.get("hash"):
            secs = [s for s in ch.get("sections", []) if not s.get("draft")]
            ch_url = (f"/{ch['slug']}/{secs[0]['slug']}/{edition_query}"
                      if secs else None)
```

Marking a draft section's targets: every one of the dozen registrations inside the section loop builds its url from the local `url`, so mark them in one place after the section is done rather than guarding each site. At the top of the `for sec in ch.get("sections", []):` body:

```python
            # Targets registered while walking a DRAFT section are marked after
            # the fact — a dozen registrations below all build their href from
            # `url`, and one post-pass cannot be forgotten by the next one
            # added. Identity, not just membership: a later section may reuse
            # an id, replacing the entry under a key that was already there.
            before = ({k: id(v) for k, v in targets.items()}
                      if sec.get("draft") else None)
```

and at the end of that loop body (after every registration, before the next section):

```python
            if before is not None:
                for k, v in targets.items():
                    if before.get(k) != id(v):
                        v["draft"] = True
```

Take care that the marker lands at the end of the **section** loop body, not inside a nested anchor loop.

- [ ] **Step 4: Run to verify it passes**

Expected: both pass.

- [ ] **Step 5: Regression**

Run `parody_web.tests_drafts` and `parody_web.tests` in full. `test_reference_into_a_draft_chapter_has_the_number_but_no_link` and `test_reference_to_a_released_chapter_is_still_a_link` must both still pass.

- [ ] **Step 6: Commit**

```bash
git add parody_web/numbering.py parody_web/tests_section_drafts.py
git commit -m "A reference into a draft section keeps its number and loses its link"
```

---

### Task 6: The staff marker, one level down

**Files:**
- Modify: `parody_web/templates/parody_web/index.html` (~57), `chapter.html` (~15–16), `section.html` (~15–16), `_chapter_nav.html` (~3)
- Test: `parody_web/tests_section_drafts.py` (append)

**Interfaces:**
- Consumes: `Section.draft`; the existing `.draft-tag` / `.draft-banner` CSS (no new styles).

- [ ] **Step 1: Write the failing test**

```python
@override_settings(PARODY_WEB_ACCESS_POLICY=POLICY)
class MarkerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.book = _import(_artifact(section_drafts={"one/one-b": True}))
        cls.staff = get_user_model().objects.create_superuser("boss", password="x")

    def _staff(self):
        c = Client()
        c.force_login(self.staff)
        return c

    def test_the_contents_marks_a_draft_section(self):
        body = self._staff().get("/").content.decode()
        self.assertEqual(body.count("draft-tag"), 1)

    def test_the_section_page_says_so(self):
        body = self._staff().get("/one/one-b/").content.decode()
        self.assertIn("draft-banner", body)

    def test_a_released_section_says_nothing(self):
        body = self._staff().get("/one/one-a/").content.decode()
        self.assertNotIn("draft-banner", body)
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — no marker on a draft section.

- [ ] **Step 3: Implement**

`index.html`, on each section line in the chapter's list (matching the chapter's own tag on line 57):

```html
{% if section.draft %}<span class="draft-tag" title="Not yet visible to readers">Draft</span>{% endif %}
```

`_chapter_nav.html`, on each rail entry; `chapter.html`, on each contents entry; and `section.html`, where the chapter banner is, add the section's own — the section banner takes precedence, since it is the more specific statement:

```html
{% if section.draft %}<div class="draft-banner">This section is <strong>in development</strong> and not yet visible to readers — you are viewing it as staff.</div>{% elif chapter.draft %}<div class="draft-banner">This section belongs to a chapter <strong>in development</strong> and is not yet visible to readers — you are viewing it as staff.</div>{% endif %}
```

Read each template before editing: the exact element each tag hangs off differs, and the existing chapter markup is the pattern to copy.

- [ ] **Step 4: Run to verify it passes**, then the full suite again.

- [ ] **Step 5: Commit**

```bash
git add parody_web/templates/parody_web/ parody_web/tests_section_drafts.py
git commit -m "Mark a draft section for the staff who can see it"
```

---

### Task 7: Release both packages and deploy

**Files:**
- Modify: `pyproject.toml` + `uv.lock` in both repos
- Modify: `docs/` release notes / CHANGELOG if the repo keeps one (check `git show` on the last release commit for the shape)

- [ ] **Step 1: Re-derive the versions against `origin/main`**

`git fetch && git show origin/main:pyproject.toml | grep '^version'` in **both** repos. Two sessions bumping to the same number merge with no conflict and ship a duplicate release (project memory `recheck-version-against-main-before-merging`). Expected at plan time: parody 0.54.4 → **0.55.0**, parody-web 0.95.0 → **0.96.0**; both are minors, this is a feature.

- [ ] **Step 2: Bump, and commit `pyproject.toml` with `uv.lock` in the same commit**

```bash
uv lock && git add pyproject.toml uv.lock && git commit -m "0.55.0: a section can be a draft, and inherits its chapter when it says nothing"
```

- [ ] **Step 3: Full test run in both repos, then push**

Push the branch to main (`git push origin section-drafts:main`), which is how these repos release from a worktree.

- [ ] **Step 4: Wait for CI green, then publish to PyPI**

Follow whatever the repo's release path is (a tag, or a workflow dispatch) — check `.github/workflows/` rather than assuming.

- [ ] **Step 5: Verify propagation FROM THE BOX, not from here**

`pip download` of the exact pin on the EC2 box. Curling the simple index from the box is **not** clearance, and the box's index lags this laptop's by 10+ minutes (project memory `pypi-propagation-lag-is-measured-from-the-box`).

- [ ] **Step 6: Repin and deploy `homepage-django`**

Branch from `origin/main` in a worktree — the local `main` there may carry another session's merged-but-unpushed work (project memory `homepage-django-local-main-may-be-ahead-unpushed`). Check `gh run list` before dispatching: "another deployment in progress" is usually true, not a stale lock.

- [ ] **Step 7: Verify on the deployed site**

The migration must have run, and a book with no drafts must render exactly as before. Verify the shipped path, not the dev one.

---

## Self-Review

**Spec coverage.** Requirements 1–3 → Task 1 (rule + artifact) and Task 3 (import). Requirement 4 → Task 4's per-reader sweep under `StudentPolicy`. Requirement 5 → Task 1's ordering test (web) and Task 2's counter test (print). Requirement 6 → Task 5. The spec's derived-chapter-visibility section → Task 4's `visible_chapters`. The spec's badge paragraph → Task 6. The spec's print section, including the counter predicate → Task 2. The spec's lead-in note → Task 4 (`visible_sections` covers it, since `chapter_detail` picks the lead-in out of that list).

**Placeholders.** None: every code step carries the code. Three steps deliberately say "check the repo before writing" (the Django test invocation, the URL shapes, the template markup) — those are instructions to read existing code, not deferred decisions, and each names exactly what to read and why.

**Type consistency.** `resolve_section_draft(declared, chapter_draft) -> bool` is defined in Task 1 and consumed in Task 2 with those argument names. `section_prints_a_heading(slug, meta, body) -> bool` is defined and tested in Task 2 and used once, in the same task. `visible_sections(chapter, request) -> list[Section]` is defined in Task 4 and used only there and in Task 6's templates via the context it fills. `Section.draft` is the same name in the model, the migration, the importer, the queries and the templates.
