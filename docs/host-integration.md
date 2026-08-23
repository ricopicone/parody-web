# Host integration

Serving a parody book from your own Django project.

parody-web renders the book: chapters, sections, cross-references, numbering,
search, the subject index. Your project owns everything about *readers* —
accounts, courses, enrollment, assignments, due dates, annotations. A handful of
seams connect the two, and parody-web never learns what a course is.

The running example is a course site that serves a textbook to a class and
opens each exercise's worked solution once its assignment is due.

## 1. Solutions and problems

A parody artifact can carry per-exercise worked solutions and problem
statements alongside a section's prose. `import_artifact` stores them:

| field | type | contents |
|---|---|---|
| `Section.has_solutions` | `bool` | the artifact's own flag |
| `Section.solutions` | `dict` | `{exercise_id: {"title": str, "content": html}}` |
| `Section.problems` | `dict` | same shape |

```python
section.solution_for("exe:z3-agent")   # -> {"title": ..., "content": ...} | None
section.problem_for("exe:z3-agent")    # -> same, or None
```

Exercise ids come from the source (`exe:z3-agent`) and contain a colon.
Artifacts without these keys — every commercial or `--online-only` artifact —
import as `{}` / `False`, exactly as before.

**Storing is not exposing.** Solution text lands in the database of whatever
deployment imports the artifact; who may *read* it is the access policy's
decision, and parody-web's own answer is "the owner, nobody else".

> **Partial limitation.** Cross-references (`.hashref` spans) inside solution
> and problem content *are* resolved, as of 0.35.0. Bibliography citations
> (`[@key]`) still are not: resolving them also builds the per-section
> References list, and doing that from extracted content would credit a section
> with citations that are not in its prose.

## 2. Access control

One setting names a policy class:

```python
# settings.py
PARODY_WEB_ACCESS_POLICY = "courses.policy.CoursePolicy"
```

Subclass `parody_web.access.DefaultPolicy` and override only the hooks you care
about; anything you leave alone keeps parody-web's behaviour. The dotted path is
validated at startup (`ParodyWebConfig.ready`), so a typo fails on boot rather
than at first render.

| hook | question | default |
|---|---|---|
| `is_owner(request)` | is this the book's owner? | `request.user.is_authenticated` |
| `can_view_section(request, section)` | may they have this page at all? | `True` |
| `section_is_preview(request, section)` | show a teaser instead of the full text? | `section.preview and not is_owner(...)` |
| `can_view_solution(request, section, exercise_id)` | may they read this solution? | `is_owner(...)` |
| `solution_denied_context(request, section, exercise_id)` | what does the refusal page say? | `{"available_after": None, "message": …}` |

### Why two section hooks

Section gating has two distinct modes, and collapsing them would silently turn
previews into denials:

- **`can_view_section`** is the *hard* gate. `False` means the reader may not
  have the page — it 404s. parody-web itself never refuses one (the table of
  contents and the prose are public), hence the `True` default. Override it for
  genuinely restricted material, such as a notebook only enrolled students may
  open.
- **`section_is_preview`** is the *soft* gate: a truncated excerpt plus a
  sign-in call to action. This is `Section.preview` — in print, not fully
  online. The page still renders, and the excerpt still opens with the prose.

### Why `request` and not `user`

Every hook takes the request. `request.user` is always reachable from a request
and the reverse is not, and a policy may want the session or query string. A
policy that only cares about the user starts with `request.user`. `request` may
be `None` on helper paths that have none, so every hook must tolerate it —
`DefaultPolicy.is_owner` does.

### A worked policy

```python
# courses/policy.py
from django.utils import timezone

from parody_web.access import DefaultPolicy

from .models import ChecklistItem, is_enrolled


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

## 3. The solution URL

```
/<chapter_slug>/<section_slug>/solutions/<exercise_id>/     name="parody_web:solution"
```

```python
reverse("parody_web:solution", args=[chapter.slug, section.slug, "exe:z3-agent"])
```

| outcome | response |
|---|---|
| policy permits | `200`, `parody_web/solution.html` |
| policy refuses | `403`, `parody_web/solution_denied.html` with the denial context merged in |
| section has no such solution | `404` |

The refusal still renders a full page, so `available_after` and `message` can
tell the reader when the solution opens. Both templates carry
`<meta name="robots" content="noindex">`, and solution URLs are excluded from
`sitemap.xml`.

`problems` gets no view — hosts read it off the model to build their own
assignment and print pages, which is where problem statements are wanted.

## 4. Per-user overlays

Features that are per-request and per-user — annotations, drawing layers,
editable data tables, an exam entry point — cannot live in the artifact and are
not parody-web's business. Four partials ship empty and are included from
`section.html`; shadow the ones you need through ordinary template resolution:

| partial | position | intended for |
|---|---|---|
| `parody_web/_section_head.html` | inside `head_extra` | overlay CSS and scripts |
| `parody_web/_section_toolbar.html` | under the heading | exam/print entry point |
| `parody_web/_section_foot.html` | after the body, before the pager | editable data tables |
| `parody_web/_section_overlay.html` | end of the page | annotation/drawing layer |

Each receives the full section context: `book`, `chapter`, `section`,
`preview`, `editions`.

```html
{# yourapp/templates/parody_web/_section_overlay.html #}
<div id="annotations" data-section="{{ section.key }}"></div>
<script src="{% static 'courses/annotate.js' %}"></script>
```

### The full-window PDF view

The PDF reader at `…/pdf/view/` has three more, and they work the same way:

| partial | position | intended for |
|---|---|---|
| `parody_web/_pdf_view_head.html` | inside `<head>` | stylesheets and scripts |
| `parody_web/_pdf_view_toolbar.html` | in the top bar | pens, colours, version switcher |
| `parody_web/_pdf_view_stage.html` | the document itself | a replacement viewer |

The stage is a **replacement**, not an overlay. It ships as an `<iframe>` around
the browser's own PDF viewer; shadow it and yours is used instead. It receives
`pdf_url` so it need not know parody-web's URL names.

An earlier design offered a transparent "annotation layer" div on top of that
iframe. It was removed because it cannot work: a page can neither draw onto the
browser's PDF plugin nor discover where its pages are. Anything that draws on a
PDF has to render the PDF itself.

### Annotation is the one per-user feature that ships

Ink on a section PDF is available as `parody_web_annotate`, a second app in
this distribution — add it to `INSTALLED_APPS` and it works.

That is a deliberate exception to the rule above, and a narrow one. The rule
exists because per-user features usually depend on enrollment, assignments and
due dates that parody-web must not know about. Ink depends on none of that:
only a user id, and a PDF parody-web itself produced and can version. Shipping
it here is what makes it available to every book site instead of being
rewritten in each one.

Template `{% block %}`s were deliberately *not* used for this. Django cannot
`{% extends %}` a template it is itself overriding, so a block-based seam would
force you to copy `section.html` wholesale and re-merge it on every parody-web
upgrade. Shadowing a small empty partial costs nothing when the page changes.

## 4b. Annotation (`parody_web_annotate`)

Freehand ink on section PDFs — pressure pen, highlighter, shapes, eraser,
undo — kept per reader and per PDF version. Install it:

```python
# settings.py
INSTALLED_APPS = [
    "parody_web_annotate",   # BEFORE parody_web: it shadows the PDF-view templates
    "parody_web",
    ...
]

# Where released book PDFs are kept so old annotated versions stay producible.
# MUST be outside the deployment checkout — a `git clean` in the checkout would
# take every annotation's source PDF with it.
PARODY_WEB_PRINT_ARCHIVE = "/srv/parody/print-archive"
```

```python
# urls.py — alongside parody_web's, under the same book prefix
path("", include("parody_web_annotate.urls")),
path("", include("parody_web.urls")),
```

Then `manage.py migrate`. The app order is enforced by a system check rather
than left to fail silently.

**What a version is.** A section's version is a hash of its own pages' content
streams, so a rebuild that does not touch the section keeps the same key and
the reader's notes stay attached. When a section really does change, the new
PDF appears and the annotated older one remains openable; the reader is offered
a one-tap carry-forward, never an automatic one.

Retention starts at the first import after installing: nothing can archive a
PDF that was already overwritten. `manage.py prune_print_archive` (dry-run by
default) removes versions that are neither current nor annotated.

**Only sections.** The full-book PDF is deliberately not annotatable — a
118-page canvas viewer is a memory problem on tablets, and a section is the
unit a reader studies.

## 5. The join key

Key your own per-section records to:

```
(book.slug, book.edition_id, section.key)
```

`Section.key` is one value that survives re-import:

```python
@property
def key(self):
    return self.hash or f"{self.chapter.slug}/{self.slug}"
```

The authored short hash when the book has one — it is stable across renames and
reorganization, and parody build-checks it for uniqueness within a book. But
parody emits a section hash *only* when the source authors one in front matter,
and course books generally do not: in the `engineering-artificial-intelligence`
golden artifact, 0 of 43 sections and 0 chapters carry a hash. Keying on
`Section.hash` alone would key every section in such a book to `""`, so `key`
falls back to the always-present chapter/section slug pair.

Use `section.key`, not `section.hash`. `hash` is indexed for lookups.

## 6. Wearing your own chrome

A deployment can replace the book masthead and nav with its own. This is
ordinary Django app-directories resolution — nothing in parody-web special-cases
it. Either list your app before `parody_web`:

```python
INSTALLED_APPS = ["courses", "parody_web", ...]
```

or add a project-level template directory:

```python
TEMPLATES = [{..., "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True}]
```

then shadow `parody_web/base.html` or `parody_web/_masthead.html`. Keep the
blocks `base.html` defines (`title`, `head_extra`, `page_class`, `side`,
`body`, `rail`) so the book pages still render into your layout.

## 7. Serving several books

parody-web began as one deployment per book: `BOOK_SLUG` named it. A course site
serves a shelf, and it has to be *one* process — enrollment, assignments and
annotations live in the one database, and a second process could see none of
them. So point parody-web at a callable that answers "which book is this request
for":

```python
# settings.py
PARODY_WEB_BOOK_RESOLVER = "config.books.resolve_book"
```

```python
# config/books.py
BOOK_SUBDOMAINS = {"electronics": "electronics",
                   "mechatronics": "mechatronics"}

def resolve_book(request):
    """electronics.example.edu -> the "electronics" book."""
    subdomain = request.get_host().split(".")[0].lower()
    return BOOK_SUBDOMAINS.get(subdomain)
```

Returning `None` declines: selection falls through to `BOOK_SLUG`, so a host maps
the hosts it knows about and lets everything else land on a default book. Routing
by subdomain, path prefix, or the signed-in reader's enrollment is your business —
parody-web only asks the question, and the callable receives the whole request.

Selection runs in three steps, most specific first:

1. `PARODY_WEB_BOOK_RESOLVER`, when set and it returns a slug;
2. `BOOK_SLUG`;
3. the only imported book.

Step 3 tolerates any number of *editions* of one book, but several distinct books
with neither setting configured raises `ImproperlyConfigured` rather than serving
an arbitrary one. The path is validated at startup, so a typo fails on boot.

Import each book the usual way — `import_artifact` already imports by slug:

```
python manage.py import_artifact electronics.json
python manage.py import_artifact mechatronics.json
```

Books on one deployment can look different. `PARODY_WEB_THEME` accepts the same
override dict keyed by book slug:

```python
PARODY_WEB_THEME = {
    "electronics":  {"light": {"accent": "#b3261e"}},
    "mechatronics": {"light": {"accent": "#1e5fb3"}},
}
```

`light` and `dark` are the only legal mode names, so a top-level key that is
neither means the dict is keyed by slug. A single-book deployment keeps writing
the plain form; the two cannot be mixed.

Nothing else needs to change. The join key already carries the book
(`(book.slug, book.edition_id, section.key)`), and every access-policy hook
already takes the request — `section.book.slug` tells the books apart.

## 8. Print PDFs

Each section page can offer the PDF of that section — not a separately typeset
copy, but the exact pages cut out of the full-book print PDF, so a student who
prints section by section ends up holding the whole book.

`parody publish` emits the PDF plus a page-map sidecar, and the artifact carries
each section's absolute page range. parody-web slices the range out on demand
and caches it.

```python
# settings.py
PARODY_WEB_PRINT_ROOT = "/var/lib/mysite/print"   # holds <book>.pdf
PARODY_WEB_PRINT_XACCEL = "/print-internal/"      # optional; nginx streams
PARODY_WEB_PUBLIC_BOOK_PDF = True                 # see the warning below
```

Install the extra, or the affordance never renders (by design, not by error):

```
pip install "parody-web[print]"
```

**`PARODY_WEB_PRINT_ROOT` must not live under `MEDIA_ROOT`.** nginx serves the
media tree with no authentication, and the print PDF contains the full text of
every section — including ones an `--online-only` artifact deliberately
withholds. Routing downloads through the view is what preserves that gating.

Two policy hooks decide who gets what:

```python
class CoursePolicy(DefaultPolicy):
    def can_download_section_pdf(self, request, section): ...
    def can_download_book_pdf(self, request, book): ...
```

`can_download_section_pdf` defaults to whatever the page itself shows — a
preview section's PDF is owner-only because the page is.
`can_download_book_pdf` defaults to **public**, gated by
`PARODY_WEB_PUBLIC_BOOK_PDF`. Note the direction: a gated book that forgets to
set it to `False` serves its whole text. parody-web warns about exactly that
combination at startup, but the setting is yours to get right.

### Routes

| route | purpose |
|---|---|
| `<ch>/<sec>/pdf/` | download that section |
| `<ch>/<sec>/pdf/view/` | full-window PDF reader |
| `pdf/` | the whole book |

### The annotation seam

`pdf_view.html` renders the PDF in a positioned container with an empty
sibling:

```html
<div class="pdf-annotation-layer" data-section-key="{{ section.key }}"></div>
```

It ships inert. A host adding drawing or annotation keys its records to that
`data-section-key` — the same join key described in §5 — and shadows the
template to add its own layer and scripts.

## 9. Read-along

`parody_web_readaloud` reads a section aloud over its PDF, highlighting each
word as it is spoken and pausing at each typeset blank so the student writes
the answer in by hand with the annotator's pen. It is additive: without it, or
without generated audio, the PDF view is exactly what it was.

```python
# settings.py — read-along and the annotator BOTH precede parody_web
INSTALLED_APPS = [
    "parody_web_readaloud",
    "parody_web_annotate",
    "parody_web",
]

# Where generated audio lives — a local directory...
PARODY_WEB_READALOUD_CACHE = "/var/lib/mysite/readalong"

# ...or an S3 bucket, which is what a real deployment should use. See below.
PARODY_WEB_READALOUD_BUCKET = "my-bucket"
```

```python
# urls.py — alongside the others, under the same book prefix
path("", include("parody_web_readaloud.urls")),
path("", include("parody_web_annotate.urls")),
path("", include("parody_web.urls")),
```

Install with the extra: `pip install "parody-web[print,readalong]"`. It pulls
`PyMuPDF` (to measure the typeset page) and `boto3` (AWS Polly and S3).
Speaking maths additionally needs **Node on the generating machine**; the IAM
user needs `polly:SynthesizeSpeech`.

`PyMuPDF` and Node are **generation-time** concerns — a host that never
generates still serves whatever tracks it already has. `boto3` used to be one
too, and no longer is: serving audio from a bucket mints a presigned URL per
request. A deployment that sets `PARODY_WEB_READALOUD_BUCKET` without boto3
installed is refused at boot rather than at the first reader's request.

### Where the audio lives

```
PARODY_WEB_READALOUD_BUCKET unset -> files under PARODY_WEB_READALOUD_CACHE
PARODY_WEB_READALOUD_BUCKET set   -> objects under PARODY_WEB_READALOUD_PREFIX
```

**Prefer the bucket.** The audio endpoint asks the access policy exactly the
question `section_pdf` asks, and only then redirects to a short-lived presigned
URL — so gating is unchanged, and **S3 answers HTTP Range**. That last point is
the reason this option exists. Serving audio from Django means hand-rolling
Range: `FileResponse` answers a Range request with 200 and the whole file, so
the browser cannot seek at all, and every seek snaps back to the start. The
local path still does that hand-rolled 206 correctly, and it stays because
`runserver` must need no AWS — but a developer is the only one who should be
touching it.

The bucket is **not** inherited from `AWS_STORAGE_BUCKET_NAME`, on purpose:
writing into a host's media bucket because it happens to have one is a
surprise. Name it. Server-side encryption *is* inherited from `AWS_S3_SSE`,
because a bucket policy that requires it would otherwise reject every upload
with no obvious cause.

Credentials come from `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` when the host
sets them and from boto3's default chain when it does not — which on EC2 means
the instance role. The role needs `s3:GetObject`, `s3:PutObject` and
`s3:ListBucket` on the prefix. Keys are sha256 text keys under the prefix, and
the bucket path must stay private: the presigned URL is the only way in, it is
minted only after the access check, and the redirect carries
`Cache-Control: private, no-store` so a dead one is never re-served from a
cache.

A signed URL dies with the credentials that signed it, which on EC2 is sooner
than its nominal expiry. The player handles that itself: on a media error it
re-fetches the endpoint once (rate-limited), which re-runs the access check,
mints a fresh URL, and restores the reader's position.

### Moving audio you already have

Audio already generated onto local disk is **moved, not re-bought** —
regenerating spends Polly money on recordings that are byte-identical:

```
python manage.py sync_readalong_audio [--dry-run] [--from DIR]
```

It uploads every `ReadAlongTrack`'s file that the bucket does not already hold,
reading from `PARODY_WEB_READALOUD_CACHE` unless `--from` says otherwise, and
leaves the local files alone so the change is reversible. Read the
**`missing from disk`** count: each one is a track that would 404 for a reader
today.

Set the bucket, run the sync, restart. `PARODY_WEB_READALOUD_CACHE` can stay
set — with a bucket configured it is unused for serving, and it is what the
sync reads from.

### Two builds of every section

The published artifact stays `--clozes blank`, unchanged. Read-along
additionally needs a `--clozes key` render of the same source, which is
**never served**: it is the only artifact that carries the answers, marks them
as `<span class="cloze-key">`, and stages the complete figure artwork.

Point `generate_readalong --key-artifact` at that file. Nothing needs importing
and nothing is served from it; it is read at generation time on the machine
doing the generating.

(A host may instead put the HTML on `Section.key_html`, but that field does not
exist and nothing requires it. Without either, `generate_readalong` skips the
section rather than falling back to blank-mode HTML: that has no answers in it,
so it would produce a track whose blanks reveal nothing, and the failure would
surface in front of a student.)

### Generating

```
python manage.py generate_readalong <book_slug> [--section KEY] [--voice Matthew]
                                    [--engine neural|standard] [--skip-math]
                                    [--force] [--dry-run]
```

`--dry-run` reports, per section, whether it would be synthesised and at what
character count or merely re-aligned, without calling Polly. Run it before
committing to a voice: cost scales with characters × voices × re-synthesis, and
not at all with listeners.

### Re-running it after an edit

Just run it again, over the whole book, with no flags. Three things can happen
to a section and only the last costs anything:

| Output  | Meaning                                                    | Cost |
| ------- | ---------------------------------------------------------- | ---- |
| `have`  | same pages, same words — nothing done                       | none |
| `moved` | the section moved on the page; boxes re-derived, mp3 kept   | ~1 s |
| `made`  | the words changed — synthesised                             | Polly |

`moved` is why editing chapter 1 does not re-buy chapter 12. A track has two
identities and they invalidate independently: `slice_key` is the identity of
its **boxes**, and must move whenever the page does, because a reader's ink is
pinned to the same geometry. `text_key` — sha256 of the spoken text, the voice
and the engine — is the identity of its **audio and timings**, and pagination
cannot enter it. Reflow cascades, so a one-word fix early in a book changes the
slice key of nearly every section after it; the text key of none of them.

Reused timings assume a stable parse: same text in, same token indices out.
That holds by construction, since the text key *is* the hash of that text, but
it is checked anyway against the stored token count — a figure cloze is never
spoken, so a token stream can shift underneath identical narration. A
disagreement synthesises rather than places words by an index that has moved.

**`--force` is not the tool for a content edit.** It re-buys every section,
including the ones whose text is untouched, and exists for when the *generator*
changed. To redo one section, name it: `--section <key>`.

Audio files are named from the text key, so two paginations of one section
share one recording rather than storing it twice.

`--no-audio` estimates word timings at reading pace and stores no file, so the
pacing and the reveals can be judged before a voice is chosen or paid for; the
viewer drives itself from a clock. `--key-artifact <path>` takes section text
straight from a `--clozes key` artifact on disk, so **no importer change and no
`Section.key_html` are needed** at all.

Whole-book cost is small: the electronics primer is 144k characters, about
$2.31 on the neural engine and $0.58 on standard.

Readers can skip the rest of a spoken equation with ArrowRight or the button
that appears while one is being read. Clozes are never skippable — their
narration is the answer.

`--skip-math` leaves equations silent. Otherwise maths is spoken through
MathJax's Speech Rule Engine, which needs **Node on the generating machine**
plus two npm packages. speech-rule-engine resolves its own package data
relative to where it is installed, so it cannot be bundled into the wheel —
install it once and point a setting at it:

```
mkdir -p /srv/parody/sre && cd /srv/parody/sre
npm install mathjax-full speech-rule-engine
cp <site-packages>/parody_web_readaloud/static/parody_web_readaloud/js/speak.mjs .
```

```python
PARODY_WEB_READALOUD_SRE = "/srv/parody/sre/speak.mjs"
```

`generate_readalong` checks this before synthesising anything and refuses to
start if maths cannot be spoken. That check earns its keep: the engine treats
every failure as silence, so without it a misconfigured host pays for a whole
book of tracks with every equation missing and is told nothing. Pass
`--skip-math` to accept silent equations deliberately.

### Audio is serve-only

Neither endpoint ever synthesises; a miss is a 404. This is deliberate. Lazy
synthesis is the one path by which an anonymous visitor to a public book could
mint new audio, and the only way cost starts tracking requests instead of
content. Because one synthesis serves every listener, read-along needs no
access tier of its own — it inherits the book's, asking the policy the same
question the section PDF asks.

### Template shadowing

Read-along shadows `parody_web/_pdf_view_head.html` to load its assets, and
that partial is also the annotator's. Django resolves app templates by
`INSTALLED_APPS` order and only the first wins, so read-along's copy re-emits
the annotator's stylesheet link too. A test pins the annotator's version, so
if it ever changes the suite fails rather than the stylesheet silently
vanishing.

## Settings reference

| setting | default | meaning |
|---|---|---|
| `PARODY_WEB_ACCESS_POLICY` | `""` (uses `DefaultPolicy`) | dotted path to the access policy class |
| `PARODY_WEB_BOOK_RESOLVER` | `""` (uses `BOOK_SLUG`) | dotted path to a `callable(request) -> slug` choosing the book per request |
| `PARODY_WEB_THEME` | `{}` | colour and font token overrides; keyed by book slug on a multi-book deployment |
| `BOOK_SLUG` | the only imported book | the book to serve when the resolver declines or is unset |
| `PARODY_WEB_PRINT_ROOT` | `""` (feature off) | directory holding the full-book print PDFs; must NOT be inside `MEDIA_ROOT` |
| `PARODY_WEB_PRINT_CACHE` | `<print root>/.cache` | where sliced section PDFs are cached; must be under the print root when X-Accel is used |
| `PARODY_WEB_PRINT_XACCEL` | `""` (Django streams) | nginx `internal` location mapped to the print root |
| `PARODY_WEB_PUBLIC_BOOK_PDF` | `True` | may the public download the whole book as one PDF; set `False` for any book that gates a section |
| `PARODY_WEB_READALOUD_CACHE` | `""` (feature off) | directory holding generated read-along audio; required to generate or serve it unless a bucket is set |
| `PARODY_WEB_READALOUD_BUCKET` | `""` (uses the cache directory) | S3 bucket holding generated audio; the endpoint redirects to a presigned URL and S3 answers Range natively |
| `PARODY_WEB_READALOUD_PREFIX` | `"readalong/"` | key prefix inside that bucket |
| `PARODY_WEB_READALOUD_REGION` | `AWS_S3_REGION_NAME`, else `us-west-2` | region of that bucket |
| `PARODY_WEB_READALOUD_URL_EXPIRE` | `3600` | seconds a minted audio URL stays valid |
| `PARODY_WEB_READALOUD_SSE` | `AWS_S3_SSE` if set | `ServerSideEncryption` applied on upload |
| `PARODY_WEB_READALOUD_SRE` | `""` (uses the packaged copy) | path to a `speak.mjs` whose npm dependencies resolve; required for spoken maths |
