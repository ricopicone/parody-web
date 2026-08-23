# Per-chapter draft mode

**Status:** approved design, 2026-08-23. Spans `parody`, `parody-web`, `homepage-django`.

## Problem

The Robotics book (`ricopicone/robotics`, slug `modern-robotics`) is being rolled out to
ME 465 / MME 565 **chapter by chapter** over a semester. Chapter 1 is ready; chapters 2–11
are not. There is today no way to publish part of a book: a chapter is either in the
artifact and visible to every reader who can see the book, or it is not in the artifact at
all.

Removing chapters from `parody.yaml` until they are ready is not acceptable — it renumbers
the book on every release, so a cross-reference, URL, or a number spoken in class silently
means something different the following week.

## Requirements

1. A chapter can be marked **draft** in `parody.yaml`.
2. A draft chapter is invisible to readers — including **authenticated students**. This is
   the requirement the design turns on: `Book.draft` today is gated on `is_owner`, and
   `DefaultPolicy.is_owner` returns true for *any* authenticated user.
3. Visible to **superusers** and **course staff**.
4. **Chapter numbers do not move.** A chapter marked draft still occupies its number, so
   Wheeled Mobile Robots is Chapter 11 from day one.
5. A released chapter may cross-reference a draft chapter. The reference renders with the
   correct number as **plain text, no link** — no 404, no title leak. See
   §"Cross-references": this is reader-independent, because numbering is baked at import.

## Approach: import-time gating

The artifact carries **every** chapter, draft or not. `parody-web` gates the draft ones at
each surface, mirroring the existing per-edition `Book.draft`.

The alternative considered was build-time exclusion (a separate public artifact with draft
chapters omitted), following the precedent of `--online-only` and `--clozes key`. It was
rejected because keeping numbers stable would then require emitting a **numbering
placeholder** for every draft chapter — new machinery in the artifact schema, in
`numbering.py`, and in every view — *and* print would still need its own draft handling.
Import-time gating needs neither: numbering works unchanged because every chapter is
present.

The cost is accepted deliberately: draft chapter HTML lives in the production database, so
correctness depends on every enumeration site filtering. §"Surfaces" enumerates them and
§"Tests" makes the negative cases the deliverable.

## Print is the load-bearing half

`parody pdf` / `parody publish` **omit draft chapters from the print PDF entirely.**

This is not a nicety. Three separate leaks close at once:

- **`book_pdf` view** serves the whole book as one file. If drafts were in the PDF, one
  download hands a student every unreleased chapter.
- **`section_pdf`** slices by page range from that PDF. A draft section has no page range,
  so it 404s without needing its own gate.
- **The annotator and read-along** both resolve through `printing.slice_key_for`, so they
  inherit the same protection.

Draft chapters must also not consume print pages, but they must still consume *chapter
numbers*, or the printed book disagrees with the web.

Concretely, in `parody/writers/latex.py` the chapter loop is at ~436
(`for chapter in project.chapters:`). A draft chapter must emit **no `\chapter`, no
`\label`, no QR and none of its sections** — but still advance the counter:

```latex
\stepcounter{chapter}
```

`\stepcounter`, not `\refstepcounter`: nothing labels a draft chapter, and
`\refstepcounter` would leave `\ref` pointing at it. The step must come **after** the
`\appendix` switch for a draft appendix chapter, since `\appendix` resets the counter to
letter numbering — so the existing `appendix_started` handling has to run for draft
chapters too, even though they emit nothing else.

Note the loop already drops chapters whose section list comes back empty (the `edition`
branch immediately above does exactly this, and `build_project` matches it). A draft
chapter is the same shape of case, with the counter step added.

## Schema

`parody.yaml`, per chapter, beside the existing `appendix`:

```yaml
chapters:
  - slug: intro
  - slug: ch02
    draft: true
```

- `parody/config.py` — `Chapter.draft: bool` parsed alongside `appendix`.
- `parody/build.py` — emitted as `"draft": True` on the chapter object. Emitted
  **unconditionally**, not `if with_hashes`: the `appendix` flag is written only under
  schema 2 and was silently dropped for a year (see project memory
  `appendix-flag-needs-schema-2`). Do not repeat that.
- `parody/writers/latex.py` (or wherever chapters are emitted for print) — skip draft
  chapters, advancing the chapter counter.

## parody-web

### Model

`Chapter.draft = BooleanField(default=False)` + migration. Set by `import_artifact` from
the artifact, defaulting False when the key is absent so older artifacts import unchanged.

### Policy

New hook on `DefaultPolicy`:

```python
def can_view_drafts(self, request):
    """Who may see chapters not yet released. Defaults to is_owner, which on a
    standalone book site is the book's single account."""
    return self.is_owner(request)
```

`homepage-django`'s `CoursePolicy` overrides it:

```python
def can_view_drafts(self, request):
    user = self._user(request)
    return bool(user and (user.is_superuser or user_teaches_any_course(user)))
```

Superusers are **deliberately excluded** from `is_owner` today — that exclusion replaced a
global-flag test which handed every course's solutions to anyone with `is_staff`. Adding
them back is scoped to drafts only and is not a change to `is_owner`.

### Surfaces

Every site enumerating chapters must filter. Enumerated from `parody_web/views.py`:

| surface | location | leak if missed |
|---|---|---|
| book TOC | `index`, ~170–179 | chapter listed |
| prev/next nav | `_chapter_nav`, ~110 | next-link walks into a draft |
| chapter detail | chapter view | direct-URL access |
| section detail | section view | direct-URL access |
| search | `search`, ~297 | **full text in results** |
| subject index | `book_index`, ~194 | index terms leak titles |
| sitemap | `sitemap_xml`, ~714–725 | search engines index it |
| section PDF | `section_pdf`, `section_pdf_view`, ~485/508 | annotatable PDF |
| whole-book PDF | `book_pdf`, ~536 | closed by print exclusion |

Implement as a single helper — `visible_chapters(book, request)` — rather than a filter
repeated nine times, so a new surface has one obvious thing to call.

Direct URL access to a draft chapter or section returns **404, not 403**: a 403 confirms
the chapter exists and leaks its slug.

### Cross-references

`numbering.py` resolves a reference through `_lookup_target`, which returns
`{"label", "url"}`. For a target inside a draft chapter, register the target with its
**label and an empty url**, and emit a bare `<span class="xref">` instead of an `<a>` when
the url is empty. The number is correct because the draft chapter is present and numbered.

**This cannot vary by reader.** `number_artifact` runs at **import**
(`import_artifact.py:111`) and its output is stored in `Section.html`; there is no request
in scope and the HTML is shared by every viewer. So a reference into a draft chapter
renders as plain text **for everyone, course staff included**. Staff reach draft chapters
through the table of contents, which does vary by reader.

Accepted deliberately. The alternative — re-running numbering per request, or storing two
HTML variants per section — costs far more than it returns for a link staff can reach one
click away. Revisit only if authors report the missing links as a real obstacle.

## Rollout

`parody.yaml` marks chapters 2–11 `draft: true`. Releasing a chapter is a one-line edit,
a tag, a repin and a deploy — the existing content chain, no new step.

## Tests

**The negative tests are the deliverable.** Mirroring `tests/test_solutions_only.py`, whose
load-bearing cases are the negatives. For each surface in the table, three cases:

1. anonymous — draft absent
2. **authenticated non-staff (a student)** — draft absent
3. course staff / superuser — draft present

Case 2 is what the requirement turns on and the one most likely to regress, because
`DefaultPolicy.is_owner` treats any authenticated user as the owner.

Plus:
- a cross-reference into a draft chapter renders the right number with no link for a
  student, and a working link for staff;
- chapter numbering is **identical** with and without drafts marked — the regression that
  would silently break every reference;
- the print PDF contains no draft chapter, and a draft section has no page range.

## Out of scope

- Per-*section* drafts. Chapter granularity is what the rollout needs.
- A per-book author designation distinct from course staffing. `CourseStaff` is the
  existing designation and is sufficient; revisit if someone must author a book they do
  not teach.
- Scheduled/automatic release by date.
