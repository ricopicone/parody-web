# Section-level drafts

**Status:** approved design, 2026-08-29. Spans `parody` and `parody-web`.
Extends [per-chapter draft mode](2026-08-23-per-chapter-draft-mode-design.md), whose
"Out of scope" section named per-section drafts as the deferred half. Read that spec
first: everything below inherits its threat model, its policy hook, and its surface
table.

## Problem

Chapter-level drafts let a book be released a chapter at a time. The unit of authoring
is finer than that. A chapter can be most of the way finished with one section still
being written, and today the author's only choices are to hold back the whole chapter
or to publish the unfinished section.

The reverse is just as real: a chapter still in development can contain one section
that is ready and wanted — a lab handout, a reference table the class needs this week —
and there is no way to release it without releasing the chapter around it.

## Requirements

1. A section can be marked **draft** in its own front matter.
2. A section that says nothing **inherits its chapter's** draft status. This is what
   makes the feature free for the books already using chapter drafts: nothing changes
   for them.
3. An explicit section flag **overrides** the chapter, in both directions:
   - `draft: true` in a released chapter → that section is hidden.
   - `draft: false` in a draft chapter → that section is published, and the chapter
     becomes visible carrying only its released sections.
4. Hidden means hidden from every reader the access policy excludes, **including
   authenticated students** — requirement 2 of the chapter spec, unchanged and still the
   one the whole feature turns on.
5. **Numbers do not move.** A draft section keeps its number, on the web and in print,
   so releasing a section never renumbers the ones after it.
6. A reference into a draft section renders with its correct number as plain text, no
   link — the chapter rule, applied one level down.

## Approach: resolve at build, gate on the section

The chapter feature gates at import: the artifact carries every chapter and
`parody-web` filters at each surface. Sections keep that shape, with one addition —
**the inheritance is resolved once, in `parody`, before the artifact is written.**

The artifact therefore carries an *effective* `draft` flag on each section: true when
the section declared it, or when it declared nothing and its chapter is draft. Nothing
downstream re-derives it.

This is the whole reason the change is small. `parody-web` never sees the tri-state and
never joins a section to its chapter to decide visibility: every existing
`exclude(chapter__draft=True)` becomes `exclude(draft=True)` on the section itself. A
draft chapter is simply one whose sections all came back draft.

The alternative — carry the tri-state into the database and resolve per query — was
rejected. It puts a two-table rule (`section.draft if not None else chapter.draft`) at
every one of the surfaces the chapter spec enumerates, which is exactly the shape of
duplication that spec set out to avoid with `visible_chapters`. Resolving in the
producer means there is one rule, in one place, and it is testable without a database.

`Chapter.draft` is still carried and still imported. It has two jobs left: the staff
"Draft" badge on a chapter that is genuinely unreleased, and print's whole-chapter skip.
It is no longer what any reader-visibility query asks about.

## Chapter visibility becomes derived

Requirement 3's second half forces this. Today:

```python
chapters.filter(draft=False)
```

A draft chapter holding one released section must appear in the table of contents, or
the released section is unreachable — no TOC line, no chapter page, no prev/next path
into it. So visibility becomes:

```python
chapters.filter(Q(draft=False) | Q(sections__draft=False)).distinct()
```

— a chapter is visible when it is released, or when it still has something to show.
The chapter's own sections list is then filtered as everywhere else, so the reader sees
the chapter with only its released sections in it.

The badge does not follow visibility. `chapter.draft` still drives it, and it still
renders only for a reader who can view drafts, so a student who reaches a partially
released chapter sees no marker on it — they are seeing published material, and the
chapter's own status is not theirs to know. A draft *section*, shown to staff, gets the
same badge treatment one level down.

## Print

`parody pdf` omits draft sections, and the load-bearing consequence is unchanged from
the chapter spec: `section_pdf` slices by page range from the print PDF, so a section
with no page range 404s without needing its own gate, and the annotator and read-along
inherit that through `printing.slice_key_for`.

The counter is the delicate part. A skipped section must still consume its number, or
print and web disagree — a section PDF labelled 3.4 that the site calls 3.5. So in the
chapter loop of `parody/writers/latex.py`, a draft section emits, in its place:

```latex
\stepcounter{section}
```

`\stepcounter`, not `\refstepcounter`, for the reason the chapter spec gives: nothing
labels a draft section, and `\refstepcounter` would leave `\ref` pointing at it.

**Only when that section would have emitted a `\section` at all.** Not every section
does — `synthesize_section_heading` returns the body untouched for a chapter lead-in,
and for a section carrying neither a front-matter title nor a heading of its own. Step
the counter for one of those and the skipped section takes a number it never had. The
predicate mirrors that function's own branches, read off the source markdown:

- slug `lead-in` → no heading, no step;
- an ATX heading at level 1 or 2 (`# `/`## `) in the body → the section's own heading,
  which `_promote_own_heading` raises to `\section` when it claims the section's id →
  step;
- otherwise, a non-empty front-matter `title` → a synthesized `\section` → step;
- otherwise → no heading, no step.

A chapter whose sections are *all* effectively draft keeps today's behaviour exactly:
no `\chapter`, no `\label`, no QR, `\stepcounter{chapter}`, and the `\appendix` switch
still honoured. That is no longer a special case written against `chapter.draft` — it
falls out of every section being skipped, which is the same condition the `edition`
branch immediately above already handles by dropping an empty chapter.

## Schema

Section front matter, beside the `title`/`id`/`hash` already there:

```yaml
---
title: Screw axes
id: screws
hash: k3
draft: true
---
```

Absent = inherit. `draft: false` = publish, whatever the chapter says. YAML
distinguishes the three, which is what makes front matter sufficient on its own.

`parody.yaml` is untouched. Its `sections:` list stays a list of bare slugs, read by
`config.py`, `build.py`, `writers/latex.py` and the edition overlay resolver — none of
which need to change shape.

### Producers

Both of them, resolved by one shared helper so they cannot drift (project memory
`enumerate-every-producer-before-fixing-one`):

- `parody/writers/artifact.py` — `load_section` reads the tri-state; a new
  `resolve_section_draft(declared, chapter_draft)` applies the inheritance.
- `parody/build.py` — writes `"draft": true` on the section object when effective, and
  **omits the key otherwise**, so a book with no drafts produces a byte-identical
  artifact (the `chapter_start` / `cloze_mode` convention). Emitted unconditionally,
  never under `if with_hashes` — see project memory `appendix-flag-needs-schema-2`.
- `parody/writers/latex.py` — the same resolution, off `section_frontmatter(src)`,
  driving the skip and the counter step.

## parody-web

### Model

`Section.draft = BooleanField(default=False)` + migration, set by `import_artifact`
from the artifact and defaulting False when the key is absent, so older artifacts
import unchanged.

### Surfaces

Every one from the chapter spec's table, with the filter moved from the chapter to the
section. The two helpers stay the single obvious thing for a new surface to call, and
gain a sibling:

| helper | change |
|---|---|
| `visible_chapters(book, request)` | released **or** holding a released section |
| `_all_sections_ordered(book, request)` | `exclude(draft=True)` (was `chapter__draft`) |
| `visible_sections(chapter, request)` | **new** — the per-chapter list, for `index` and `_chapter_nav`, which both walked `chapter.sections.all()` raw |

Call sites: `index` (TOC), `_chapter_nav` (prev/next and the rail),
`chapter_detail` (its contents list, its lead-in and its "continue" target),
`section_detail`, `search`, `book_index`, `sitemap_xml`, the table export,
`_resolve_code` (printed short codes), `section_pdf`, `section_pdf_view`, and
`generate_readalong` in `parody_web_readaloud`.

Direct URL access to a draft section returns **404, not 403**, for the chapter spec's
reason: a 403 confirms it exists.

One case deserves naming because it is new. A chapter's lead-in can itself be draft. It
is not a contents entry, so it cannot be hidden by filtering the contents list —
`chapter_detail` renders it directly. It is gated where it is read.

### Cross-references

`numbering.py` already withholds the url of a target inside a draft chapter, so a
reference to it renders as a number in plain text rather than a link into a 404. The
same, one level down: a target inside a draft section registers with its label and no
url, and the chapter-target url reconstruction — which points a chapter reference at
its first section — picks the first **non-draft** section.

As with chapters, this cannot vary by reader: `number_artifact` runs at import and its
output is stored in `Section.html`. A reference into a draft section is plain text for
everyone, staff included. Accepted for the same reason, and staff reach it from the
contents one click away.

## Tests

**The negative tests are the deliverable**, and they must install
`tests_drafts.StudentPolicy`: `DefaultPolicy.is_owner` returns True for any
authenticated user, so a test without a course-shaped policy passes for the wrong
reason. For each surface: anonymous absent, signed-in student absent, staff present.

Beyond the per-surface sweep, the cases that carry this feature:

- **inheritance** — a section that says nothing follows its chapter, both ways;
- **override up** — `draft: false` in a draft chapter is reachable by a student, and
  its chapter appears in the TOC carrying only it;
- **override down** — `draft: true` in a released chapter is 404 for a student while
  its neighbours are fine;
- **numbering is identical** with and without sections marked draft — web *and* print,
  since this is the regression that would silently break every reference;
- **the counter predicate** — a draft lead-in does not step the section counter, a
  titled draft section does;
- **print** — a draft section's text is absent from the emitted `.tex`, and it has no
  page range in the pagemap.

## Out of scope

- Scheduled or automatic release by date (also out of scope for chapters).
- Marking any real book's sections draft. This ships the capability; which sections are
  draft is the author's editorial call.
- A `draft` flag on anything finer than a section.
