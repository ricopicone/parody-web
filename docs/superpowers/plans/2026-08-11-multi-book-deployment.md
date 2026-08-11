# Multi-Book Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One parody-web Django process serves several books, choosing per request, so homepage-django can host every notebook subdomain from a single deployment.

**Architecture:** A new `parody_web/books.py` owns book selection behind a three-step ladder — a host-supplied resolver callable (`PARODY_WEB_BOOK_RESOLVER`, dotted path, validated at boot like the theme and access-policy seams), then `BOOK_SLUG`, then the only imported book. `views._book_slug()` takes the `request` its three callers already hold. `PARODY_WEB_THEME` gains a slug-keyed form so books on one deployment can look different. homepage-django then routes book subdomains through one generalized URLconf driven by a `BOOK_SUBDOMAINS` map.

**Tech Stack:** Python 3, Django, django-hosts (homepage side only), stdlib `unittest`/Django `TestCase`, `uv`, PyPI.

## Global Constraints

- **rtcbook.org must keep working unchanged.** Both existing selection paths survive verbatim: `BOOK_SLUG` as a plain string, and the no-setting fallback to the only imported `Book`. **Every existing test in `parody_web/tests.py` must pass untouched** — do not edit an existing test to accommodate new code.
- Two repos are involved and they are **shared working trees with concurrent agent sessions**. parody-web work happens in the worktree `/Users/picone/parody-web-worktrees/multi-book` (branch `multi-book`). **Never run `git add -A` or `git commit -a`** — always `git add` the exact paths listed in the task.
- Test command for parody-web, run from the worktree root: `uv run python runtests.py`
- Version bumps must change **both** `pyproject.toml` and `uv.lock` in the same commit (`uv lock` regenerates the lock).
- The parody-web version is **re-derived at merge time**, not now: `origin/main` moves under concurrent sessions. At the time of writing it is `0.35.0`, so this ships as `0.36.0` unless main has moved.
- Settings validated at startup follow the existing posture in `parody_web/apps.py`: raise `django.core.exceptions.ImproperlyConfigured` with a message naming the setting and the offending value.
- Match the surrounding code's voice: module docstrings explain *why* the seam exists, comments explain non-obvious choices, no comment restates the code.

---

## File Structure

**parody-web** (worktree `/Users/picone/parody-web-worktrees/multi-book`):

| File | Responsibility |
|---|---|
| `parody_web/books.py` (create) | Book selection: validate + import the resolver, run the three-step ladder. |
| `parody_web/apps.py` (modify) | Boot-time validation of `PARODY_WEB_BOOK_RESOLVER`. |
| `parody_web/views.py` (modify) | `_book_slug(request=None)` delegating to `books.resolve_slug`; three call sites pass their request. |
| `parody_web/theme.py` (modify) | Accept the slug-keyed `PARODY_WEB_THEME` form; validate it. |
| `parody_web/templatetags/parody_web.py` (modify) | `theme_css` becomes context-aware and selects by the rendered book. |
| `parody_web/tests.py` (modify, append) | New test classes; existing classes untouched. |
| `docs/host-integration.md` (modify) | Section 7 "Serving several books" + settings-reference rows. |
| `pyproject.toml`, `uv.lock` (modify) | Version bump. |

**homepage-django** (`/Users/picone/homepage-django`, branch created in Task 7):

| File | Responsibility |
|---|---|
| `config/books.py` (create) | `BOOK_SUBDOMAINS` map, `resolve_book(request)`, `host_pattern()`. |
| `config/book_urls.py` (rename from `config/electronics_urls.py`) | The URL space for any book subdomain. |
| `config/hosts.py` (modify) | One generated host entry for every book subdomain. |
| `config/settings.py` (modify) | `PARODY_WEB_BOOK_RESOLVER`; keep `BOOK_SLUG`; fix the stale comment. |
| `teaching/tests_parody_web.py` (modify, append) | Subdomain-routing test. |

---

### Task 1: The selection ladder

**Files:**
- Create: `parody_web/books.py`
- Test: `parody_web/tests.py` (append a new class at end of file)

**Interfaces:**
- Consumes: `parody_web.models.Book`; Django `settings`, `ImproperlyConfigured`, `Http404`, `import_string`.
- Produces:
  - `validate_resolver(path: str) -> None` — raises `ImproperlyConfigured` unless `path` is falsy or names an importable callable.
  - `get_resolver()` — returns the configured callable, or `None` when unset.
  - `resolve_slug(request=None) -> str` — the ladder. Raises `Http404("no book imported")` when nothing is imported, `ImproperlyConfigured` when several distinct slugs exist with nothing configured.

- [ ] **Step 1: Write the failing tests**

Append to the end of `parody_web/tests.py`:

A dotted path has to name something importable, so the test resolvers are
module-level functions rather than closures:

```python
def resolve_to_book_a(request):
    return "book-a"


def resolve_to_nothing(request):
    return None


def resolve_by_host(request):
    return request.get_host().split(".")[0]


NOT_CALLABLE = "a string, not a callable"


class BookResolverTests(TestCase):
    """Which book a request is for: resolver, then BOOK_SLUG, then the only
    imported book."""

    def test_single_book_fallback_unchanged(self):
        _import("book-a")
        self.assertEqual(resolve_slug(None), "book-a")

    def test_book_slug_setting_wins_over_fallback(self):
        _import("book-a")
        _import("book-b")
        with override_settings(BOOK_SLUG="book-b"):
            self.assertEqual(resolve_slug(None), "book-b")

    def test_resolver_wins_over_book_slug(self):
        _import("book-a")
        _import("book-b")
        with override_settings(
                BOOK_SLUG="book-b",
                PARODY_WEB_BOOK_RESOLVER="parody_web.tests.resolve_to_book_a"):
            self.assertEqual(resolve_slug(None), "book-a")

    def test_resolver_returning_none_falls_through_to_book_slug(self):
        _import("book-a")
        _import("book-b")
        with override_settings(
                BOOK_SLUG="book-b",
                PARODY_WEB_BOOK_RESOLVER="parody_web.tests.resolve_to_nothing"):
            self.assertEqual(resolve_slug(None), "book-b")

    def test_resolver_reads_the_request(self):
        _import("book-a")
        _import("book-b")
        request = RequestFactory().get("/", HTTP_HOST="book-b.example.com")
        with override_settings(
                PARODY_WEB_BOOK_RESOLVER="parody_web.tests.resolve_by_host"):
            self.assertEqual(resolve_slug(request), "book-b")

    def test_several_books_and_nothing_configured_raises(self):
        _import("book-a")
        _import("book-b")
        with self.assertRaises(ImproperlyConfigured) as cm:
            resolve_slug(None)
        message = str(cm.exception)
        self.assertIn("book-a", message)
        self.assertIn("book-b", message)

    def test_no_book_imported_is_404(self):
        with self.assertRaises(Http404):
            resolve_slug(None)

    def test_editions_of_one_book_are_not_ambiguous(self):
        _import("book-a")
        Book.objects.create(slug="book-a", title="Book A", edition_id="2",
                            edition_order=2)
        self.assertEqual(resolve_slug(None), "book-a")

    def test_bad_resolver_path_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_resolver("parody_web.tests.no_such_resolver")

    def test_non_callable_resolver_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_resolver("parody_web.tests.NOT_CALLABLE")

    def test_non_string_resolver_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_resolver(resolve_to_book_a)

    def test_empty_resolver_path_is_fine(self):
        validate_resolver("")
```

Add to the imports at the top of `parody_web/tests.py` (keep them alphabetical
within the existing `from parody_web...` block):

```python
from django.http import Http404

from parody_web.books import resolve_slug, validate_resolver
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python runtests.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'parody_web.books'`

- [ ] **Step 3: Write the implementation**

Create `parody_web/books.py`:

```python
"""Which book a request is for.

parody-web began as one deployment per book: `BOOK_SLUG` named it, and with no
setting the only imported book won by default. A course site serves a shelf —
every notebook on one Django process, routed by subdomain — because enrollment,
assignments and annotations all live in the one database, and a second process
could see none of them.

So selection moves behind a hook, alongside PARODY_WEB_ACCESS_POLICY:

    PARODY_WEB_BOOK_RESOLVER = "config.books.resolve_book"

The callable takes the *request* and returns a slug, or None to decline — a host
maps the subdomains it knows about and lets anything else fall through to the
deployment's default book. Routing by subdomain, path prefix or anything else is
the host's business; parody-web only asks the question.

The setting is validated at startup (see apps.py) so a typo'd path fails on boot
rather than at first render — the same posture as PARODY_WEB_THEME.

See docs/host-integration.md for the full contract.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404
from django.utils.module_loading import import_string

from .models import Book


def validate_resolver(path):
    """Raise ImproperlyConfigured unless `path` names an importable callable."""
    if not path:
        return
    if not isinstance(path, str):
        raise ImproperlyConfigured(
            f"PARODY_WEB_BOOK_RESOLVER must be a dotted path string, "
            f"got {type(path).__name__}")
    try:
        resolver = import_string(path)
    except ImportError as e:
        raise ImproperlyConfigured(
            f"PARODY_WEB_BOOK_RESOLVER: could not import {path!r}: {e}")
    if not callable(resolver):
        raise ImproperlyConfigured(
            f"PARODY_WEB_BOOK_RESOLVER: {path!r} is not callable")


def get_resolver():
    """The configured resolver callable, or None when unset.

    Resolved per call rather than cached at import, so override_settings takes
    effect in tests — the same reasoning as access.get_policy.
    """
    path = getattr(settings, "PARODY_WEB_BOOK_RESOLVER", "")
    if not path:
        return None
    validate_resolver(path)
    return import_string(path)


def resolve_slug(request=None):
    """The slug of the book this request is for.

    Three steps, most specific first: the host's resolver, then BOOK_SLUG, then
    the only imported book. The last two are how single-book deployments have
    always worked and are unchanged.
    """
    resolver = get_resolver()
    if resolver is not None:
        slug = resolver(request)
        if slug:
            return slug
    slug = getattr(settings, "BOOK_SLUG", "")
    if slug:
        return slug
    slugs = sorted(Book.objects.values_list("slug", flat=True).distinct())
    if not slugs:
        raise Http404("no book imported")
    if len(slugs) > 1:
        # Editions of one book are fine — several *books* are not: picking one
        # arbitrarily would serve the wrong book rather than fail.
        raise ImproperlyConfigured(
            f"several books are imported ({', '.join(slugs)}) but neither "
            f"PARODY_WEB_BOOK_RESOLVER nor BOOK_SLUG says which to serve")
    return slugs[0]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python runtests.py`
Expected: PASS — every test, including all pre-existing ones.

- [ ] **Step 5: Commit**

```bash
git add parody_web/books.py parody_web/tests.py
git commit -m "books: resolve the book per request behind a host hook (task #557)"
```

---

### Task 2: Validate the resolver at boot

**Files:**
- Modify: `parody_web/apps.py:9-17`
- Test: `parody_web/tests.py` (append to `BookResolverTests`)

**Interfaces:**
- Consumes: `books.validate_resolver` from Task 1.
- Produces: nothing new; `ParodyWebConfig.ready()` now also rejects a malformed `PARODY_WEB_BOOK_RESOLVER`.

- [ ] **Step 1: Write the failing test**

Append this method to `BookResolverTests` in `parody_web/tests.py`:

```python
    def test_ready_rejects_a_bad_resolver_path(self):
        from django.apps import apps as django_apps
        config = django_apps.get_app_config("parody_web")
        with override_settings(
                PARODY_WEB_BOOK_RESOLVER="nowhere.at.all"):
            with self.assertRaises(ImproperlyConfigured):
                config.ready()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python runtests.py parody_web.tests.BookResolverTests.test_ready_rejects_a_bad_resolver_path`

If `runtests.py` does not accept a test label, run `uv run python runtests.py` and read the failure.
Expected: FAIL — `ready()` does not raise.

- [ ] **Step 3: Write the implementation**

In `parody_web/apps.py`, replace the body of `ready`:

```python
    def ready(self):
        # Fail on a malformed PARODY_WEB_THEME, PARODY_WEB_ACCESS_POLICY or
        # PARODY_WEB_BOOK_RESOLVER at startup rather than silently dropping it
        # at first render.
        from django.conf import settings

        from .access import validate_policy
        from .books import validate_resolver
        from .theme import validate_theme
        validate_theme(getattr(settings, "PARODY_WEB_THEME", None))
        validate_policy(getattr(settings, "PARODY_WEB_ACCESS_POLICY", ""))
        validate_resolver(getattr(settings, "PARODY_WEB_BOOK_RESOLVER", ""))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python runtests.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add parody_web/apps.py parody_web/tests.py
git commit -m "apps: reject a malformed PARODY_WEB_BOOK_RESOLVER at boot (task #557)"
```

---

### Task 3: Views select per request

**Files:**
- Modify: `parody_web/views.py:34-43` (`_book_slug`), `:63`, `:142`, `:428`
- Test: `parody_web/tests.py` (append a new class)

**Interfaces:**
- Consumes: `books.resolve_slug` from Task 1.
- Produces: `views._book_slug(request=None) -> str`. `_resolve_book`, `_resolve_code` and `sitemap_xml` pass the request they already hold.

- [ ] **Step 1: Write the failing tests**

Append to the end of `parody_web/tests.py`:

```python
@override_settings(PARODY_WEB_BOOK_RESOLVER="parody_web.tests.resolve_by_host")
class MultiBookTests(TestCase):
    """Two books on one deployment, chosen by the request's host. Every page
    that reaches for a book has to follow the request, not the process."""

    def setUp(self):
        _import("book-a")
        _import("book-b")
        Book.objects.filter(slug="book-a").update(title="Book A")
        Book.objects.filter(slug="book-b").update(title="Book B")

    def test_index_serves_the_requested_book(self):
        a = self.client.get("/", HTTP_HOST="book-a.example.com")
        b = self.client.get("/", HTTP_HOST="book-b.example.com")
        self.assertContains(a, "Book A")
        self.assertNotContains(a, "Book B")
        self.assertContains(b, "Book B")
        self.assertNotContains(b, "Book A")

    def test_section_belongs_to_the_requested_book(self):
        r = self.client.get("/hardware/specific-t1/", HTTP_HOST="book-b.example.com")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["book"].slug, "book-b")

    def test_sitemap_covers_only_the_requested_book(self):
        r = self.client.get("/sitemap.xml", HTTP_HOST="book-a.example.com")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("book-a.example.com/hardware/specific-t1/", body)
        self.assertNotIn("book-b", body)

    def test_short_code_resolves_within_the_requested_book(self):
        # 'ef' is the specific-t1 section hash in both books; the redirect must
        # come from the book the host asked for.
        r = self.client.get("/ef", HTTP_HOST="book-b.example.com")
        self.assertEqual(r.status_code, 302)
        target = r["Location"]
        self.assertIn("/hardware/specific-t1/", target)
        page = self.client.get(target, HTTP_HOST="book-b.example.com")
        self.assertEqual(page.context["book"].slug, "book-b")

    def test_unmapped_host_with_no_book_slug_raises(self):
        # resolve_by_host returns "unknown"; no such book exists, so there is
        # nothing to serve.
        r = self.client.get("/", HTTP_HOST="unknown.example.com")
        self.assertEqual(r.status_code, 404)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python runtests.py`
Expected: FAIL — the views still resolve one process-global book, so `book-b.example.com` serves Book A (or raises `ImproperlyConfigured` from Task 1's ambiguity guard).

- [ ] **Step 3: Write the implementation**

In `parody_web/views.py`, replace `_book_slug` (lines 34–43) with:

```python
def _book_slug(request=None):
    """The slug of the book this *request* is for — the host's resolver, else
    BOOK_SLUG, else the only imported book (see books.resolve_slug)."""
    return resolve_slug(request)
```

Add the import beside the existing `from .access import get_policy`:

```python
from .books import resolve_slug
```

Delete the now-unused `Book` import only if nothing else in the module uses it —
check first; `Book` is likely still referenced.

Then pass the request at the three call sites:

- line 63, in `_resolve_book`: `everything = _editions(_book_slug(request))`
- line 142, in `_resolve_code`: `editions = [b for b in _editions(_book_slug(request)) if owner or not b.draft]`
- line 428, in `sitemap_xml`: `editions = [b for b in _editions(_book_slug(request)) if not b.draft]`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python runtests.py`
Expected: PASS — including every pre-existing single-book test.

- [ ] **Step 5: Verify no call site was missed**

Run: `grep -n "_book_slug()" parody_web/views.py`
Expected: no output (every call now passes a request).

- [ ] **Step 6: Commit**

```bash
git add parody_web/views.py parody_web/tests.py
git commit -m "views: select the book per request (task #557)"
```

---

### Task 4: Per-book theme

**Files:**
- Modify: `parody_web/theme.py:46-77`
- Modify: `parody_web/templatetags/parody_web.py:179-186`
- Test: `parody_web/tests.py` (append a new class)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `theme.is_keyed(theme) -> bool` — True when the dict is keyed by book slug rather than by mode.
  - `theme.theme_for(theme, slug) -> dict` — the mode dict for one book (`{}` when there is nothing for it).
  - `theme.validate_theme(theme)` — now accepts both forms.
  - `theme.theme_css(theme, slug=None)` — selects by slug when the setting is keyed.

- [ ] **Step 1: Write the failing tests**

Append to the end of `parody_web/tests.py`:

```python
class PerBookThemeTests(TestCase):
    """One deployment, several books, one tint each. Today's plain form — a
    dict of light/dark — keeps working untouched."""

    def setUp(self):
        _import("book-a")
        _import("book-b")

    def test_plain_form_still_applies(self):
        css = theme_css({"light": {"accent": "#b3261e"}}, "book-a")
        self.assertIn(":root{--accent:#b3261e;}", css)

    def test_keyed_form_selects_by_slug(self):
        theme = {"book-a": {"light": {"accent": "#b3261e"}},
                 "book-b": {"light": {"accent": "#1e5fb3"}}}
        self.assertIn("--accent:#b3261e", theme_css(theme, "book-a"))
        self.assertIn("--accent:#1e5fb3", theme_css(theme, "book-b"))

    def test_keyed_form_with_no_entry_emits_nothing(self):
        theme = {"book-a": {"light": {"accent": "#b3261e"}}}
        self.assertEqual(theme_css(theme, "book-b"), "")

    def test_keyed_form_with_no_slug_emits_nothing(self):
        theme = {"book-a": {"light": {"accent": "#b3261e"}}}
        self.assertEqual(theme_css(theme, None), "")

    def test_keyed_form_validates_each_book(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_theme({"book-a": {"light": {"accent": "#b3261e"}},
                            "book-b": {"light": {"background-image": "url(x)"}}})

    def test_mixed_form_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_theme({"light": {"accent": "#b3261e"},
                            "book-b": {"light": {"accent": "#1e5fb3"}}})

    @override_settings(
        PARODY_WEB_BOOK_RESOLVER="parody_web.tests.resolve_by_host",
        PARODY_WEB_THEME={"book-a": {"light": {"accent": "#b3261e"}},
                          "book-b": {"light": {"accent": "#1e5fb3"}}})
    def test_each_book_gets_its_own_tint_on_the_page(self):
        a = self.client.get("/", HTTP_HOST="book-a.example.com").content.decode()
        b = self.client.get("/", HTTP_HOST="book-b.example.com").content.decode()
        self.assertIn("--accent:#b3261e", a)
        self.assertNotIn("--accent:#1e5fb3", a)
        self.assertIn("--accent:#1e5fb3", b)
        self.assertNotIn("--accent:#b3261e", b)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python runtests.py`
Expected: FAIL — `theme_css()` takes 1 positional argument.

- [ ] **Step 3: Write the implementation**

In `parody_web/theme.py`, extend the module docstring after the existing example:

```
A deployment serving several books keys the same dict by book slug instead:

    PARODY_WEB_THEME = {"electronics":  {"light": {"accent": "#b3261e"}},
                        "mechatronics": {"light": {"accent": "#1e5fb3"}}}

``light`` and ``dark`` are the only legal mode names, so a top-level key that is
neither means the dict is keyed by slug. The two forms cannot be mixed.
```

Then replace `validate_theme` and `theme_css` with:

```python
def is_keyed(theme):
    """Whether `theme` is keyed by book slug rather than by light/dark mode."""
    return bool(theme) and isinstance(theme, dict) and not (set(theme) & set(_MODES))


def _validate_modes(theme, where):
    """Validate one book's worth of overrides: a dict of light/dark → tokens."""
    for mode, tokens in theme.items():
        if mode not in _MODES:
            raise ImproperlyConfigured(
                f"PARODY_WEB_THEME{where}: unknown mode {mode!r} "
                f"(expected light/dark)")
        if not isinstance(tokens, dict):
            raise ImproperlyConfigured(
                f"PARODY_WEB_THEME{where}[{mode!r}] must be a dict")
        for token, value in tokens.items():
            if token not in ALLOWED_THEME_TOKENS:
                raise ImproperlyConfigured(
                    f"PARODY_WEB_THEME: {token!r} is not an overridable token "
                    f"(allowed: {', '.join(sorted(ALLOWED_THEME_TOKENS))})")
            _check_value(token, value)


def validate_theme(theme):
    """Raise ImproperlyConfigured unless `theme` is a well-formed override dict,
    in either the single-book or the slug-keyed form."""
    if not theme:
        return
    if not isinstance(theme, dict):
        raise ImproperlyConfigured("PARODY_WEB_THEME must be a dict")
    if not is_keyed(theme):
        # a mode key present: the single-book form, and every key must be one
        _validate_modes(theme, "")
        return
    for slug, book_theme in theme.items():
        if not isinstance(book_theme, dict):
            raise ImproperlyConfigured(
                f"PARODY_WEB_THEME[{slug!r}] must be a dict")
        if is_keyed(book_theme):
            raise ImproperlyConfigured(
                f"PARODY_WEB_THEME[{slug!r}] has no light/dark modes — the "
                f"per-book and single-book forms cannot be mixed")
        _validate_modes(book_theme, f"[{slug!r}]")


def theme_for(theme, slug):
    """One book's overrides: `theme` itself in the single-book form, else the
    entry for `slug` (empty when the setting names no theme for it)."""
    if not theme:
        return {}
    if not is_keyed(theme):
        return theme
    return theme.get(slug) or {}


def theme_css(theme, slug=None):
    """CSS overriding the default tokens, or "" when nothing is configured."""
    validate_theme(theme)
    theme = theme_for(theme, slug)
    if not theme:
        return ""
    out = []
    for mode, selector in _MODES.items():
        tokens = theme.get(mode) or {}
        if tokens:
            decls = "".join(f"--{k}:{v};" for k, v in sorted(tokens.items()))
            out.append(f"{selector}{{{decls}}}")
    return "".join(out)
```

Note `_MODES` is `{"light": ..., "dark": ...}`; `set(_MODES)` is `{"light", "dark"}`.

In `parody_web/templatetags/parody_web.py`, replace `theme_css`:

```python
@register.simple_tag(takes_context=True)
def theme_css(context):
    """Token overrides (settings.PARODY_WEB_THEME) as CSS, for the book on the
    page — a deployment serving several books tints each one separately.

    A tag rather than a context processor: parody-web is an installable app and
    must not require every consuming project to edit its TEMPLATES setting."""
    from ..theme import theme_css as _css
    book = context.get("book")
    return mark_safe(_css(getattr(settings, "PARODY_WEB_THEME", None),
                          getattr(book, "slug", None)))
```

`{% theme_css %}` in `base.html` needs no change — `takes_context` is invisible
at the call site.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python runtests.py`
Expected: PASS — including the pre-existing `ThemeSettingTests`, which calls
`theme_css(...)` with one argument and must still work.

- [ ] **Step 5: Commit**

```bash
git add parody_web/theme.py parody_web/templatetags/parody_web.py parody_web/tests.py
git commit -m "theme: a tint per book on a multi-book deployment (task #557)"
```

---

### Task 5: Document the seam

**Files:**
- Modify: `docs/host-integration.md` — the intro's "Four seams" line, a new section 7, the settings-reference table.

**Interfaces:**
- Consumes: the settings from Tasks 1–4.
- Produces: the host-facing contract Task 7 implements against.

- [ ] **Step 1: Update the intro**

In `docs/host-integration.md`, the intro says "Four seams connect the two".
Change that sentence to:

```
accounts, courses, enrollment, assignments, due dates, annotations. A handful of
seams connect the two, and parody-web never learns what a course is.
```

- [ ] **Step 2: Add section 7**

Insert after section 6 ("Wearing your own chrome") and before "## Settings
reference":

````markdown
## 7. Serving several books

parody-web began as one deployment per book: `BOOK_SLUG` named it. A course site
serves a shelf, and it has to be *one* process — enrollment, assignments and
annotations live in the one database, and a second process could see none of
them. So point parody-web at a callable that answers "which book is this
request for":

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
by subdomain, path prefix, or the signed-in reader's enrolment is your business —
parody-web only asks the question, and the callable receives the whole request.

Selection runs in three steps, most specific first:

1. `PARODY_WEB_BOOK_RESOLVER`, when set and it returns a slug;
2. `BOOK_SLUG`;
3. the only imported book.

Step 3 tolerates any number of *editions* of one book, but several distinct books
with neither setting configured raises `ImproperlyConfigured` at request time
rather than serving an arbitrary one.

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
already takes the request — `section.book.slug` tells them apart.
````

- [ ] **Step 3: Update the settings reference**

Replace the settings-reference table with:

```markdown
| setting | default | meaning |
|---|---|---|
| `PARODY_WEB_ACCESS_POLICY` | `""` (uses `DefaultPolicy`) | dotted path to the access policy class |
| `PARODY_WEB_BOOK_RESOLVER` | `""` (uses `BOOK_SLUG`) | dotted path to a `callable(request) -> slug` choosing the book per request |
| `PARODY_WEB_THEME` | `{}` | colour and font token overrides; keyed by book slug on a multi-book deployment |
| `BOOK_SLUG` | the only imported book | the book to serve when the resolver declines or is unset |
```

- [ ] **Step 4: Check the doc reads correctly**

Run: `grep -n "which book this deployment serves" docs/host-integration.md`
Expected: no output — the stale phrasing is gone.

- [ ] **Step 5: Commit**

```bash
git add docs/host-integration.md
git commit -m "docs: serving several books from one deployment (task #557)"
```

---

### Task 6: Release parody-web

**Files:**
- Modify: `pyproject.toml` (version), `uv.lock`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: a published parody-web release Task 7 depends on.

- [ ] **Step 1: Re-derive the version against main**

```bash
git fetch origin && git log --oneline -1 origin/main && grep -n '^version' pyproject.toml
```

Read the version on `origin/main` **now** — concurrent sessions ship releases
while this work is in flight. This is a feature release, so bump the minor of
whatever `origin/main` currently carries (0.35.0 → 0.36.0 at the time of
writing).

- [ ] **Step 2: Rebase onto main and run the suite**

```bash
git rebase origin/main && uv run python runtests.py
```

Expected: PASS. Resolve any conflict in favour of keeping both sides' behaviour.

- [ ] **Step 3: Bump the version in both files**

Edit `version = "..."` in `pyproject.toml`, then:

```bash
uv lock
```

`uv.lock` pins the project's own version; a bump that touches only
`pyproject.toml` leaves the lock stale.

- [ ] **Step 4: Commit the bump**

```bash
git add pyproject.toml uv.lock
git commit -m "0.36.0: serve several books from one deployment (task #557)"
```

Use the version actually derived in Step 1 in both the version fields and the
commit subject.

- [ ] **Step 5: Verify the diff is only this work**

```bash
git diff --stat origin/main
```

Expected: only `parody_web/books.py`, `parody_web/apps.py`, `parody_web/views.py`,
`parody_web/theme.py`, `parody_web/templatetags/parody_web.py`,
`parody_web/tests.py`, `docs/host-integration.md`, `docs/superpowers/**`,
`pyproject.toml`, `uv.lock`. Anything else is another session's work swept in —
stop and unstage it.

- [ ] **Step 6: Push to main and publish**

```bash
git push origin multi-book:main
```

Then build and publish the wheel to PyPI following the repo's usual release step
(`uv build && uv publish`), and confirm the new version appears on PyPI before
Task 7's deploy.

---

### Task 7: Wire homepage-django

**Files:**
- Create: `config/books.py`
- Rename: `config/electronics_urls.py` → `config/book_urls.py`
- Modify: `config/hosts.py:37-40`, `config/settings.py:249-254`
- Test: `teaching/tests_parody_web.py` (append)

**Interfaces:**
- Consumes: `PARODY_WEB_BOOK_RESOLVER` from Task 1, published in Task 6.
- Produces:
  - `config.books.BOOK_SUBDOMAINS: dict[str, str]` — subdomain → book slug.
  - `config.books.resolve_book(request) -> str | None`.
  - `config.books.host_pattern() -> str` — the django-hosts regex for every book subdomain.

- [ ] **Step 1: Branch**

Work in `/Users/picone/homepage-django`. Create a branch first — this repo is
also shared with concurrent sessions:

```bash
git fetch origin && git checkout -b multi-book origin/main
```

- [ ] **Step 2: Write the failing test**

Append to `teaching/tests_parody_web.py`:

```python
class BookSubdomainRoutingTests(TestCase):
    """Every book subdomain reaches parody-web through one URLconf, and the
    resolver tells parody-web which book the request is for."""

    def test_resolve_book_maps_the_subdomain(self):
        from config.books import resolve_book
        request = RequestFactory().get("/", HTTP_HOST="electronics.ricopic.one")
        self.assertEqual(resolve_book(request), "electronics")

    def test_resolve_book_is_case_insensitive(self):
        from config.books import resolve_book
        request = RequestFactory().get("/", HTTP_HOST="Electronics.ricopic.one")
        self.assertEqual(resolve_book(request), "electronics")

    def test_resolve_book_declines_an_unmapped_host(self):
        from config.books import resolve_book
        request = RequestFactory().get("/", HTTP_HOST="www.ricopic.one")
        self.assertIsNone(resolve_book(request))

    def test_host_pattern_covers_every_book_subdomain(self):
        import re
        from config.books import BOOK_SUBDOMAINS, host_pattern
        pattern = re.compile(host_pattern())
        for subdomain in BOOK_SUBDOMAINS:
            self.assertTrue(pattern.fullmatch(subdomain), subdomain)
        self.assertFalse(pattern.fullmatch("www"))

    def test_settings_point_parody_web_at_the_resolver(self):
        from django.conf import settings
        self.assertEqual(settings.PARODY_WEB_BOOK_RESOLVER,
                         "config.books.resolve_book")
```

Add `RequestFactory` to the `django.test` import at the top of the file if it is
not already imported.

- [ ] **Step 3: Run the test to verify it fails**

Run the repo's usual test command for this module — check `Procfile`/CI or the
repo README for the runner; with the standard Django layout it is:

```bash
python manage.py test teaching.tests_parody_web.BookSubdomainRoutingTests
```

Expected: FAIL — `ModuleNotFoundError: No module named 'config.books'`

- [ ] **Step 4: Create `config/books.py`**

```python
"""Which book each notebook subdomain serves.

Every notebook runs from this one deployment — enrollment, assignments,
annotations and the session all live in this database, and a standalone
parody-web instance could see none of them. parody-web asks *us* which book a
request is for (PARODY_WEB_BOOK_RESOLVER), so the map below is the single place
a new notebook is registered: one entry here, one artifact import, done.
"""

#: subdomain -> parody book slug
BOOK_SUBDOMAINS = {
    "electronics": "electronics",
}


def resolve_book(request):
    """The book for this request, or None to let parody-web fall back.

    Returning None matters: the main site and every non-book subdomain reach
    parody-web's helper paths too, and they should not be told a book they have
    no business serving.
    """
    subdomain = request.get_host().split(".")[0].lower()
    return BOOK_SUBDOMAINS.get(subdomain)


def host_pattern():
    """The django-hosts regex matching every book subdomain."""
    return "|".join(sorted(BOOK_SUBDOMAINS))
```

- [ ] **Step 5: Rename the URLconf**

```bash
git mv config/electronics_urls.py config/book_urls.py
```

Replace the module docstring's first two paragraphs with:

```python
"""URLconf for every book subdomain — the notebooks, via parody-web.

One module serves them all: which book a request is for is settled by
config.books.resolve_book (PARODY_WEB_BOOK_RESOLVER), not by the URLconf, so a
new notebook needs a BOOK_SUBDOMAINS entry and nothing here.

django-hosts points a subdomain at a URLconf *module*, and pointing it straight
at `parody_web.urls` leaves the `parody_web` namespace unregistered: that module
declares `app_name`, and a namespace only comes into being through `include()`.
Every book template reverses `parody_web:section`, so without this wrapper every
page 500s with NoReverseMatch.
```

Leave the rest of the docstring and the whole body unchanged.

- [ ] **Step 6: Update `config/hosts.py`**

Replace the `electronics` host entry (and its comment) with:

```python
    # The notebooks — served by parody-web from this same deployment, so
    # enrollment, assignment due dates and annotations all still apply. A
    # standalone parody-web instance could not see any of them. One URLconf for
    # every book: config.books.resolve_book tells parody-web which book the
    # request is for. config.book_urls, not parody_web.urls directly: the
    # namespace the book templates reverse only exists via include().
    host(book_host_pattern(), 'config.book_urls', name='books'),
```

and add to the imports at the top:

```python
from config.books import host_pattern as book_host_pattern
```

- [ ] **Step 7: Find and fix any reverse that named the old host**

```bash
grep -rn "electronics_urls\|host=\"electronics\"\|host='electronics'\|'electronics'\s*%}" --include=*.py --include=*.html . | grep -v .claude-worktrees
```

Update every hit: `host_url` reverses that named `electronics` now name `books`.
`django_hosts.reverse` with `host="books"` needs the subdomain as a host arg —
check each call site and pass `host_args=["electronics"]` where the old entry
had no argument. If a hit is a plain absolute URL string rather than a reverse,
leave it.

- [ ] **Step 8: Update `config/settings.py`**

Replace the parody-web block's comment and add the setting:

```python
# --- parody-web (book rendering for notebook subdomains) -------------------
# Which book a request is for. parody-web asks this callable per request, so one
# process serves every notebook subdomain; config/books.py holds the map.
PARODY_WEB_BOOK_RESOLVER = "config.books.resolve_book"

# Where a request that the resolver declines lands — the helper paths that reach
# parody-web off a book subdomain.
BOOK_SLUG = "electronics"
```

Leave the `PARODY_WEB_ACCESS_POLICY` block below it exactly as it is.

- [ ] **Step 9: Run the tests**

```bash
python manage.py test teaching
```

Expected: PASS, including the pre-existing parody-web tests in this repo.

- [ ] **Step 10: Check the app boots and the subdomain still renders**

```bash
python manage.py check
```

Expected: no issues. `check` also runs `AppConfig.ready()`, so a bad
`PARODY_WEB_BOOK_RESOLVER` path fails here.

- [ ] **Step 11: Commit**

```bash
git add config/books.py config/book_urls.py config/hosts.py config/settings.py teaching/tests_parody_web.py
git commit -m "feat(books): route every notebook subdomain through one parody-web URLconf"
```

Include any file touched by Step 7 in the `git add` list. Run `git status --short`
first and confirm nothing unrelated is staged.

- [ ] **Step 12: Merge and deploy**

```bash
git push origin multi-book:main
```

Then deploy with the repo's usual release step (`scripts/release.sh` or
`scripts/deploy_ec2.sh` — check which one the last deploy used in the git log)
and pin the deployed parody-web to the version published in Task 6.

- [ ] **Step 13: Verify production**

Fetch `https://electronics.ricopic.one/` and one section page. Expected: 200, the
Electronics Primer's content, styling intact. Confirm `https://ricopic.one/` and
the other subdomains still resolve.

---

## Verification

Before calling this done:

- `uv run python runtests.py` passes in the parody-web worktree, with no existing
  test modified (`git diff origin/main -- parody_web/tests.py` shows additions
  only).
- `python manage.py test teaching` passes in homepage-django.
- The new parody-web version is on PyPI.
- `https://electronics.ricopic.one/` serves the Electronics Primer over HTTPS,
  and `https://ricopic.one/` is unaffected.
- rtcbook.org is untouched by this work — it pins its own parody-web version and
  upgrades on its own schedule.
