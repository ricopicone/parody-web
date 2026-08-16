# Per-section PDF Annotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reader opens a section's PDF full-window, writes on it with a stylus, and their ink persists per user and per PDF version — with older annotated versions remaining openable after the book is rebuilt.

**Architecture:** `parody_web` (core) gains PDF *version* retention and template seams and stays JavaScript-free. A new app `parody_web_annotate`, shipped in the same distribution and enabled via `INSTALLED_APPS`, owns the per-user model, the endpoints, the PDF exporter, and a prebuilt pdf.js viewer that ports homepage-django's `notebook-drawing` engine from viewport coordinates to PDF page coordinates. Hosts only configure.

**Tech Stack:** Django, pypdf, pdfjs-dist, Konva, perfect-freehand, esbuild, `node --test`.

**Spec:** `docs/superpowers/specs/2026-08-16-pdf-annotation-design.md`

## Global Constraints

- Repo: `~/parody-web-worktrees/pdf-annotate`, branch `pdf-annotate`. **Never `git add -A`** — these trees are shared with concurrent sessions; stage named paths only.
- Tests: `python runtests.py` (Django runner, `tests/settings.py`, in-memory sqlite). JS: `node --test`.
- `pypdf` is an optional extra. Every new code path must degrade to "no affordance" when it is absent, never raise.
- Stroke coordinates are **PDF points, origin at the page CropBox top-left, y increasing downward**. The exporter is the only place that flips to PDF's y-up.
- Page numbers in `pages` and in stroke keys are **1-based inclusive**.
- The annotator applies to **section PDFs only**. The full-book PDF is never annotatable.
- New static assets MUST be added to `pyproject.toml` `[tool.setuptools.package-data]` or the wheel silently ships without them.
- Version bumps must commit **both** `pyproject.toml` and `uv.lock`.

---

### Task 1: Version identity — `slice_key_for`

The property everything rests on: a rebuild that does not touch this section must yield the same key.

**Files:**
- Modify: `parody_web/printing.py`
- Test: `parody_web/tests_printing.py`

**Interfaces:**
- Produces: `slice_key_for(book, section) -> str | None` — 64-char hex, or None when unavailable.

- [ ] **Step 1: Write the failing tests**

```python
class SliceKeyTests(PrintTestCase):
    def test_same_source_gives_same_key(self):
        first = printing.slice_key_for(self.book, self.section)
        second = printing.slice_key_for(self.book, self.section)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_key_is_not_the_file_hash(self):
        """pypdf's output is not byte-stable, so a file hash would drift."""
        key = printing.slice_key_for(self.book, self.section)
        path = printing.section_pdf_path(self.book, self.section)
        import hashlib
        self.assertNotEqual(key, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_different_page_range_gives_different_key(self):
        self.section.print_pages = [2, 3]
        self.section.save()
        other = printing.slice_key_for(self.book, self.section)
        self.section.print_pages = [1, 2]
        self.section.save()
        self.assertNotEqual(other, printing.slice_key_for(self.book, self.section))

    def test_missing_pages_is_none(self):
        self.section.print_pages = None
        self.assertIsNone(printing.slice_key_for(self.book, self.section))
```

- [ ] **Step 2: Run and watch it fail**

Run: `python runtests.py` — Expected: `AttributeError: module 'parody_web.printing' has no attribute 'slice_key_for'`

- [ ] **Step 3: Implement**

```python
def _page_fingerprint(page):
    """Bytes that change when the page's drawing changes, and not otherwise."""
    contents = page.get_contents()
    if contents is None:
        data = b""
    elif hasattr(contents, "get_data"):
        data = contents.get_data()
    else:  # ArrayObject of streams
        data = b"".join(s.get_object().get_data() for s in contents)
    box = page.mediabox
    return data + str([float(v) for v in (box.left, box.bottom,
                                          box.right, box.top)]).encode()


def slice_key_for(book, section):
    """Deterministic identity for this section's pages.

    NOT the sha256 of the sliced file: pypdf's writer is not byte-stable
    (document /ID, metadata), so a file hash would change whenever the slice
    cache was cleared and manufacture phantom versions. Hashing the source
    pages' content streams is stable, needs no slice to exist, and has the
    property the feature depends on — a rebuild that leaves this section alone
    leaves its key alone, so the reader's notes stay put.
    """
    import hashlib
    if not section.print_pages or len(section.print_pages) != 2:
        return None
    src = book_pdf_path(book)
    if src is None:
        return None
    reader = _reader(str(src), src.stat().st_mtime_ns)
    start, end = section.print_pages
    digest = hashlib.sha256()
    for i in range(max(1, start) - 1, min(end, len(reader.pages))):
        digest.update(_page_fingerprint(reader.pages[i]))
    return digest.hexdigest()
```

- [ ] **Step 4: Run and watch it pass** — `python runtests.py`

- [ ] **Step 5: Commit**

```bash
git add parody_web/printing.py parody_web/tests_printing.py
git commit -m "print: a deterministic version key for a section's pages"
```

---

### Task 2: Archive released book PDFs

**Files:**
- Modify: `parody_web/models.py`, `parody_web/printing.py`, `parody_web/management/commands/import_artifact.py:146-148`
- Create: `parody_web/migrations/00XX_bookprintversion.py` (via `makemigrations`)
- Test: `parody_web/tests_printing.py`

**Interfaces:**
- Consumes: `book_pdf_path(book)`.
- Produces: `print_archive_root() -> Path | None`; `archive_book_pdf(book) -> BookPrintVersion | None`; `archived_pdf_path(book_slug, sha256) -> Path | None`; model `BookPrintVersion(book, sha256, filename, page_count, first_seen)`.

- [ ] **Step 1: Write the failing tests**

```python
class ArchiveTests(PrintTestCase):
    def test_import_archives_the_pdf(self):
        with self.settings(PARODY_WEB_PRINT_ARCHIVE=str(self.archive)):
            version = printing.archive_book_pdf(self.book)
        self.assertEqual(version.sha256, self.book.print_sha256)
        self.assertTrue(printing.archived_pdf_path(
            self.book.slug, self.book.print_sha256).is_file())

    def test_archiving_twice_writes_once(self):
        with self.settings(PARODY_WEB_PRINT_ARCHIVE=str(self.archive)):
            first = printing.archive_book_pdf(self.book)
            again = printing.archive_book_pdf(self.book)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(BookPrintVersion.objects.count(), 1)

    def test_no_archive_configured_is_a_no_op(self):
        with self.settings(PARODY_WEB_PRINT_ARCHIVE=""):
            self.assertIsNone(printing.archive_book_pdf(self.book))

    def test_old_version_survives_the_book_being_replaced(self):
        with self.settings(PARODY_WEB_PRINT_ARCHIVE=str(self.archive)):
            old_sha = self.book.print_sha256
            printing.archive_book_pdf(self.book)
            self._write_book_pdf(pages=6)          # a new release lands
            self.book.print_sha256 = "b" * 64
            self.book.save()
            printing.archive_book_pdf(self.book)
            self.assertTrue(printing.archived_pdf_path(self.book.slug, old_sha).is_file())
```

- [ ] **Step 2: Run and watch it fail** — Expected: `AttributeError: … 'archive_book_pdf'`

- [ ] **Step 3: Add the model**

```python
class BookPrintVersion(models.Model):
    """A released book PDF, kept so old annotated sections stay producible.

    The live PDF is overwritten by every deploy. Without a copy here, a reader
    whose notes are on last month's version would have notes on a document
    that no longer exists anywhere.
    """
    book = models.ForeignKey(Book, on_delete=models.CASCADE,
                             related_name="print_versions")
    sha256 = models.CharField(max_length=64)
    filename = models.CharField(max_length=200)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    first_seen = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("book", "sha256")
        indexes = [models.Index(fields=["book", "sha256"])]
```

- [ ] **Step 4: Implement the archive functions**

```python
def print_archive_root():
    """Durable store for released book PDFs, or None when unconfigured.

    MUST be outside the deployment checkout: deploy_ec2.sh runs
    `git reset --hard` in a persistent directory, and a later `git clean -fdx`
    would take every annotated version's source PDF with it.
    """
    value = getattr(settings, "PARODY_WEB_PRINT_ARCHIVE", "")
    return Path(value) if value else None


def archived_pdf_path(book_slug, sha256):
    root = print_archive_root()
    if not root or not sha256:
        return None
    return root / book_slug / f"{sha256}.pdf"


def archive_book_pdf(book):
    """Copy the current book PDF into the archive; idempotent."""
    from .models import BookPrintVersion
    src = book_pdf_path(book)
    dest = archived_pdf_path(book.slug, book.print_sha256)
    if src is None or dest is None:
        return None
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    version, _ = BookPrintVersion.objects.get_or_create(
        book=book, sha256=book.print_sha256,
        defaults={"filename": dest.name,
                  "page_count": len(_reader(str(dest), dest.stat().st_mtime_ns).pages)})
    return version
```

- [ ] **Step 5: Hook it into import** — in `import_artifact.py`, immediately after the `Book` upsert block:

```python
        # Keep this release's PDF before a later deploy overwrites it.
        # Best-effort: a failure here must not fail the import.
        try:
            printing.archive_book_pdf(book)
        except Exception as exc:          # noqa: BLE001
            self.stderr.write(f"print archive skipped: {exc}")
```

- [ ] **Step 6: Make the migration** — `python -m django makemigrations parody_web --settings=tests.settings`

- [ ] **Step 7: Run and watch it pass** — `python runtests.py`

- [ ] **Step 8: Commit**

```bash
git add parody_web/models.py parody_web/printing.py parody_web/migrations \
        parody_web/management/commands/import_artifact.py parody_web/tests_printing.py
git commit -m "print: archive each released book PDF outside the checkout"
```

---

### Task 3: Slice a section out of an archived version

**Files:** Modify `parody_web/printing.py`; test `parody_web/tests_printing.py`

**Interfaces:**
- Produces: `versioned_section_pdf(book, book_sha256, pages, cache_name) -> Path | None`

- [ ] **Step 1: Write the failing test**

```python
def test_slices_an_old_version_after_the_book_moved_on(self):
    with self.settings(PARODY_WEB_PRINT_ARCHIVE=str(self.archive)):
        old_sha = self.book.print_sha256
        printing.archive_book_pdf(self.book)
        self._write_book_pdf(pages=6)            # book replaced on disk
        path = printing.versioned_section_pdf(self.book, old_sha, [1, 2], "s")
    self.assertIsNotNone(path)
    from pypdf import PdfReader
    self.assertEqual(len(PdfReader(str(path)).pages), 2)

def test_unknown_version_is_none(self):
    with self.settings(PARODY_WEB_PRINT_ARCHIVE=str(self.archive)):
        self.assertIsNone(printing.versioned_section_pdf(
            self.book, "f" * 64, [1, 2], "s"))
```

- [ ] **Step 2: Run and watch it fail**

- [ ] **Step 3: Implement**

```python
def versioned_section_pdf(book, book_sha256, pages, cache_name):
    """A section slice cut from an ARCHIVED book version.

    Unlike section_pdf_path this never falls back to the current book: a
    version we cannot produce must 404, not silently serve different pages
    under a key the reader believes is theirs.
    """
    if not pages or len(pages) != 2 or not has_pypdf():
        return None
    src = archived_pdf_path(book.slug, book_sha256)
    if src is None or not src.is_file():
        return None
    cache = print_cache_root()
    if cache is None:
        return None
    start, end = pages
    dest = (cache / book.slug / (book.edition_id or "_")
            / f"v{book_sha256[:12]}" / f"{cache_name}-{start}-{end}.pdf")
    if not dest.is_file():
        slice_pdf(src, dest, start, end)
    return dest
```

- [ ] **Step 4: Run and watch it pass**

- [ ] **Step 5: Commit**

```bash
git add parody_web/printing.py parody_web/tests_printing.py
git commit -m "print: slice a section out of an archived book version"
```

---

### Task 4: Template seams on the PDF view

**Files:**
- Modify: `parody_web/templates/parody_web/pdf_view.html`, `docs/host-integration.md`
- Create: `parody_web/templates/parody_web/_pdf_view_stage.html`, `_pdf_view_head.html`, `_pdf_view_toolbar.html`
- Test: `parody_web/tests_printing.py`

**Interfaces:** Produces three shadowable partials, each receiving `book`, `chapter`, `section`, `pdf_url`.

- [ ] **Step 1: Write the failing tests**

```python
def test_default_stage_is_still_the_iframe(self):
    html = self.client.get(self.view_url).content.decode()
    self.assertIn("<iframe", html)

def test_a_host_can_replace_the_stage(self):
    # shadowing is ordinary template resolution; tests/templates/ precedes the app
    with self.settings(TEMPLATES=self._templates_with_override()):
        html = self.client.get(self.view_url).content.decode()
    self.assertNotIn("<iframe", html)
    self.assertIn("REPLACED-STAGE", html)

def test_the_dead_annotation_layer_is_gone(self):
    """It was a div over an iframe — undrawable, and misleading to keep."""
    html = self.client.get(self.view_url).content.decode()
    self.assertNotIn("pdf-annotation-layer", html)
```

- [ ] **Step 2: Run and watch it fail**

- [ ] **Step 3: Create `_pdf_view_stage.html`**

```html
{% comment %}
The PDF stage. Default: the browser's own PDF viewer in an iframe.

Shadow this template to replace it — parody_web_annotate does, with a pdf.js
canvas viewer it can draw on. It must REPLACE rather than overlay: a page
cannot draw onto the browser's PDF plugin, nor discover where its pages are.
{% endcomment %}
<iframe title="{{ section.title|cut:'`' }} (PDF)"
        src="{{ pdf_url }}?inline=1#view=FitH"></iframe>
```

`_pdf_view_head.html` and `_pdf_view_toolbar.html` ship empty with a comment naming their position, matching the four §4 partials.

- [ ] **Step 4: Rewrite the stage block of `pdf_view.html`**

```html
  <div class="pdf-stage">
    {% include "parody_web/_pdf_view_stage.html" %}
  </div>
```

…and add `{% include "parody_web/_pdf_view_head.html" %}` after the stylesheet links, `{% include "parody_web/_pdf_view_toolbar.html" %}` in the bar before the links, and delete the `.pdf-annotation-layer` div and its CSS rule. Add `pdf_url` to the view's context in `views.py:section_pdf_view`.

- [ ] **Step 5: Run and watch it pass**

- [ ] **Step 6: Document the seam** — add to `docs/host-integration.md` §4 the three new partials, and a carve-out paragraph: ink on a parody-web-produced PDF needs only a user id, not enrollment, so it ships as `parody_web_annotate` rather than being rewritten per host.

- [ ] **Step 7: Commit**

```bash
git add parody_web/templates parody_web/views.py parody_web/tests_printing.py docs/host-integration.md
git commit -m "print: make the PDF stage shadowable; drop the undrawable layer"
```

---

### Task 5: `prune_print_archive`

**Files:** Create `parody_web/management/commands/prune_print_archive.py`; test `parody_web/tests_printing.py`

**Interfaces:** Consumes `BookPrintVersion`, and `InkLayer` **if installed** (imported defensively — core must not depend on the app).

- [ ] **Step 1: Write the failing test**

```python
def test_prune_keeps_current_and_referenced_versions(self):
    ...
    call_command("prune_print_archive", "--yes", stdout=out)
    self.assertTrue(archived_current.is_file())
    self.assertTrue(archived_referenced.is_file())
    self.assertFalse(archived_orphan.is_file())

def test_dry_run_is_the_default(self):
    call_command("prune_print_archive", stdout=out)
    self.assertTrue(archived_orphan.is_file())
    self.assertIn("would remove", out.getvalue())
```

- [ ] **Step 2: Run and watch it fail**

- [ ] **Step 3: Implement** — collect `keep = {every Book.print_sha256} | {InkLayer.book_sha256 …}`; list `BookPrintVersion` rows not in `keep`; require `--yes` to unlink, because the failure mode is destroying the substrate of a student's notes.

```python
def _referenced_shas():
    try:
        from parody_web_annotate.models import InkLayer
    except ImportError:      # annotator not installed; nothing references
        return set()
    return set(InkLayer.objects.values_list("book_sha256", flat=True))
```

- [ ] **Step 4: Run and watch it pass**

- [ ] **Step 5: Commit**

```bash
git add parody_web/management/commands/prune_print_archive.py parody_web/tests_printing.py
git commit -m "print: prune the archive, keeping anything a reader annotated"
```

---

### Task 6: The `parody_web_annotate` app and its model

**Files:**
- Create: `parody_web_annotate/{__init__,apps,models,urls,views}.py`, `migrations/__init__.py`, `tests.py`
- Modify: `pyproject.toml` (`include = ["parody_web*"]` already matches the new package — verify), `tests/settings.py` (add to `INSTALLED_APPS`), `runtests.py` (run both labels)

**Interfaces:** Produces `InkLayer` per spec §3, and `InkLayer.for_reader(user, book, section, slice_key)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_unique_per_user_section_and_version(self):
    InkLayer.objects.create(**self.kw)
    with self.assertRaises(IntegrityError):
        InkLayer.objects.create(**self.kw)

def test_two_versions_of_one_section_coexist(self):
    InkLayer.objects.create(**self.kw)
    InkLayer.objects.create(**{**self.kw, "slice_key": "b" * 64})
    self.assertEqual(InkLayer.objects.count(), 2)

def test_reimport_does_not_delete_ink(self):
    """Sections are recreated on import; a FK would cascade notes away."""
    InkLayer.objects.create(**self.kw)
    self.section.delete()
    self.assertEqual(InkLayer.objects.count(), 1)
```

- [ ] **Step 2: Run and watch it fail**

- [ ] **Step 3: Implement the model** exactly as spec §3, with `strokes = models.JSONField(default=dict)` and the docstring explaining why `book_sha256` and `pages` are stored rather than looked up (`Section.print_pages` is overwritten every import, so without them the row would name a version it can no longer produce).

- [ ] **Step 4: Register the app** in `tests/settings.py` and make `runtests.py` run `["parody_web", "parody_web_annotate"]`.

- [ ] **Step 5: makemigrations, run, watch pass**

- [ ] **Step 6: Commit**

```bash
git add parody_web_annotate tests/settings.py runtests.py pyproject.toml
git commit -m "annotate: the app and its per-reader, per-version ink layer"
```

---

### Task 7: Ink read/write endpoints

**Files:** Modify `parody_web_annotate/{views,urls}.py`; test `parody_web_annotate/tests.py`

**Interfaces:** Produces `GET/PUT <chapter>/<section>/ink/` (JSON), name `parody_web_annotate:ink`.

- [ ] **Step 1: Write the failing tests**

```python
def test_put_then_get_round_trips(self):
    self.client.force_login(self.reader)
    body = {"slice_key": "a"*64, "book_sha256": "b"*64, "pages": [1, 2],
            "strokes": {"1": [{"tool": "pen", "color": "#000", "size": 2,
                               "opacity": 1, "points": [[1, 2, 0.5]], "d": "M1 2"}]}}
    self.assertEqual(self.client.put(self.url, body, "application/json").status_code, 200)
    got = self.client.get(self.url, {"v": "a"*64}).json()
    self.assertEqual(got["strokes"]["1"][0]["tool"], "pen")

def test_a_reader_cannot_see_another_readers_ink(self):
    InkLayer.objects.create(user=self.other, **self.kw)
    self.client.force_login(self.reader)
    self.assertEqual(self.client.get(self.url, {"v": self.kw["slice_key"]}).json()["strokes"], {})

def test_a_reader_cannot_overwrite_another_readers_ink(self):
    layer = InkLayer.objects.create(user=self.other, **self.kw)
    self.client.force_login(self.reader)
    self.client.put(self.url, {**self.body, "strokes": {}}, "application/json")
    layer.refresh_from_db()
    self.assertNotEqual(layer.strokes, {})

def test_anonymous_cannot_write(self):
    self.assertIn(self.client.put(self.url, self.body, "application/json").status_code, (302, 403))

def test_a_gated_section_yields_no_ink(self):
    with self.settings(PARODY_WEB_ACCESS_POLICY="parody_web_annotate.tests.DenyAll"):
        self.assertEqual(self.client.get(self.url, {"v": "a"*64}).status_code, 404)
```

- [ ] **Step 2: Run and watch it fail**

- [ ] **Step 3: Implement.** Both verbs resolve `book`/`section` the way `views.section_pdf` does, ask the access policy the identical question first, then filter `InkLayer` by `user=request.user` — always, so isolation is structural rather than a check that can be forgotten. PUT replaces the whole stroke set (idempotent; the payload is kilobytes).

- [ ] **Step 4: Run and watch it pass**

- [ ] **Step 5: Commit**

```bash
git add parody_web_annotate
git commit -m "annotate: read and write a reader's own ink, gated like the PDF"
```

---

### Task 8: Versioned PDF and carry-forward

**Files:** Modify `parody_web_annotate/{views,urls}.py`; test `parody_web_annotate/tests.py`

**Interfaces:** `GET …/pdf/ink/?v=`, `POST …/ink/carry-forward/`, and `versions_for(request, book, section) -> list[dict]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_current_version_needs_no_v(self):
    self.assertEqual(self.client.get(self.pdf_url).status_code, 200)

def test_an_old_version_is_served_from_the_archive(self):
    # book replaced on disk; the reader's old version still resolves
    self.assertEqual(self.client.get(self.pdf_url, {"v": old_key}).status_code, 200)

def test_a_version_the_reader_has_no_ink_for_is_404(self):
    self.assertEqual(self.client.get(self.pdf_url, {"v": "f"*64}).status_code, 404)

def test_carry_forward_copies_strokes_and_keeps_the_old_layer(self):
    self.client.post(self.carry_url, {"from": old_key, "to": new_key},
                     content_type="application/json")
    self.assertEqual(InkLayer.objects.count(), 2)
    self.assertEqual(InkLayer.objects.get(slice_key=new_key).strokes,
                     InkLayer.objects.get(slice_key=old_key).strokes)

def test_carry_forward_will_not_clobber_existing_work(self):
    InkLayer.objects.create(user=self.reader, **{**self.kw, "slice_key": new_key,
                                                 "strokes": {"1": ["mine"]}})
    self.assertEqual(self.client.post(self.carry_url, ...).status_code, 409)
```

- [ ] **Step 2: Run and watch it fail**

- [ ] **Step 3: Implement.** `versions_for` returns the current `slice_key_for(...)` plus every `InkLayer.slice_key` this reader holds, newest first, each with `{key, current, updated_at}` — nothing else, because the reader cares about their notes rather than the release history. Carry-forward is a copy, never a move, and refuses with 409 rather than overwriting.

- [ ] **Step 4: Run and watch it pass**

- [ ] **Step 5: Commit**

```bash
git add parody_web_annotate
git commit -m "annotate: serve an older version, and offer to bring notes forward"
```

---

### Task 9: The exporter — ink composited into a real PDF

**Files:** Create `parody_web_annotate/export.py`; modify `views.py`, `urls.py`; test `parody_web_annotate/tests_export.py`

**Interfaces:** `svg_path_to_pdf_ops(d, page_height) -> str`; `composite(src_path, strokes, dest_path) -> None`; `GET …/pdf/annotated/?v=`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_quadratic_becomes_a_cubic(self):
    ops = export.svg_path_to_pdf_ops("M0 0 Q10 0 10 10 Z", page_height=100)
    self.assertIn(" c", ops)          # PDF has no quadratic operator
    self.assertNotIn("Q", ops)

def test_y_is_flipped_once(self):
    ops = export.svg_path_to_pdf_ops("M0 10 L0 20", page_height=100)
    self.assertIn("0 90 m", ops)      # screen y=10 -> PDF y=90
    self.assertIn("0 80 l", ops)

def test_composite_keeps_the_page_count_and_adds_the_fill(self):
    export.composite(self.slice_path, {"1": [self.stroke]}, self.out)
    from pypdf import PdfReader
    self.assertEqual(len(PdfReader(str(self.out)).pages), 2)
    self.assertIn(b" f", self._content_of(self.out, 0))

def test_a_page_with_no_strokes_is_untouched(self):
    export.composite(self.slice_path, {"2": [self.stroke]}, self.out)
    self.assertEqual(self._content_of(self.out, 0), self._content_of(self.slice_path, 0))
```

- [ ] **Step 2: Run and watch it fail**

- [ ] **Step 3: Implement.** No new dependency: `perfect-freehand` already gave us an outline, so a stroke is a filled polygon. Parse `d`'s `M/L/Q/C/Z`, flip y once (`y' = page_height - y`), emit `m`/`l`/`c`/`h` + `f`, elevating each quadratic to a cubic:

```python
# Q(p0, q, p1) == C(p0, p0 + 2/3(q - p0), p1 + 2/3(q - p1), p1)
c1 = (p0[0] + 2/3*(q[0]-p0[0]), p0[1] + 2/3*(q[1]-p0[1]))
c2 = (p1[0] + 2/3*(q[0]-p1[0]), p1[1] + 2/3*(q[1]-p1[1]))
```

Highlighter alpha needs an `ExtGState` resource (`/ca`) added to the page's resource dictionary. Merge by appending a content stream to each annotated page, wrapped in `q`/`Q` so it cannot leak graphics state into the page it is drawn over.

- [ ] **Step 4: Run and watch it pass**

- [ ] **Step 5: Commit**

```bash
git add parody_web_annotate/export.py parody_web_annotate/tests_export.py parody_web_annotate/views.py parody_web_annotate/urls.py
git commit -m "annotate: composite ink into a downloadable, printable PDF"
```

---

### Task 10: JS build and the paged coordinate transform

**Files:**
- Create: `package.json`, `esbuild.config.cjs`, `assets/annotate/paged.js`, `assets/annotate/paged.test.js`
- Modify: `.gitignore` (do NOT ignore the built bundle — it ships)

**Interfaces:** Produces `pagedTransform({pageEl, page, viewport, dpr}) -> (event) => {page, x, y, pressure}` and `screenToPdf(x, y, viewport)`.

- [ ] **Step 1: Write the failing test** (`node --test assets/annotate/paged.test.js`)

```js
test('a click at the page origin maps to PDF 0,0', () => {
  const t = screenToPdf(0, 0, {scale: 1, rotation: 0, height: 792});
  assert.deepEqual(t, {x: 0, y: 0});
});

test('zoom divides out', () => {
  assert.deepEqual(screenToPdf(200, 100, {scale: 2, rotation: 0, height: 792}),
                   {x: 100, y: 50});
});

test('device pixel ratio never reaches PDF space', () => {
  // the transform takes CSS pixels; DPR belongs to the canvas backing store
  assert.deepEqual(screenToPdf(100, 100, {scale: 1, rotation: 0, height: 792}),
                   {x: 100, y: 100});
});
```

- [ ] **Step 2: Run and watch it fail** — `node --test assets/annotate/`

- [ ] **Step 3: Implement `paged.js`** — pure functions only, no DOM, so they stay testable without a browser.

- [ ] **Step 4: Add the build**

```json
{ "scripts": { "build:annotate": "node esbuild.config.cjs" },
  "dependencies": { "pdfjs-dist": "^4.10.38", "konva": "^10.2.0",
                    "perfect-freehand": "^1.2.3" } }
```

esbuild bundles `assets/annotate/index.js` → `parody_web_annotate/static/parody_web_annotate/js/annotate.js`, and copies the pdf.js worker beside it. **Both are committed**: hosts `pip install` and must never need Node.

- [ ] **Step 5: Run and watch it pass**

- [ ] **Step 6: Commit**

```bash
git add package.json esbuild.config.cjs assets/annotate .gitignore
git commit -m "annotate: the paged coordinate transform, and a build for it"
```

---

### Task 11: The viewer — pdf.js pages, ported engine, stylus

**Files:**
- Create: `assets/annotate/{index,pages,ink,toolbar,api}.js`, ported `assets/annotate/engine/*.js`
- Create: `parody_web_annotate/templates/parody_web/_pdf_view_stage.html`, `_pdf_view_head.html`, `_pdf_view_toolbar.html`
- Create: `parody_web_annotate/static/parody_web_annotate/css/annotate.css`
- Test: `assets/annotate/palm.test.js`

**Interfaces:** Consumes `pagedTransform`, the ink endpoints, `versions_for`.

- [ ] **Step 1: Write the failing palm-rejection test**

```js
test('once a pen is seen, touch stops drawing for the session', () => {
  const g = new PointerGate();
  assert.equal(g.shouldDraw({pointerType: 'touch'}), true);
  g.note({pointerType: 'pen'});
  assert.equal(g.shouldDraw({pointerType: 'touch'}), false);
  assert.equal(g.shouldDraw({pointerType: 'pen'}), true);
});
```

- [ ] **Step 2: Run and watch it fail**

- [ ] **Step 3: Port the engine.** Copy `assets/js/notebook-drawing/{stroke-renderer,serialization,eraser,selection,shape-tools,history,keyboard,toolbar,state,constants,pointer-utils}.js` from `~/homepage-django` into `assets/annotate/engine/`. **Replace `stage-manager.js` only** — one Konva stage per page instead of one viewport stage with a scroll offset and prose-offset compensation. Register the paged transform through the existing seam:

```js
import { setPointerTransform } from './engine/pointer-utils.js';
setPointerTransform(pagedTransform(currentPage));
```

Serialization changes shape: strokes are grouped by page number and carry `d`.

- [ ] **Step 4: Render pages, windowed** — `pdfjs-dist` renders only pages near the viewport and releases canvases outside it. This is what keeps an iPad alive, and why the full-book PDF is out of scope.

- [ ] **Step 5: Stylus** — `touch-action: none`, `setPointerCapture`, `getCoalescedEvents()`, and `PointerGate` for palm rejection.

- [ ] **Step 6: Shadow the stage template** — render the toolbar, the canvas host, and the version switcher (only when more than one version exists); load the bundle from `_pdf_view_head.html`. Anonymous readers get no annotation UI at all.

- [ ] **Step 7: Build, run both suites, watch pass** — `npm run build:annotate && node --test assets/annotate/ && python runtests.py`

- [ ] **Step 8: Commit**

```bash
git add assets/annotate parody_web_annotate/templates parody_web_annotate/static
git commit -m "annotate: pdf.js viewer with the drawing engine on paged coordinates"
```

---

### Task 12: Package and release

**Files:** Modify `pyproject.toml`, `uv.lock`, `README.md`

- [ ] **Step 1: Add the static assets to `package-data`** — `parody_web_annotate = ["templates/parody_web/*.html", "static/parody_web_annotate/js/*.js", "static/parody_web_annotate/css/*.css"]`. Omitting this ships a wheel with no viewer and no error.

- [ ] **Step 2: Verify the wheel actually contains them**

```bash
uv build && unzip -l dist/*.whl | grep -E "annotate.*(js|css|html)"
```

- [ ] **Step 3: Bump the version** in `pyproject.toml` **and** `uv.lock`, re-deriving it against `origin/main` at merge time rather than plan time.

- [ ] **Step 4: Document** the app in `README.md` and `docs/host-integration.md`: `INSTALLED_APPS`, `PARODY_WEB_PRINT_ARCHIVE`, the URL include, and `migrate`.

- [ ] **Step 5: Commit and publish** — push `pdf-annotate:main`, `uv build`, `uvx twine upload dist/*`.

---

### Task 13: Configure the host and deploy

**Files:** Modify `~/homepage-django/{config/settings.py,requirements.txt,config/book_urls.py}`

- [ ] **Step 1: Wait for PyPI** — measured from the upload, 10+ minutes. The box's edge lags your own; a ~6-minute gap has failed twice.

- [ ] **Step 2: Configure** — add `parody_web_annotate` to `INSTALLED_APPS`, set `PARODY_WEB_PRINT_ARCHIVE = "/srv/parody/print-archive"` (outside the checkout), include the app's URLs in the book URLconf, and pin the new parody-web exactly in `requirements.txt`.

- [ ] **Step 3: Ensure the archive directory exists on the box** — add a `mkdir -p` to `scripts/deploy_ec2.sh` before `migrate`, owned by the app user.

- [ ] **Step 4: Deploy** — commit, push `main`, watch `deploy-ec2.yml`. The deploy runs `migrate` and `import_books`, and the import archives the current PDF (spec §11: versions from before this ships are unrecoverable).

- [ ] **Step 5: Verify live** — open a section's PDF view on electronics.ricopic.one, draw with a pointer, reload and confirm the ink returns, download the annotated PDF and confirm the marks are in it.
