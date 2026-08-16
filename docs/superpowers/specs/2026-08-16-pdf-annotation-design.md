# Per-section PDF annotation — design

**Status:** approved design, 2026-08-16
**Follows:** `2026-08-13-section-print-pdf-design.md` (per-section print PDFs)

## Goal

A reader opens a section's PDF full-window, writes on it freehand with a
stylus, and their marks are still there next time — permanently, and
specifically on *the version they annotated*. When a newer PDF of that section
is issued, the new one appears too; the annotated old one does not disappear.

## Why the existing drawing tool could not do this

homepage-django already has a capable engine (`assets/js/notebook-drawing/`):
Konva scene graph, `perfect-freehand` pressure strokes, eraser, selection,
shape tools, undo/redo, pointer capture with `e.pressure`.

Its problem is not the tool, it is the **substrate**. Strokes are anchored to
viewport coordinates over reflowing HTML. `stage-manager.js` patches this by
measuring the prose container and shifting every stroke when it moves
horizontally — which cannot survive a rewrap, a font change, or a different
window width. So the marks are good for a session and worthless as notes.

A PDF page does not reflow. Anchor the same strokes to PDF page coordinates and
they become permanent. **This design changes the substrate and keeps the
engine.**

## Scope

**In:** per-section PDFs, freehand pen (pressure), highlighter, eraser,
selection, the shape tools the existing engine has, undo/redo, per-user
persistence, version retention, carry-forward, download of a flattened
annotated PDF.

**Out:** annotating the **full-book PDF** — it stays a plain download. A
118-page document in one canvas viewer is a memory and performance problem on
tablets, and the section is the unit a reader studies. Also out: shared or
collaborative annotation, comment threads, text-selection highlighting bound to
glyphs (this is ink over pages, not semantic markup).

## 1. Ownership

Three parts, because the existing boundaries are worth keeping.

### `parody_web` (core) — versions only, still no JavaScript

Core gains the ability to retain and address PDF *versions*, which is
inherently its business: it owns `print_sha256`, the slice cache, and the print
root. It gains no models about users and no JS.

- Archives each released book PDF (§2).
- Exposes the version *capability* as three functions, and no new URL:

  ```python
  archive_book_pdf(book)                    -> BookPrintVersion   # at import
  slice_key_for(book, section)              -> str                # §2 identity
  versioned_section_pdf(book, book_sha256, pages) -> Path | None  # cut from the archive
  ```

  Core deliberately does **not** grow a `?v=` endpoint. Resolving a
  `slice_key` back to *which* archived book and *which* page range requires the
  `InkLayer` row, and that lives in the annotate app — an endpoint in core
  could not answer its own query. Core supplies the mechanism; the app owns the
  routing.
- `pdf_view.html`'s hardcoded `<iframe>` becomes
  `{% include "parody_web/_pdf_view_stage.html" %}`, with
  `_pdf_view_head.html` and `_pdf_view_toolbar.html` alongside — the same
  shadowing seam as `docs/host-integration.md` §4. Default stage remains
  today's iframe, so a host that installs nothing sees no change.

**Correction to the previous design.** The `.pdf-annotation-layer` div shipped
in `pdf_view.html` is removed. It cannot work: it is a transparent div over an
`<iframe>`, and a page cannot draw onto the browser's PDF plugin nor discover
where its pages are. The stage must be *replaced*, not overlaid.

### `parody_web_annotate` (new app, same distribution) — the annotator

A second Django app shipped in the parody-web distribution and enabled by
adding it to `INSTALLED_APPS`. It owns the per-user models, the endpoints, and
the prebuilt viewer bundle.

This is a deliberate, narrow exception to host-integration §4 ("per-user
overlays are the host's business"). §4's reasoning is that per-user features
depend on enrollment, assignments and due dates that parody-web must not know
about. Ink on a PDF depends on none of that — only a user id and a PDF
parody-web itself produced. Keeping it in the distribution is what makes it
reusable across rtcbook and every course site instead of being rewritten per
host. §4 gets an explicit carve-out saying so.

`example_site/` is **not** the place for it: it is a project skeleton that
hosts copy once (rtcbook-web is such a copy), it is excluded from the wheel by
`include = ["parody_web*"]`, and additions to it reach no existing site.

### The host — configuration only

homepage-django adds the app, sets two settings, and runs migrations. It writes
no annotation code. Its existing `notebook-drawing` bundle stays as it is, for
HTML notebooks.

## 2. Version identity and retention

### Identity: a deterministic content key, not a file hash

A section's version is

```
slice_key = sha256( for each page in range: page content stream bytes + MediaBox )
```

Not the sha256 of the sliced file. Measured: pypdf's writer *is* byte-stable
today — same input, same bytes, no `/ID` or `/CreationDate` — so that is not
the objection. The objection is that a file hash would make every reader's
version key depend on **our writer** rather than on the book. A pypdf upgrade
that changed object ordering or stream compression would silently change every
slice's hash at once, and every annotation on the site would point at a version
that no longer appears to exist. Hashing the *source* pages' content streams
depends only on the PDF parody produced.

It is also the cheaper key: it needs no slice to exist, so the viewer can ask
"is this the version you annotated?" for a section without cutting a PDF first.

Either way it has the property the feature rests on: **a rebuild that does not
touch this section yields the same key, and the reader's notes stay put.**

Repagination *does* change the key, because the printed page number is drawn in
the content stream. That is correct and honest — the page genuinely changed —
and §4's carry-forward exists for it.

### Retention: archive the book PDF, outside the checkout

Slices regenerate, so retention is per *book* PDF: one file per release
(~3 MB), which also makes every historical version reachable rather than only
annotated ones.

```
PARODY_WEB_PRINT_ARCHIVE = "/srv/parody/print-archive"   # NOT inside the repo
```

`<archive>/<book-slug>/<book-sha256>.pdf`, written at import when
`Book.print_sha256` changes.

**It must live outside the deployment checkout.** `deploy_ec2.sh` runs
`git fetch && git reset --hard origin/main` in a persistent `/srv` directory;
an archive under `teaching/notebooks_data/` would survive that but be destroyed
by any future `git clean -fdx`, taking the source PDFs behind every student's
annotations with it. Unset archive = versioning disabled, current version only.

A `BookPrintVersion` row (book, sha256, filename, page_count, first_seen)
records what has been archived, so the store can be listed and pruned.

### Pruning

`prune_print_archive` keeps: the current version of every book, plus every
version referenced by an `InkLayer`. Everything else is removable. Ships as a
management command, run manually — never automatically, because the failure
mode is deleting a student's notes' substrate.

## 3. Data model

One model, in `parody_web_annotate`, deliberately self-sufficient:

```python
class InkLayer(models.Model):
    user        = FK(AUTH_USER_MODEL)
    book_slug   = CharField
    edition_id  = CharField(blank=True)
    section_key = CharField          # Section.key — see host-integration §5
    slice_key   = CharField(64)      # §2 identity
    book_sha256 = CharField(64)      # which archived book PDF it came from
    pages       = JSONField          # [start, end], 1-based inclusive
    strokes     = JSONField          # §4
    created_at / updated_at

    unique_together = (user, book_slug, edition_id, section_key, slice_key)
```

`book_sha256` and `pages` are stored rather than looked up because
`Section.print_pages` is overwritten at every import. Without them, an old
version could not be re-sliced once the book moved on — the record would name a
version it could no longer produce. With them the row can always reconstruct
its own PDF.

Keying on `(book_slug, edition_id, section_key)` rather than a `Section` FK is
deliberate: sections are deleted and recreated on re-import, and a FK would
cascade a student's notes away. This is the join key
`docs/host-integration.md` §5 already prescribes for exactly this reason.

## 4. Strokes and coordinates

Strokes are stored **per page, in PDF points, origin at the page's CropBox
top-left, y increasing downward** (screen convention; the exporter flips to
PDF's y-up at write time, in one place).

```json
{"1": [ {"tool": "pen", "color": "#1a1a1a", "size": 2.5, "opacity": 1.0,
         "points": [[x, y, pressure], ...],
         "d": "M… Q… Z"} ]}
```

Keys are page numbers *within the section slice*, 1-based.

Each stroke carries both its input `points` and `d`, the rendered outline as an
SVG path. `points` is what the eraser, selection and any future re-edit need.
`d` is what the server exports: the client already computes it with
`getSvgPathFromStroke`, and storing it means the export path does not require a
Python reimplementation of `perfect-freehand`. Converting `d`'s `M/L/Q/Z` to
PDF operators is a small, total transform (quadratic → cubic by degree
elevation).

Shape tools (line, rect, ellipse) store their parameters directly and need no
`d`.

## 5. The viewer

`parody_web_annotate` shadows `_pdf_view_stage.html` with a pdf.js viewer.

- **Render:** `pdfjs-dist` draws each page to its own canvas, windowed —
  only pages near the viewport are rendered, and canvases outside it are
  released. This is what keeps an iPad from running out of memory, and it is
  why the full-book PDF is out of scope.
- **Draw:** one Konva stage per page, sized to that page's rendered box. The
  ported engine talks to it through `setPointerTransform()` — a seam
  `pointer-utils.js` **already exposes** for whiteboard pan/zoom, so paged mode
  is a third consumer of an existing interface rather than a new one. The
  transform maps a client point to `(page, x, y)` in PDF points, dividing out
  zoom and device pixel ratio.
- **Replaced:** `stage-manager.js` — the viewport-sized stage, the scroll
  offset, and the prose-offset compensation all go. Everything else
  (`stroke-renderer`, `serialization`, `eraser`, `selection`, `shape-tools`,
  `history`, `keyboard`, `toolbar`) ports with the coordinate space redefined
  beneath it.

### Stylus

- `touch-action: none` on the stage; `setPointerCapture` on the active pointer.
- **Palm rejection:** once a `pointerType === "pen"` event is seen, touch
  pointers stop drawing for the rest of the session and pan/zoom instead. This
  is the behaviour a tablet user expects and it needs no heuristics.
- `getCoalescedEvents()` for the full input sample rate, so fast strokes are
  smooth rather than polygonal.
- `e.pressure` feeds `perfect-freehand`, as the existing engine already does.
  A mouse reports 0.5 and gets a constant-width line.

### Saving

Debounced autosave (the engine already has `SAVE_DEBOUNCE_MS`) `PUT`s the whole
stroke set for the section. Whole-document PUT, not deltas: the payload is
kilobytes of JSON, and it makes the endpoint idempotent and the client simple.
`navigator.sendBeacon` on `pagehide` catches the last edit.

## 6. Versions in the UI

The viewer's bar shows the version only when there is more than one to show:
the current version, plus any version this reader has ink on. Nothing else is
listed — the reader cares about their notes, not the release history.

Opening a section whose current `slice_key` differs from one they have notes on
offers, once: **"You have notes on an earlier version of this section. Bring
them forward?"** Accepting copies the strokes into a new `InkLayer` for the
current key; declining leaves the new version clean. Both versions remain
openable. Never automatic — the page usually only changed its page number, but
when it changed for real, silently moving ink would put it in the wrong place.

Multiple annotated versions are listed newest-first with their date. No further
design: it is a genuine edge case.

## 7. Download

The annotate app owns all versioned routes, since it holds the only mapping
from a `slice_key` to a producible PDF:

```
GET  …/pdf/ink/?v=<slice_key>             the section PDF at that version
GET  …/pdf/annotated/?v=<slice_key>       the same, with ink composited in
GET/PUT …/ink/                            this reader's strokes (JSON)
POST …/ink/carry-forward/                 copy an older version's strokes
```

Omitting `v` means the current version. A `v` the reader has no `InkLayer` for
is a 404, not a guess — core can still slice the current book, but a version it
cannot resolve is one it must not silently substitute.

Server-side, with no new dependency: the strokes are already outlines, so the
exporter emits a PDF content stream of filled paths (`… m`, `… l`, `… c`, `f`)
plus an `ExtGState` for the highlighter's alpha, and merges it onto each page
with pypdf. Doing it server-side rather than in the browser means the annotated
PDF is a real file the reader can mail, print, or keep.

## 8. Access control

The annotated section PDF is exactly as gated as the section PDF: every
endpoint asks `PARODY_WEB_ACCESS_POLICY` the same question `section_pdf`
already asks, before touching ink. Ink itself is private — a reader may only
ever read or write `InkLayer` rows whose `user` is themselves; there is no
sharing surface and no admin read path in this design.

Anonymous readers get the current viewer with no annotation UI at all, not a
disabled one.

## 9. Packaging

The bundle is **prebuilt and committed**: hosts `pip install` the package and
must not need Node. A `npm run build:annotate` step (esbuild, matching
homepage-django's existing setup) produces
`parody_web_annotate/static/parody_web_annotate/js/annotate.js` plus the pdf.js
worker, and both are committed and listed in `pyproject.toml`'s
`package-data` — parody-web ships static assets **only** if they are listed
there, and a missed entry silently produces a wheel with no viewer.

pdf.js and its worker are vendored, pinned, and their licenses recorded.

## 10. Testing

- **Version identity:** the same source produces the same `slice_key` twice;
  editing a *different* section leaves this section's key unchanged; changing
  this section's pages changes it. This is the property everything else rests
  on.
- **Retention:** archive on import; an old `InkLayer` still resolves to a
  sliceable PDF after the book is rebuilt; prune keeps referenced versions.
- **Isolation:** one user cannot read or write another's ink.
- **Gating:** a section the policy refuses yields no PDF, no ink, no viewer.
- **Export:** a known stroke set composites to a PDF whose page count matches
  the slice and which contains the expected fill operators.
- **Degradation:** with the app uninstalled, `pdf_view.html` still renders the
  iframe; with `pypdf` absent, no PDF affordance appears at all.
- Client: the transform (client point → page point) is unit-tested across zoom
  and DPR; palm rejection is unit-tested as a state machine.

## 11. Risks

- **pdf.js is large.** Loaded only on the PDF view, never on section pages.
- **Tablet memory.** Mitigated by windowed rendering and by excluding the
  full-book PDF.
- **The archive only grows.** Bounded by pruning, not eliminated. ~3 MB per
  release per book.
- **Versions before this ships are unrecoverable.** Retention begins at the
  first import after deployment; nothing can archive a PDF that was already
  overwritten.
