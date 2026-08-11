# Serving more than one book from a single parody-web deployment

Task #557. Blocks migrating homepage-django's remaining six notebooks (me-345 #541).

## The limit

Book selection is process-global, not per-request:

```python
def _book_slug():
    s = getattr(settings, "BOOK_SLUG", "")
    if s:
        return s
    book = Book.objects.first()
    ...
```

`_book_slug()` takes no argument, and `_resolve_book(request)` calls
`_editions(_book_slug())`. One Django process therefore serves exactly one book,
whatever the request asks for. `docs/host-integration.md` says so outright:
`BOOK_SLUG` — "which book this deployment serves".

homepage-django runs every notebook from a single deployment, routing subdomains
with django-hosts (`analysis.`, `movies.`, and now `electronics.`). A second book
would otherwise need a second Django process, which defeats the point: course
integration depends on sharing the database and the session.

## What already works in our favour

- **Editions are already request-aware.** `_resolve_book(request)` selects an
  edition from `?ed=<id>`, so per-request *book* resolution extends an existing
  shape rather than introducing a new one.
- **The join key already includes the book** — `(book.slug, book.edition_id,
  section.key)`. Host-side records are unaffected.
- **The access policy is already request-aware.** Every hook takes `request`, and
  `CoursePolicy._notebook_section()` in homepage already keys on
  `section.book.slug`.
- **Every existing caller of `_book_slug()` already holds a `request`** —
  `_resolve_book`, `_resolve_code`, `sitemap_xml`. `robots_txt` never called it.
  So threading the request through is a signature change and nothing more.

The change is confined to book *selection* (and, because it becomes visible at
the same moment, theme selection).

## Decisions

### Shape: a resolver hook

Considered three shapes:

1. **Host-keyed mapping** — `BOOK_SLUG` accepts a dict of host → slug. Zero host
   code, but routes by `Host` header only.
2. **A resolver hook** — a dotted path to a callable taking `request` and
   returning a slug, sibling to `PARODY_WEB_ACCESS_POLICY`. **Chosen.** Composes
   with the seams added in 0.34.0, leaves single-book deployments untouched, and
   lets a host route by subdomain, path prefix or anything else.
3. **URL prefix** — mount each book under `/<book-slug>/`. Simplest inside
   parody-web, but changes every URL and breaks the printed short codes `go/`
   resolves.

### Theme follows the book

`PARODY_WEB_THEME` is also process-global. Once seven books share a process they
would all wear one tint, so the same task makes the theme per-book. Deferring it
would land six visually identical notebooks.

### Ambiguity fails loudly

Today's last-resort fallback is `Book.objects.first()`. With several distinct
slugs imported and nothing configured, that silently serves an arbitrary book —
a failure mode this task creates. It becomes an `ImproperlyConfigured` naming the
slugs found.

## Design

### 1. Book selection — `parody_web/books.py` (new)

```python
PARODY_WEB_BOOK_RESOLVER = "config.books.resolve_book"   # callable(request) -> slug | None
```

- `validate_resolver(path)` — raises `ImproperlyConfigured` unless the path names
  an importable callable. Called from `apps.ready()`, the same posture as
  `validate_theme` / `validate_policy`: a typo fails on boot, not at first
  render.
- `get_resolver()` — resolved per call, not cached at import, so
  `override_settings` takes effect in tests.
- `resolve_slug(request)` — the ladder:

  1. the configured resolver, if set and it returns a non-empty slug for this
     request;
  2. `settings.BOOK_SLUG`, if set — **rtcbook.org's path, unchanged**;
  3. the only imported book's slug.

  Step 3 counts *distinct* slugs. One slug, however many editions → serve it,
  exactly as today. Two or more → `ImproperlyConfigured` listing them. No book at
  all → `Http404("no book imported")`, as today.

A resolver returning `None` falls through to step 2 deliberately: a host maps the
subdomains it knows about and lets everything else land on the deployment's
default book.

### 2. Views

`_book_slug()` → `_book_slug(request=None)`, delegating to `resolve_slug`. The
three call sites pass the `request` they already hold. Nothing else in the view
layer changes: `_resolve_book` filters editions by the resolved slug, and every
query is already scoped by `book`.

### 3. Theme — `parody_web/theme.py`, `templatetags/parody_web.py`

`PARODY_WEB_THEME` gains a second accepted shape:

```python
# single book (unchanged)
PARODY_WEB_THEME = {"light": {"accent": "#b3261e"}}

# several books, keyed by slug
PARODY_WEB_THEME = {
    "electronics":  {"light": {"accent": "#b3261e"}},
    "mechatronics": {"light": {"accent": "#1e5fb3"}},
}
```

The discriminator is the top-level key: `light` and `dark` are the only legal
mode names and are already validated, so any other key means the dict is keyed by
slug. Mixing the two forms is an `ImproperlyConfigured`.

`theme_css` becomes `takes_context=True` and selects by `context["book"].slug`.
All nine templates extending `base.html` are rendered with `book` in context, so
there is no gap; no book in context emits no overrides. `validate_theme` recurses
one level for the keyed form, so a bad token under book #4 still fails at boot.

### 4. Host wiring — homepage-django

- `config/books.py` — `BOOK_SUBDOMAINS = {"electronics": "electronics"}`,
  `resolve_book(request)` keying on the leftmost host label, and `host_pattern()`
  regenerating the django-hosts regex from the map's keys.
- `config/electronics_urls.py` → `config/book_urls.py`; docstring generalized,
  content otherwise unchanged.
- `config/hosts.py` — the `electronics` entry becomes the generated alternation,
  `name="books"`. Any `host="electronics"` reverse is updated with it.
- `settings.py` — add `PARODY_WEB_BOOK_RESOLVER`; **keep** `BOOK_SLUG =
  "electronics"` as the ladder's step 2, so a resolver miss still lands somewhere
  sane. Drop the "parody-web serves ONE book" comment, which stops being true.

Adding notebooks 2–7 under #541 then costs one `BOOK_SUBDOMAINS` entry and one
import each.

### 5. Documentation

`docs/host-integration.md` gains a seventh section, "Serving several books", and
the settings-reference table gains `PARODY_WEB_BOOK_RESOLVER`. The `BOOK_SLUG`
row stops saying "which book this deployment serves".

## Compatibility

rtcbook.org must keep working unchanged, in both its forms: `BOOK_SLUG` as a
plain string, and the no-setting fallback to the only imported `Book`. Both are
steps on the ladder, and every existing single-book test must pass untouched —
that is the regression contract.

`import_artifact` already imports by slug and needs no change; a deployment
simply imports several books.

## Testing

parody-web:

- `MultiBookTests` — two books imported, a resolver keyed on the host; index,
  section, sitemap and short-code resolution each follow the request.
- Ladder precedence: resolver wins over `BOOK_SLUG`; a resolver returning `None`
  falls through to `BOOK_SLUG`; `BOOK_SLUG` wins over the single-book fallback.
- Ambiguity: two distinct slugs and nothing configured raises.
- Validation: a bad `PARODY_WEB_BOOK_RESOLVER` path fails at `apps.ready()`.
- Theme: keyed form selects by book; plain form still applies; mixed form raises.
- Every existing single-book test passes unchanged.

homepage-django: a subdomain-routing test asserting `electronics.` reaches the
book and resolves to the `electronics` slug.

## Out of scope

Migrating the six remaining notebooks (#541). This task delivers the capability
and wires the one book that exists.
