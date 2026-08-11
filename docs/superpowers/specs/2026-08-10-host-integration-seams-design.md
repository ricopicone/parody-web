# parody-web host-integration seams

Design for task #549. Lets a course site (homepage-django, serving the
Electronics Primer at electronics.ricopic.one) serve books from parody-web
instead of reimplementing notebook views, without parody-web taking on any
knowledge of enrollment, assignments, or due dates.

## Problem

parody-web's access model is commercial publishing: `Section.online_only`,
`Section.preview`, `Book.draft`, with `_is_owner(request)` defined as
`request.user.is_authenticated` (`views.py:50`). A course site needs "can *this*
student see the solution to *this* exercise *yet*", which depends on enrollment,
which assignment the exercise belongs to, and that assignment's due date.

There is no seam for that today — `PARODY_WEB_THEME` is the only settings knob
in the app. Worse, the artifact's per-section `has_solutions` / `solutions` /
`problems` are dropped on import, so the data a course site needs never reaches
the database.

## Non-goals

parody-web never learns what a course, enrollment, assignment, or due date is.
Every such concept stays in the host project and reaches parody-web only through
the policy object described below.

## Seam 1 — carry solutions and problems through import

`Section` gains three fields (migration `0009`):

```python
has_solutions = models.BooleanField(default=False)
solutions = models.JSONField(default=dict, blank=True)
problems  = models.JSONField(default=dict, blank=True)
```

`solutions` and `problems` are both `{exercise_id: {"title": str, "content":
html}}`, matching the artifact. `import_artifact.py` reads them off each section
dict; artifacts without them (every commercial/partial artifact today) import as
`{}` / `False` exactly as before.

Two accessors on `Section` return one entry or `None`:

```python
section.solution_for("exe:z3-agent")  # -> {"title": ..., "content": ...} | None
section.problem_for("exe:z3-agent")
```

This does put solution text into the database of a public deployment. Exposure
is the access policy's job; `DefaultPolicy` keeps solutions owner-only, matching
the existing gating posture.

## Seam 2 — pluggable access control

A new module `parody_web/access.py` defines `DefaultPolicy`, and one setting
names a replacement:

```python
PARODY_WEB_ACCESS_POLICY = "courses.policy.CoursePolicy"
```

The dotted path is resolved by `get_policy()` and validated at startup in
`apps.py`, so a bad path fails on boot rather than at first render — the same
posture as `PARODY_WEB_THEME`.

```python
class DefaultPolicy:
    def is_owner(self, request) -> bool
    def can_view_section(self, request, section) -> bool
    def section_is_preview(self, request, section) -> bool
    def can_view_solution(self, request, section, exercise_id) -> bool
    def solution_denied_context(self, request, section, exercise_id) -> dict
```

Defaults reproduce today's behaviour exactly:

| hook | default |
|---|---|
| `is_owner` | `request.user.is_authenticated` |
| `can_view_section` | `True` |
| `section_is_preview` | `section.preview and not is_owner(request)` |
| `can_view_solution` | `is_owner(request)` |
| `solution_denied_context` | `{"available_after": None, "message": …}` |

### Why two section hooks

Today's section gating has two distinct modes, and collapsing them into a single
bool would silently convert previews into denials:

- `can_view_section` is the **hard** gate. False means the reader may not have
  the page at all — the restricted-notebook case. No current behaviour needs it,
  hence the `True` default; it exists so a host can add one.
- `section_is_preview` is the **soft** gate: the reader gets a truncated excerpt
  plus a sign-in CTA. This is today's `Section.preview`.

### Why `request` rather than `user`

Task #549 sketches these hooks as `(user, section)`. They take `request`
instead: `request.user` is always reachable from a request, the reverse is not,
and every call site in `views.py` already has the request in hand. A host policy
that only cares about the user starts with `request.user`.

### Call sites

`views.py` keeps no inline gating. `_is_owner`, each
`section.preview and not request.user.is_authenticated` expression, and the
`public` context variable all route through the policy. The existing test suite
is the regression net for the default policy being behaviour-preserving.

Draft-edition handling continues to key off `is_owner` rather than gaining its
own hook — no host has asked to redefine "who sees an unreleased edition"
separately from "who is the owner".

## Seam 2b — the solution page

```python
path("<slug:chapter_slug>/<slug:section_slug>/solutions/<str:exercise_id>/",
     views.solution_detail, name="solution")
```

`<str:>` (not `<slug:>`) because exercise ids contain a colon: `exe:z3-agent`.

The view resolves book and section, then:

- no such solution on the section → `Http404`;
- `policy.can_view_solution(...)` true → render `parody_web/solution.html`, with
  the stored content passed through the `render_book` filter exactly as section
  html is;
- false → render `parody_web/solution_denied.html` with
  `policy.solution_denied_context(...)` merged into the context, HTTP **403**.
  The denial page still renders in full, so a host can show "solutions available
  after &lt;due date&gt;" via `available_after`.

Solution URLs are omitted from `sitemap.xml`.

`problems` is stored but gets no view. Hosts read it off the model to build
assignment and print pages, which is where problem statements are wanted.

## Seam 3 — per-user overlay hooks

Four partials ship empty and are included from `section.html`. A host overrides
only the ones it needs through normal Django template resolution, and never
copies `section.html` — so parody-web can keep evolving the page without
breaking host deployments.

| partial | position in `section.html` | intended for |
|---|---|---|
| `_section_head.html` | inside the `head_extra` block | overlay CSS/JS |
| `_section_toolbar.html` | after breadcrumbs and `<h1>` | exam/print entry point |
| `_section_foot.html` | after content, before the pager | editable data tables |
| `_section_overlay.html` | end of the body block | annotations/drawing layer |

Each receives the full `section_detail` context (`book`, `chapter`, `section`,
`preview`, `editions`, …).

Blocks were rejected for this: Django cannot `{% extends %}` a template it is
itself overriding, so a block-based seam forces the host to copy `section.html`
wholesale and re-merge it on every upgrade.

## Seam 4 — stable join key

Host-side records (annotations, per-user data) must key to a section identity
that survives re-import.

`Section.hash` alone does not work. parody emits a section `hash` only when the
source authors one in front matter (`parody/writers/artifact.py:796`). RTC
authors them; course books do not — in the golden artifact
`engineering-artificial-intelligence.json`, 0 of 43 sections and 0 chapters
carry a hash. A host keying on `hash` would key every section to `""`.

`Section` therefore gains a `key` property:

```python
@property
def key(self):
    return self.hash or f"{self.chapter.slug}/{self.slug}"
```

Authored-hash-preferred, because a short hash is stable across renames and
reorganization and is already build-time-checked for uniqueness within a book
(`parody/build.py::_check_duplicate_hashes`); structural fallback, because
`chapter.slug/section.slug` is always present. One value for a host to store.

The documented contract is the triple `(book.slug, book.edition_id,
section.key)`. `Section.hash` gains a DB index for host-side lookups.

## Host chrome

`base.html` and `_masthead.html` override through ordinary app-directories
template resolution: a host app listed before `parody_web` in `INSTALLED_APPS`
(or a project-level `DIRS` entry) shadowing `parody_web/base.html` wears its own
nav and breadcrumbs. This already works; it is documented rather than built.

## Documentation

`docs/host-integration.md` covers all four seams, the settings, the join-key
contract, and template overriding, with a worked `CoursePolicy` example.

## Testing

- import carries `has_solutions` / `solutions` / `problems` onto `Section`, and
  an artifact lacking them still imports;
- `DefaultPolicy` reproduces current behaviour (the existing suite, plus direct
  assertions on each hook);
- a custom policy installed with `override_settings` flips a solution from 403
  to 200, and its `solution_denied_context` reaches the denial template;
- an unknown exercise id 404s; a section with no solutions 404s;
- a host-overridden overlay partial renders into the section page;
- `Section.key` returns the hash when authored and the slug pair when not.

## Release

parody-web 0.34.0. Additive throughout: no existing behaviour changes when
neither new setting is configured. `uv.lock` is committed in the same commit as
the version bump.
