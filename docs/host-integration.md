# Host integration

Serving a parody book from your own Django project.

parody-web renders the book: chapters, sections, cross-references, numbering,
search, the subject index. Your project owns everything about *readers* —
accounts, courses, enrollment, assignments, due dates, annotations. Four seams
connect the two, and parody-web never learns what a course is.

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

> **Known limitation.** Cross-references and citations inside solution and
> problem content are not resolved at import. `number_artifact` rewrites only
> `section["html"]`, so a `[@key]` or a `.hashref` span in a solution body
> renders literally. A host that needs them resolved must run its own pass over
> the content.

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

Template `{% block %}`s were deliberately *not* used for this. Django cannot
`{% extends %}` a template it is itself overriding, so a block-based seam would
force you to copy `section.html` wholesale and re-merge it on every parody-web
upgrade. Shadowing a small empty partial costs nothing when the page changes.

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

## Settings reference

| setting | default | meaning |
|---|---|---|
| `PARODY_WEB_ACCESS_POLICY` | `""` (uses `DefaultPolicy`) | dotted path to the access policy class |
| `PARODY_WEB_THEME` | `{}` | per-book colour and font token overrides |
| `BOOK_SLUG` | first imported book | which book this deployment serves |
