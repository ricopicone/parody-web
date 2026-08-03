# Web Visual Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan
> task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace parody-web's undesigned inline stylesheet with a tokenized design system —
typewriter/serif identity, dark mode, masthead + chapter navigation, typeset-contents landing page —
and ship it to rtcbook.org.

**Architecture:** All work is in `~/parody-web`. The 235-line inline `<style>` in `base.html` moves to
three static stylesheets driven by CSS custom properties. Per-book theming comes from a
`PARODY_WEB_THEME` Django setting, validated at app startup and rendered by a template tag. New
reading chrome (masthead, chapter sidebar, margin rail, footer) is added as template partials fed by a
shared view helper. No parody changes, no artifact schema change, no JS framework, no CSS build step.

**Tech Stack:** Django (installable app), plain CSS with custom properties, self-hosted WOFF2 fonts,
`python runtests.py` (Django test runner, 95 existing tests).

**Spec:** `docs/superpowers/specs/2026-08-02-web-visual-design.md`

## Global Constraints

- All changes in `~/parody-web`. No changes to parody, the artifact schema, or the print/PDF path.
- No CSS preprocessor, no node toolchain, no JS framework. Plain CSS + a few lines of vanilla JS.
- parody-web is an **installable app**: never require a consuming deployment to edit `TEMPLATES` or
  `MIDDLEWARE`. Theming is exposed through a template tag, not a context processor.
- The 95 existing tests must stay green after every task. Run `python runtests.py` before every commit.
- Fonts: Courier Prime and Source Serif 4, SIL OFL, self-hosted WOFF2, latin subset, vendored in-repo.
- Accessibility: every text/background token pair meets WCAG AA. `--ink-ghost` is decoration only,
  never text.
- Work on branch `web-visual-design`, branched from `main` at `957aa2c`. Merge to `main` at the end.
- Release is the **reduced** chain (parody-web-only change): publish parody-web → bump rtcbook-web pin
  → deploy. Budget 5+ minutes for PyPI propagation before deploying.

---

## File Structure

**Created:**

- `parody_web/static/parody_web/css/tokens.css` — custom properties only; light, dark, and
  `data-theme` overrides.
- `parody_web/static/parody_web/css/book.css` — reset, typography, page layout, masthead, sidebar,
  rail, footer, nav, pager.
- `parody_web/static/parody_web/css/content.css` — book-content components: figures, tables, boxes,
  listings, math, subject index, search results, key chips, syntax highlighting.
- `parody_web/static/parody_web/fonts/` — 6 WOFF2 files + `OFL.txt`.
- `parody_web/theme.py` — token whitelist, value validation, CSS generation.
- `parody_web/templates/parody_web/_masthead.html` — sticky top bar.
- `parody_web/templates/parody_web/_footer.html` — site footer.
- `parody_web/templates/parody_web/_chapter_nav.html` — sidebar chapter section list.
- `parody_web/templates/parody_web/_rail.html` — right margin rail.

**Modified:**

- `parody_web/templates/parody_web/base.html` — strip the inline style block; add font preloads,
  stylesheet links, theme style, no-flash script, masthead, footer.
- `parody_web/templates/parody_web/{index,chapter,section,book_index,search,systems,errata}.html`
- `parody_web/templates/registration/login.html`
- `parody_web/views.py` — `_chapter_nav()` and `_page_anchors()` helpers; extra context in
  `section_detail` (`:294-317`) and `chapter_detail` (`:259-292`).
- `parody_web/apps.py` — validate `PARODY_WEB_THEME` in `ready()`.
- `parody_web/templatetags/parody_web.py` — `{% theme_css %}` tag.
- `parody_web/tests.py` — new test classes appended.
- `pyproject.toml` — version bump to 0.30.0.

---

# Phase 1 — Foundation (pure refactor, no visual change)

### Task 1: Extract the inline stylesheet into static files

**Files:**
- Create: `parody_web/static/parody_web/css/tokens.css`, `book.css`, `content.css`
- Modify: `parody_web/templates/parody_web/base.html:7-242`
- Test: `parody_web/tests.py`

**Interfaces:**
- Produces: three stylesheets linked from `base.html` via `{% static %}`; token names defined in
  `tokens.css` and consumed by the other two.

This task is a **pure refactor**. Every declaration keeps its current computed value; only its
location changes, and hardcoded values become token references whose values are today's values.

- [ ] **Step 1: Write the failing test**

Append to `parody_web/tests.py` (new class at end of file):

```python
class StylesheetTests(TestCase):
    def setUp(self):
        _import()

    def test_stylesheets_linked_and_no_inline_block(self):
        html = self.client.get("/").content.decode()
        for name in ("tokens.css", "book.css", "content.css"):
            self.assertIn(f"css/{name}", html)
        # the 235-line inline block is gone; only the small theme <style> may remain
        self.assertNotIn("nav.crumbs", html.split("</head>")[0].replace("\n", " ")
                         .split("<style>")[-1] if "<style>" in html else "")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"`
Expected: FAILED — `tokens.css` not in the response.

- [ ] **Step 3: Create `tokens.css` with today's values**

```css
/* Design tokens. Phase 1 records the CURRENT values verbatim so the extraction
   is visually neutral; Phase 2 changes them. */
:root {
  --paper: #ffffff;
  --paper-sunk: #f6f6f4;
  --ink: #1a1a1a;
  --ink-muted: #555555;
  --ink-faint: #777777;
  --ink-ghost: #999999;
  --rule: #dddddd;
  --rule-faint: #eeeeee;
  --accent: #7a6ff0;
  --accent-ink: #5a4fd0;
  --accent-soft: #c8c8c8;
  --accent-wash: #eef0fb;
  --box-line: #a89a86;
  --box-label: #6b5d49;
  --box-wash: #faf8f3;
  --box-rule: #e0d9cb;
  --flash: #fdf2b8;
  --mark: #fde68a;

  --font-display: system-ui, sans-serif;
  --font-body: Georgia, 'Times New Roman', serif;
  --font-mono: ui-monospace, Menlo, monospace;

  --fs-base: 1.05rem;
  --lh-base: 1.6;
  --measure: 46rem;
}
```

- [ ] **Step 4: Move the style block into `book.css` and `content.css`**

Split the existing block at `base.html:8-241` by responsibility, replacing literal values with the
tokens above. Layout, typography, nav, crumbs, pager, forms, buttons, `.signin-gate`, `.preview`,
`.draft-banner`, `.version-icon`, `.edition-switcher` → `book.css`. Figures, subfigures, subtables,
tables, captions, `.example`, `.freadinglist`, `.book-index`, `.search-*`, `.key`/`.menu`,
`pre`/`code` syntax spans, `.eqanchor`, `.index`, `.rights-placeholder`, `.listing-caption`,
`table.specs`, `section.references` → `content.css`.

Example of the mechanical substitution — this block:

```css
body { max-width: 46rem; margin: 2rem auto; padding: 0 1rem;
       font: 1.05rem/1.6 Georgia, 'Times New Roman', serif; color: #1a1a1a; }
```

becomes, in `book.css`:

```css
body { max-width: var(--measure); margin: 2rem auto; padding: 0 1rem;
       font: var(--fs-base)/var(--lh-base) var(--font-body); color: var(--ink); }
```

Keep every comment from the original block — they document real gotchas (pandoc quirks, cmidrule
segments, the equation anchor relocation).

- [ ] **Step 5: Replace the block in `base.html`**

Delete lines 7–242 (`<style>` … `</style>`) and insert, after the `<title>` line:

```html
{% load static %}
<link rel="stylesheet" href="{% static 'parody_web/css/tokens.css' %}">
<link rel="stylesheet" href="{% static 'parody_web/css/book.css' %}">
<link rel="stylesheet" href="{% static 'parody_web/css/content.css' %}">
```

- [ ] **Step 6: Run the full suite**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"`
Expected: `Ran 96 tests` … `OK`

- [ ] **Step 7: Verify visually neutral**

Run `python -m http.server` is not enough — start the example site and screenshot the index:
`cd example_site && python manage.py runserver 8765`. Compare against the pre-change page. Any visual
difference is a bug in the extraction, not an improvement — fix it now.

- [ ] **Step 8: Commit**

```bash
git add parody_web/static/parody_web/css parody_web/templates/parody_web/base.html parody_web/tests.py
git commit -m "css: extract the inline stylesheet into tokens/book/content"
```

---

### Task 2: Theme setting, validation, and template tag

**Files:**
- Create: `parody_web/theme.py`
- Modify: `parody_web/apps.py`, `parody_web/templatetags/parody_web.py`,
  `parody_web/templates/parody_web/base.html`
- Test: `parody_web/tests.py`

**Interfaces:**
- Produces:
  - `parody_web.theme.ALLOWED_THEME_TOKENS: frozenset[str]`
  - `parody_web.theme.validate_theme(theme: dict) -> None` — raises `ImproperlyConfigured`
  - `parody_web.theme.theme_css(theme: dict) -> str` — returns a `<style>`-ready CSS string
  - `{% theme_css %}` template tag, used in `base.html`

A template tag, not a context processor: a context processor would force every deployment to edit its
`TEMPLATES` setting, which an installable app must not require. Validation still happens at startup
via `AppConfig.ready()`, so a bad setting fails fast rather than at first render.

- [ ] **Step 1: Write the failing tests**

```python
from django.core.exceptions import ImproperlyConfigured
from parody_web.theme import theme_css, validate_theme


class ThemeSettingTests(TestCase):
    def setUp(self):
        _import()

    def test_tokens_emitted_for_light_and_dark(self):
        css = theme_css({"light": {"accent": "#b3261e"},
                         "dark": {"accent": "#ff8a80"}})
        self.assertIn(":root{--accent:#b3261e}", css.replace(" ", ""))
        self.assertIn('[data-theme="dark"]', css)
        self.assertIn("#ff8a80", css)

    def test_unknown_token_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_theme({"light": {"background-image": "url(evil.png)"}})

    def test_malformed_value_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_theme({"light": {"accent": "red; } body { display:none"}})

    def test_font_stack_value_accepted(self):
        validate_theme({"light": {"font-display": '"Courier Prime", monospace'}})

    @override_settings(PARODY_WEB_THEME={"light": {"accent": "#b3261e"}})
    def test_theme_reaches_the_page(self):
        html = self.client.get("/").content.decode()
        self.assertIn("#b3261e", html)

    def test_absent_setting_emits_nothing(self):
        self.assertEqual(theme_css(None), "")
```

- [ ] **Step 2: Run and watch them fail**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"`
Expected: FAILED — `No module named 'parody_web.theme'`

- [ ] **Step 3: Write `parody_web/theme.py`**

```python
"""Per-book theme overrides.

A deployment may retint the site through settings.PARODY_WEB_THEME without
touching parody-web:

    PARODY_WEB_THEME = {"light": {"accent": "#b3261e"},
                        "dark":  {"accent": "#ff8a80"}}

Only whitelisted token names are accepted, and only colour / font-stack shaped
values — a settings dict must never become a CSS injection vector.
"""
import re

from django.core.exceptions import ImproperlyConfigured

ALLOWED_THEME_TOKENS = frozenset({
    "accent", "accent-ink", "accent-soft", "accent-wash",
    "paper", "paper-sunk", "ink", "ink-muted",
    "font-display", "font-body",
})

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# a font stack: quoted family names and bare generics, comma separated
_FONT = re.compile(r'^(?:"[\w \-]+"|[a-z\-]+)(?:\s*,\s*(?:"[\w \-]+"|[a-z\-]+))*$')

_MODES = {"light": ":root", "dark": ':root[data-theme="dark"]'}


def _check_value(token, value):
    if not isinstance(value, str):
        raise ImproperlyConfigured(
            f"PARODY_WEB_THEME: {token!r} must be a string, got {type(value).__name__}")
    ok = _FONT.match(value) if token.startswith("font-") else _HEX.match(value)
    if not ok:
        raise ImproperlyConfigured(
            f"PARODY_WEB_THEME: {value!r} is not a valid value for {token!r}")


def validate_theme(theme):
    """Raise ImproperlyConfigured unless `theme` is a well-formed override dict."""
    if not theme:
        return
    if not isinstance(theme, dict):
        raise ImproperlyConfigured("PARODY_WEB_THEME must be a dict")
    for mode, tokens in theme.items():
        if mode not in _MODES:
            raise ImproperlyConfigured(
                f"PARODY_WEB_THEME: unknown mode {mode!r} (expected light/dark)")
        if not isinstance(tokens, dict):
            raise ImproperlyConfigured(f"PARODY_WEB_THEME[{mode!r}] must be a dict")
        for token, value in tokens.items():
            if token not in ALLOWED_THEME_TOKENS:
                raise ImproperlyConfigured(
                    f"PARODY_WEB_THEME: {token!r} is not an overridable token "
                    f"(allowed: {', '.join(sorted(ALLOWED_THEME_TOKENS))})")
            _check_value(token, value)


def theme_css(theme):
    """CSS text overriding the default tokens, or "" when nothing is set."""
    validate_theme(theme)
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

- [ ] **Step 4: Validate at startup in `apps.py`**

```python
from django.apps import AppConfig


class ParodyWebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parody_web"

    def ready(self):
        # Fail at startup on a malformed theme, not at first page render.
        from django.conf import settings

        from .theme import validate_theme
        validate_theme(getattr(settings, "PARODY_WEB_THEME", None))
```

- [ ] **Step 5: Add the template tag**

Append to `parody_web/templatetags/parody_web.py`:

```python
@register.simple_tag
def theme_css():
    """Per-deployment token overrides (settings.PARODY_WEB_THEME) as CSS."""
    from ..theme import theme_css as _css
    return mark_safe(_css(getattr(settings, "PARODY_WEB_THEME", None)))
```

- [ ] **Step 6: Render it in `base.html`**

Directly after the three stylesheet links:

```html
<style>{% theme_css %}</style>
```

- [ ] **Step 7: Run the tests**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"`
Expected: `Ran 102 tests` … `OK`

- [ ] **Step 8: Commit**

```bash
git add parody_web/theme.py parody_web/apps.py parody_web/templatetags/parody_web.py \
        parody_web/templates/parody_web/base.html parody_web/tests.py
git commit -m "theme: per-book token overrides via a validated PARODY_WEB_THEME setting"
```

---

# Phase 2 — Identity

### Task 3: Vendor the fonts

**Files:**
- Create: `parody_web/static/parody_web/fonts/*.woff2`, `parody_web/static/parody_web/fonts/OFL.txt`
- Modify: `parody_web/static/parody_web/css/tokens.css`, `base.html`

**Interfaces:**
- Produces: `--font-display` = Courier Prime stack, `--font-body` = Source Serif 4 stack, both backed
  by `@font-face` rules in `tokens.css`.

- [ ] **Step 1: Download the WOFF2 files**

The Google Fonts CSS API serves WOFF2 only to modern user agents, so the UA header is required:

```bash
mkdir -p parody_web/static/parody_web/fonts && cd parody_web/static/parody_web/fonts && UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" && curl -s -H "User-Agent: $UA" "https://fonts.googleapis.com/css2?family=Courier+Prime:ital,wght@0,400;0,700;1,400;1,700&family=Source+Serif+4:ital,opsz,wght@0,8..60,200..900;1,8..60,200..900&display=swap" -o fonts.css && grep -oE 'https://[^)]+\.woff2' fonts.css | sort -u
```

Then download each URL whose preceding `unicode-range` block is the latin subset, naming them
`courier-prime-400.woff2`, `courier-prime-400-italic.woff2`, `courier-prime-700.woff2`,
`courier-prime-700-italic.woff2`, `source-serif-4-variable.woff2`,
`source-serif-4-variable-italic.woff2`. Delete `fonts.css` afterwards.

- [ ] **Step 2: Save the licenses**

Both families are SIL OFL 1.1. Save the license text to `fonts/OFL.txt` with a header naming both
families and their upstream URLs (`github.com/quoteunquoteapps/CourierPrime`,
`github.com/adobe-fonts/source-serif`).

- [ ] **Step 3: Add `@font-face` rules at the top of `tokens.css`**

```css
@font-face { font-family: "Courier Prime"; font-style: normal; font-weight: 400;
  font-display: swap; src: url("../fonts/courier-prime-400.woff2") format("woff2"); }
@font-face { font-family: "Courier Prime"; font-style: italic; font-weight: 400;
  font-display: swap; src: url("../fonts/courier-prime-400-italic.woff2") format("woff2"); }
@font-face { font-family: "Courier Prime"; font-style: normal; font-weight: 700;
  font-display: swap; src: url("../fonts/courier-prime-700.woff2") format("woff2"); }
@font-face { font-family: "Courier Prime"; font-style: italic; font-weight: 700;
  font-display: swap; src: url("../fonts/courier-prime-700-italic.woff2") format("woff2"); }
@font-face { font-family: "Source Serif 4"; font-style: normal; font-weight: 200 900;
  font-display: swap; src: url("../fonts/source-serif-4-variable.woff2") format("woff2"); }
@font-face { font-family: "Source Serif 4"; font-style: italic; font-weight: 200 900;
  font-display: swap; src: url("../fonts/source-serif-4-variable-italic.woff2") format("woff2"); }
```

- [ ] **Step 4: Point the font tokens at them**

```css
  --font-display: "Courier Prime", "Courier New", monospace;
  --font-body: "Source Serif 4", Charter, Georgia, serif;
  --font-mono: "Courier Prime", "Courier New", monospace;
```

- [ ] **Step 5: Preload the two faces above the fold**

In `base.html`, before the stylesheet links:

```html
<link rel="preload" as="font" type="font/woff2" crossorigin
      href="{% static 'parody_web/fonts/source-serif-4-variable.woff2' %}">
<link rel="preload" as="font" type="font/woff2" crossorigin
      href="{% static 'parody_web/fonts/courier-prime-700.woff2' %}">
```

- [ ] **Step 6: Run the tests and check the page**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected OK.
Then load the example site and confirm both faces render (no fallback to Georgia/Courier New).

- [ ] **Step 7: Commit**

```bash
git add parody_web/static/parody_web/fonts parody_web/static/parody_web/css/tokens.css \
        parody_web/templates/parody_web/base.html
git commit -m "fonts: self-host Courier Prime + Source Serif 4 (OFL)"
```

---

### Task 4: Apply the light palette and type scale

**Files:**
- Modify: `parody_web/static/parody_web/css/tokens.css`, `book.css`
- Test: `parody_web/tests.py`

**Interfaces:**
- Produces: the final light token values consumed by every later task.

- [ ] **Step 1: Replace the light token values**

```css
:root {
  --paper: #fbf9f5;
  --paper-sunk: #f4f0e7;
  --paper-panel: #ffffff;   /* images only — light in BOTH themes */
  --ink: #1c1b19;
  --ink-muted: #56534c;
  --ink-faint: #6f6c64;     /* 4.8:1 on paper — the lowest token allowed for text */
  --ink-ghost: #8d8a80;     /* 3.2:1 — DECORATION ONLY, never text */
  --rule: #e8e3d9;
  --rule-strong: #1c1b19;
  --accent: #3550c8;
  --accent-ink: #2a3fa0;
  --accent-soft: #ccd4f3;
  --accent-wash: #eef1fb;
  --flash: #fdf2b8;
  --mark: #fde68a;

  --fs-xs: .72rem;  --fs-sm: .82rem;  --fs-base: 1.0625rem;  --fs-lg: 1.25rem;
  --fs-h3: 1.35rem; --fs-h2: 1.6rem;  --fs-h1: 1.9rem;
  --lh-base: 1.62;  --lh-head: 1.18;
  --measure: 34rem;

  --s1: .25rem; --s2: .5rem; --s3: .75rem; --s4: 1rem;
  --s5: 1.5rem; --s6: 2rem; --s7: 3rem; --s8: 4rem;
}
```

Note `--box-line`/`--box-label`/`--box-wash`/`--box-rule` are deliberately dropped here; Task 6
rewrites the components that used them onto the palette above.

- [ ] **Step 2: Apply the type rule in `book.css`**

Monospace for numbers, labels and headings; serif for anything that runs long.

```css
body { max-width: none; margin: 0; padding: 0;
       font: var(--fs-base)/var(--lh-base) var(--font-body);
       color: var(--ink); background: var(--paper); }
h1, h2, h3, h4 { font-family: var(--font-display); line-height: var(--lh-head);
                 letter-spacing: -.03em; font-weight: 700; }
h1 { font-size: var(--fs-h1); } h2 { font-size: var(--fs-h2); } h3 { font-size: var(--fs-h3); }
.secnum { font-family: var(--font-display); color: var(--accent); font-weight: 700;
          margin-right: var(--s2); font-variant-numeric: tabular-nums; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
a:focus-visible, button:focus-visible, summary:focus-visible, input:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px; }
/* contents lists and breadcrumbs stay serif — monospace running text at list
   size is where the identity breaks (94-char chapter titles). */
ul.toc, nav.crumbs { font-family: var(--font-body); }
```

The `body` rule surrenders centring because Task 8 introduces the page grid; until then pages will
look full-bleed. That is expected and corrected in Phase 3.

- [ ] **Step 2b: Add a temporary page wrapper so Phase 2 stays reviewable**

```css
.page { max-width: var(--measure); margin: var(--s6) auto; padding: 0 var(--s4); }
```

Wrap `{% block body %}` in `base.html` with `<div class="page">…</div>`. Task 8 replaces this wrapper
with the real grid.

- [ ] **Step 3: Write the accessibility guard test**

```python
class PaletteContrastTests(TestCase):
    """--ink-ghost is decoration-only; catch it being used for text."""

    def test_ghost_token_not_used_for_color_on_text_rules(self):
        from pathlib import Path
        css = Path("parody_web/static/parody_web/css/book.css").read_text()
        css += Path("parody_web/static/parody_web/css/content.css").read_text()
        for line in css.splitlines():
            if "--ink-ghost" in line and "color:" in line:
                self.assertIn("border", line + "",
                              f"--ink-ghost used as text colour: {line.strip()}")
```

- [ ] **Step 4: Run the tests**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected OK.

- [ ] **Step 5: Commit**

```bash
git add parody_web/static/parody_web/css parody_web/templates/parody_web/base.html parody_web/tests.py
git commit -m "css: apply the warm-paper palette and typewriter/serif type scale"
```

---

### Task 5: Dark mode

**Files:**
- Modify: `tokens.css`, `book.css`, `base.html`
- Test: `parody_web/tests.py`

**Interfaces:**
- Produces: `data-theme` attribute contract on `<html>`, `localStorage["parody-theme"]`, and a
  `.theme-toggle` button that Task 8 relocates into the masthead.

- [ ] **Step 1: Add the dark token block to `tokens.css`**

```css
/* Dark mode. --paper-panel deliberately does NOT flip: figures are images with
   white or transparent backgrounds baked in by LaTeX, so they sit on a light
   panel. Tables, math and code are live text and recolour correctly. */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #16171a; --paper-sunk: #1e2025;
    --ink: #e8e6e1; --ink-muted: #a8a49c; --ink-faint: #78756e; --ink-ghost: #5a5852;
    --rule: #2c2e34; --rule-strong: #e8e6e1;
    --accent: #93a6f5; --accent-ink: #b9c4f8;
    --accent-soft: #2f3a63; --accent-wash: #1b1f2e;
    --flash: #4a4326; --mark: #6b5d1f;
  }
}
:root[data-theme="dark"] {
  --paper: #16171a; --paper-sunk: #1e2025;
  --ink: #e8e6e1; --ink-muted: #a8a49c; --ink-faint: #78756e; --ink-ghost: #5a5852;
  --rule: #2c2e34; --rule-strong: #e8e6e1;
  --accent: #93a6f5; --accent-ink: #b9c4f8;
  --accent-soft: #2f3a63; --accent-wash: #1b1f2e;
  --flash: #4a4326; --mark: #6b5d1f;
}
```

- [ ] **Step 2: Put images on the light panel**

In `content.css`:

```css
/* LaTeX-baked images carry their own white/transparent background, so they keep
   a light panel in dark mode rather than being inverted (which would wreck the
   colour figures, photos and screenshots this book contains). */
figure img, img.cover, figure[id^="tbl:"] img, figure[id^="al:"] img,
figure[id^="alg:"] img { background: var(--paper-panel); border-radius: 3px; }
:root[data-theme="dark"] figure img,
:root[data-theme="dark"] figure[id^="tbl:"] img { padding: var(--s2); }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) figure img { padding: var(--s2); }
}
```

- [ ] **Step 3: Add the no-flash script and the toggle**

In `base.html`, as the first thing inside `<head>`:

```html
<script>
/* Apply the stored theme before first paint so a dark-mode reader never sees a
   white flash. Absent preference = follow the system. */
(function () {
  try {
    var t = localStorage.getItem('parody-theme');
    if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t;
  } catch (e) {}
})();
</script>
```

and, in the body (temporarily beside the owner-view line; Task 8 moves it):

```html
<button class="theme-toggle" type="button" aria-label="Toggle dark mode">◐</button>
<script>
document.querySelector('.theme-toggle').addEventListener('click', function () {
  var root = document.documentElement;
  var dark = getComputedStyle(root).getPropertyValue('--paper').trim() === '#16171a';
  var next = dark ? 'light' : 'dark';
  root.dataset.theme = next;
  try { localStorage.setItem('parody-theme', next); } catch (e) {}
});
</script>
```

- [ ] **Step 4: Honour reduced motion**

In `content.css`, beside the existing `eq-target-flash` keyframes:

```css
@media (prefers-reduced-motion: reduce) {
  .eqanchor:target ~ .math.display { animation: none; background: var(--flash); }
}
```

- [ ] **Step 5: Write the test**

```python
class DarkModeTests(TestCase):
    def setUp(self):
        _import()

    def test_no_flash_script_and_toggle_present(self):
        html = self.client.get("/").content.decode()
        self.assertIn("parody-theme", html)
        self.assertIn('class="theme-toggle"', html)
```

- [ ] **Step 6: Run the tests, then check both themes**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected OK.
Load the example site, toggle, and confirm: no flash on reload, figures stay legible, the toggle
overrides the OS setting in both directions.

- [ ] **Step 7: Commit**

```bash
git add parody_web/static/parody_web/css parody_web/templates/parody_web/base.html parody_web/tests.py
git commit -m "css: dark mode with light panels for LaTeX-baked images"
```

---

### Task 6: Component sweep — boxes, badges and controls

**Files:**
- Modify: `parody_web/static/parody_web/css/content.css`, `book.css`

Retunes every component that used the retired taupe placeholder or a hardcoded grey onto the palette.

- [ ] **Step 1: Rewrite the example box**

The bracket-corner geometry from task #318 is kept; only the colour source changes.

```css
/* [ … ] bracket box mirroring the print book's boxed examples (task #318).
   --exc = corner arm length, --ext = thickness. */
.example { --exc: 18px; --ext: 1.5px; --excol: var(--accent);
  margin: var(--s5) 0; padding: var(--s4) var(--s5);
  background-image:
    linear-gradient(var(--excol),var(--excol)), linear-gradient(var(--excol),var(--excol)),
    linear-gradient(var(--excol),var(--excol)), linear-gradient(var(--excol),var(--excol)),
    linear-gradient(var(--excol),var(--excol)), linear-gradient(var(--excol),var(--excol));
  background-repeat: no-repeat;
  background-size: var(--ext) 100%, var(--ext) 100%, var(--exc) var(--ext),
    var(--exc) var(--ext), var(--exc) var(--ext), var(--exc) var(--ext);
  background-position: left top, right top, left top, right top, left bottom, right bottom; }
.example-label { font-family: var(--font-display); font-weight: 700; font-size: var(--fs-sm);
  color: var(--accent); margin-bottom: var(--s2); }
.example > .example-solution { margin-top: var(--s3); padding-top: var(--s3);
  border-top: 1px dashed var(--rule); }
```

- [ ] **Step 2: Rewrite the remaining boxes and controls**

Apply the same substitution to `.freadinglist` / `.freading-label`, `.signin-gate`, `form.codebox`,
`a.continue-button`, `a.download-button`, `.version-icon` (+ `.ds`), `.draft-banner`,
`.rights-placeholder`, `.key`/`.keys`/`.menu .m-item`, `table.specs`, `section.references`,
`section.online-resources`, `.note`, `nav.edition-switcher`, `.preview`:

| Old value | Token |
|---|---|
| `#f6f6f4`, `#faf8f3`, `#f8f8f8` | `var(--paper-sunk)` |
| `#ddd`, `#e0d9cb`, `#c8c8c8`, `#eee` | `var(--rule)` |
| `#7a6ff0`, `#5a4fd0` | `var(--accent)` |
| `#a89a86`, `#6b5d49` | `var(--accent)` |
| `#555`, `#333` | `var(--ink-muted)` |
| `#777`, `#999` on text | `var(--ink-faint)` |
| `#2a9d8f` (`.version-icon.ds`) | keep — it is a *semantic* distinction (DS vs TS track), not decoration |
| `#fff7e6` / `#f0c060` (draft banner) | `var(--accent-wash)` / `var(--accent-soft)` |

Every label that was `system-ui, sans-serif` becomes `var(--font-display)`.

- [ ] **Step 3: Run the tests**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected OK.

- [ ] **Step 4: Check every component renders**

The example site's demo book does not exercise all of these. Load the RTC artifact locally if
available, otherwise inspect `parody_web/tests.py` fixtures for each class and confirm via the test
client HTML that the class names still match.

- [ ] **Step 5: Commit**

```bash
git add parody_web/static/parody_web/css
git commit -m "css: retune boxes, badges and controls onto the palette"
```

---

### Task 7: Component sweep — content typography and syntax highlighting

**Files:**
- Modify: `parody_web/static/parody_web/css/content.css`

- [ ] **Step 1: Retune figures, tables and captions**

`.fignum`, `.subfignum`, `.listing-caption`, `figcaption`, `table.notes-table` rules, `.grp`,
`.vsep2`, `.cmid::after`, `.book-index`, `.index-letter`, `.index-entry`, `.search-*`, `mark`:
replace `#222` → `var(--rule-strong)`, `#999`/`#bbb` → `var(--rule)`, `#555` → `var(--ink-muted)`,
`#fde68a` → `var(--mark)`. Caption number spans (`.fignum`, `.subfignum`) take
`font-family: var(--font-display)`; caption *prose* stays serif.

- [ ] **Step 2: Give code blocks a theme-aware surface**

```css
pre { background: var(--paper-sunk); color: var(--ink); padding: var(--s3) var(--s4);
      border-radius: 4px; overflow-x: auto; font-size: var(--fs-sm);
      font-family: var(--font-mono); }
code { font-family: var(--font-mono); }
```

- [ ] **Step 3: Tokenize the syntax-highlighting palette**

Today's colours are hardcoded light-mode values with no dark variant. Define them as tokens so the
dark block can flip them:

```css
:root {
  --syn-kw: #007020; --syn-dt: #902000; --syn-num: #40a070; --syn-str: #4070a0;
  --syn-com: #60a0b0; --syn-op: #666666; --syn-fun: #06287e; --syn-con: #880000;
  --syn-var: #19177c; --syn-pp: #bc7a00; --syn-err: #ff0000;
}
:root[data-theme="dark"] {
  --syn-kw: #7ec699; --syn-dt: #e2a072; --syn-num: #9ad1a5; --syn-str: #8fb8e0;
  --syn-com: #7f9fa8; --syn-op: #a8a49c; --syn-fun: #9db4ef; --syn-con: #e08f8f;
  --syn-var: #b0aee8; --syn-pp: #e0b56a; --syn-err: #ff8a80;
}
```

Repeat the dark block inside the `@media (prefers-color-scheme: dark)
:root:not([data-theme="light"])` selector, then point every `code span.*` rule at its token.

- [ ] **Step 4: Run the tests**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected OK.

- [ ] **Step 5: Commit**

```bash
git add parody_web/static/parody_web/css/content.css
git commit -m "css: retune content typography; tokenize syntax highlighting with a dark variant"
```

---

# Phase 3 — Chrome

### Task 8: Masthead, footer, and the page grid

**Files:**
- Create: `_masthead.html`, `_footer.html`
- Modify: `base.html`, `book.css`
- Test: `parody_web/tests.py`

**Interfaces:**
- Produces: `.site-head`, `.site-foot`, `.page` grid; `{% block body %}` now renders inside
  `<main class="col">`. The theme toggle and owner sign-in move here from their temporary homes.

- [ ] **Step 1: Write the failing test**

```python
class ChromeTests(TestCase):
    def setUp(self):
        _import()

    def test_masthead_and_footer_present(self):
        html = self.client.get("/").content.decode()
        self.assertIn('class="site-head"', html)
        self.assertIn('class="site-foot"', html)
        self.assertIn('class="theme-toggle"', html)

    def test_owner_signin_moved_out_of_floating_div(self):
        html = self.client.get("/").content.decode()
        self.assertNotIn('style="font-family:system-ui,sans-serif;font-size:.8rem;'
                         'text-align:right', html)
        self.assertIn("owner sign in", html)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected FAILED, no `site-head`.

- [ ] **Step 3: Write `_masthead.html`**

```html
{% load parody_web %}
<header class="site-head">
  <a class="site-title" href="{% index_url book %}">{{ book.title }}</a>
  <nav class="site-nav">
    <details class="contents-menu">
      <summary>Contents</summary>
      <div class="contents-pop">{% include "parody_web/_chapter_nav.html" %}</div>
    </details>
    <a href="{% url 'parody_web:book_index' %}{{ ed_query }}">Index</a>
    <form class="head-search" action="{% url 'parody_web:search' %}" method="get" role="search">
      <input type="search" name="q" placeholder="Search inside…" aria-label="Search inside the book">
    </form>
    <button class="theme-toggle" type="button" aria-label="Toggle dark mode">◐</button>
  </nav>
</header>
```

- [ ] **Step 4: Write `_footer.html`**

Move the edition switcher, the draft banner note, the owner sign-in form (currently the inline-styled
div at `base.html:296-303`) and a copyright line here, all classed rather than inline-styled.

- [ ] **Step 5: Add the grid to `book.css`**

```css
.site-head { position: sticky; top: 0; z-index: 10; display: flex; gap: var(--s4);
  align-items: center; padding: var(--s2) var(--s5); background: var(--paper);
  border-bottom: 1px solid var(--rule); font-family: var(--font-display);
  font-size: var(--fs-sm); }
.site-title { font-weight: 700; color: var(--ink); }
.site-nav { margin-left: auto; display: flex; gap: var(--s4); align-items: center; }
.page { display: grid; gap: var(--s6); justify-content: center; padding: var(--s6) var(--s5);
  grid-template-columns: 12.5rem minmax(0, var(--measure)) 9rem; }
.col { min-width: 0; }
.side, .rail { font-size: var(--fs-sm); }
@media (max-width: 1440px) { .page { grid-template-columns: 12.5rem minmax(0, var(--measure)); }
                             .rail { display: none; } }
@media (max-width: 1180px) { .page { grid-template-columns: minmax(0, var(--measure)); }
                             .side { display: none; } }
@media (max-width: 900px)  { .page { padding: var(--s4) var(--s4); }
                             .site-head { padding: var(--s2) var(--s4); }
                             .head-search { display: none; }
                             nav.pager { flex-direction: column; gap: var(--s2); } }
```

The `.contents-menu` disclosure is present at every width; below 1180px it becomes the only route to
the chapter contents.

- [ ] **Step 6: Re-tune the scroll anchors**

**This is a regression guard.** `.eqanchor` and `.index` set `scroll-margin-top` (3rem / 5rem) tuned
for a page with no masthead; a sticky header hides the target under it. In `content.css`:

```css
/* keep in sync with the sticky .site-head height */
:root { --head-h: 3rem; }
.eqanchor { scroll-margin-top: calc(var(--head-h) + var(--s5)); }
.index { scroll-margin-top: calc(var(--head-h) + var(--s6)); }
```

- [ ] **Step 7: Wire it into `base.html`**

Replace the floating owner-view div and the bare `{% block body %}` with:

```html
{% include "parody_web/_masthead.html" %}
<div class="page">
  {% block side %}{% endblock %}
  <main class="col">{% block body %}{% endblock %}</main>
  {% block rail %}{% endblock %}
</div>
{% include "parody_web/_footer.html" %}
```

- [ ] **Step 8: Run the tests**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected OK.

- [ ] **Step 9: Verify the equation deep-link still lands**

Load a section with a numbered equation and follow an equation cross-ref. The equation must land
below the masthead, not under it. This is the #297/#306 behaviour and must not regress.

- [ ] **Step 10: Commit**

```bash
git add parody_web/templates/parody_web parody_web/static/parody_web/css parody_web/tests.py
git commit -m "chrome: sticky masthead, footer and page grid; re-tune scroll anchors"
```

---

### Task 9: Chapter sidebar and margin rail

**Files:**
- Create: `_chapter_nav.html`, `_rail.html`
- Modify: `views.py:259-317`, `section.html`, `chapter.html`, `book.css`
- Test: `parody_web/tests.py`

**Interfaces:**
- Consumes: `_all_sections_ordered(book)` (existing, `views.py:90`)
- Produces:
  - `_chapter_nav(book, chapter, current=None) -> list[Section]` — the chapter's content sections in
    order, each with a `.is_current` boolean attached
  - `_page_anchors(html) -> list[dict]` — `[{"id": str, "text": str}]` for `<h2 id=…>` in the section
  - context keys `chapter_nav` and `page_anchors` on section pages; `chapter_nav` on chapter pages

- [ ] **Step 1: Write the failing tests**

```python
class ChapterNavTests(TestCase):
    def setUp(self):
        _import()

    def test_sidebar_lists_siblings_with_one_current(self):
        html = self.client.get("/hardware/specific-t1/").content.decode()
        self.assertIn('class="side"', html)
        self.assertEqual(html.count('class="nav-item on"'), 1)
        self.assertIn("Licensed Chapter", html)  # a sibling is listed

    def test_leadin_excluded_from_sidebar(self):
        html = self.client.get("/hardware/specific-t1/").content.decode()
        nav = html.split('class="side"')[1].split("</nav>")[0]
        self.assertNotIn(">Hardware</a>", nav)  # the lead-in section

    def test_page_anchors_extracted_from_h2_ids(self):
        from parody_web.views import _page_anchors
        got = _page_anchors('<h2 data-h="x" id="alpha">Alpha</h2><h2>No id</h2>'
                            '<h2 id="beta">Beta <em>b</em></h2>')
        self.assertEqual([a["id"] for a in got], ["alpha", "beta"])
        self.assertEqual(got[0]["text"], "Alpha")
        self.assertEqual(got[1]["text"], "Beta b")
```

- [ ] **Step 2: Run and watch them fail**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected FAILED.

- [ ] **Step 3: Add the view helpers**

In `views.py`, after `_all_sections_ordered` (line 98):

```python
_H2_ID_RE = re.compile(r'<h2\b[^>]*\bid="(?P<id>[^"]+)"[^>]*>(?P<text>.*?)</h2>', re.S)


def _chapter_nav(book, chapter, current=None):
    """The chapter's content sections in reading order, each flagged whether it
    is the one being read. The lead-in is intro prose, not a contents entry."""
    out = []
    for s in chapter.sections.all():
        if s.slug == "lead-in":
            continue
        s.is_current = bool(current and s.pk == current.pk)
        out.append(s)
    return out


def _page_anchors(html):
    """Subsection targets for the margin rail: <h2 id="…"> only. Headings
    without an id (some migrated sections have them) can't be linked, so they
    are skipped rather than guessed at."""
    out = []
    for mo in _H2_ID_RE.finditer(html or ""):
        text = " ".join(strip_tags(mo.group("text")).split())
        if text:
            out.append({"id": mo.group("id"), "text": text})
    return out
```

- [ ] **Step 4: Add the context**

In `section_detail` (`views.py:306`), add to the render context:

```python
        "chapter_nav": _chapter_nav(book, section.chapter, current=section),
        "page_anchors": [] if preview else _page_anchors(section.html),
```

In `chapter_detail` (`views.py:283`), add:

```python
        "chapter_nav": _chapter_nav(book, chapter),
```

Note the nav is built from `chapter.sections.all()`, which is already prefetched for
`chapter_detail` and one cheap query on `section_detail` — no N+1.

- [ ] **Step 5: Write `_chapter_nav.html`**

```html
{% load parody_web %}
<nav class="side" aria-label="Chapter contents">
  <p class="side-cap">{% if chapter.number %}{% if chapter.appendix %}Appendix {% endif %}Chapter {{ chapter.number }}{% else %}Contents{% endif %}</p>
  <ol class="nav-list">
  {% for s in chapter_nav %}
    <li class="nav-item{% if s.is_current %} on{% endif %}">
      {% if s.number %}<i>{{ s.number }}</i>{% endif %}
      <a href="{% section_url book chapter.slug s.slug %}">{{ s.title|code_spans }}</a>
    </li>
  {% endfor %}
  </ol>
</nav>
```

- [ ] **Step 6: Write `_rail.html`**

```html
<aside class="rail" aria-label="On this page">
  {% if page_anchors %}
  <p class="rail-cap">On this page</p>
  <ul class="rail-list">
    {% for a in page_anchors %}<li><a href="#{{ a.id }}">{{ a.text }}</a></li>{% endfor %}
  </ul>
  {% endif %}
</aside>
```

- [ ] **Step 7: Fill the blocks in `section.html` and `chapter.html`**

```html
{% block side %}{% include "parody_web/_chapter_nav.html" %}{% endblock %}
{% block rail %}{% include "parody_web/_rail.html" %}{% endblock %}
```

(`chapter.html` gets `side` only.)

- [ ] **Step 8: Style them in `book.css`**

```css
.side { position: sticky; top: calc(var(--head-h) + var(--s4)); align-self: start;
        max-height: calc(100vh - var(--head-h) - var(--s6)); overflow-y: auto; }
.side-cap, .rail-cap { font-family: var(--font-display); font-size: var(--fs-xs);
  letter-spacing: .12em; text-transform: uppercase; color: var(--ink-faint);
  border-bottom: 1px solid var(--rule); padding-bottom: var(--s1); margin: 0 0 var(--s2); }
.nav-list, .rail-list { list-style: none; margin: 0; padding: 0; }
.nav-item { margin: var(--s1) 0; line-height: 1.4; }
.nav-item i { font-family: var(--font-display); font-style: normal; font-size: var(--fs-xs);
  color: var(--ink-ghost); margin-right: var(--s1); }
.nav-item a { color: var(--ink-muted); }
.nav-item.on { font-weight: 600; box-shadow: -.7rem 0 0 -.62rem var(--accent); }
.nav-item.on a { color: var(--ink); }
.nav-item.on i { color: var(--accent); }
.rail { position: sticky; top: calc(var(--head-h) + var(--s4)); align-self: start;
        color: var(--ink-faint); }
.rail-list a { color: var(--ink-muted); }
```

- [ ] **Step 9: Run the tests**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected OK.

- [ ] **Step 10: Commit**

```bash
git add parody_web/views.py parody_web/templates/parody_web parody_web/static/parody_web/css \
        parody_web/tests.py
git commit -m "chrome: chapter sidebar and on-this-page margin rail"
```

---

# Phase 4 — Pages

### Task 10: Typeset-contents landing page

**Files:**
- Modify: `index.html`, `book.css`
- Test: `parody_web/tests.py`

- [ ] **Step 1: Write the failing test**

```python
class LandingPageTests(TestCase):
    def setUp(self):
        _import()

    def test_chapters_collapse_with_first_open(self):
        html = self.client.get("/").content.decode()
        self.assertIn('class="toc-chapter"', html)
        self.assertIn("<details class=\"toc-chapter\" open>", html)

    def test_search_and_code_boxes_survive(self):
        html = self.client.get("/").content.decode()
        self.assertIn('name="q"', html)      # search inside
        self.assertIn('id="code"', html)     # printed short code
```

- [ ] **Step 2: Run and watch it fail**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected FAILED.

- [ ] **Step 3: Restructure `index.html`**

Replace the flat chapter/section dump (`index.html:47-58`) with a `<details>` per chapter, first open:

```html
<div class="book-toc">
  <p class="toc-cap">Contents</p>
  <hr class="toc-rule">
  {% for chapter, sections in chapters %}
  <details class="toc-chapter"{% if forloop.first %} open{% endif %}>
    <summary>
      <i>{% if chapter.number %}{% if chapter.appendix %}App. {% endif %}{{ chapter.number }}{% endif %}</i>
      <em>{{ chapter.title|code_spans }}</em>
      <span class="dots"></span>
      <u>{{ sections|length }} §</u>
    </summary>
    <ul class="toc">
      {% for section in sections %}{% if section.slug != "lead-in" %}
      <li>{% if section.number %}<span class="secnum">{{ section.number }}</span>{% endif %}
        <a href="{% section_url book chapter.slug section.slug %}">{{ section.title|code_spans }}</a>
        {% if public and section.preview %}<span class="note">— preview</span>{% endif %}</li>
      {% endif %}{% endfor %}
    </ul>
  </details>
  {% endfor %}
</div>
```

Keep the cover, title block, authors, publisher line, "Get the book" button, the search form and the
code box above it — the QR codes printed in the book point at this page, so both forms are
load-bearing. Replace `img.cover`'s float with a flex title block.

- [ ] **Step 4: Style it in `book.css`**

```css
.book-hero { display: flex; gap: var(--s5); align-items: flex-start; margin-bottom: var(--s6); }
.book-hero img.cover { float: none; max-width: 9rem; margin: 0; border: 1px solid var(--rule);
  box-shadow: 0 1px 4px rgb(0 0 0 / .15); }
.toc-cap { font-family: var(--font-display); font-size: var(--fs-xs); letter-spacing: .18em;
  text-transform: uppercase; color: var(--ink-faint); margin: 0 0 var(--s1); }
.toc-rule { border: 0; border-top: 2px solid var(--rule-strong); margin: 0 0 var(--s2); }
.toc-chapter > summary { display: flex; align-items: baseline; gap: var(--s2);
  padding: var(--s2) 0; cursor: pointer; list-style: none; }
.toc-chapter > summary::-webkit-details-marker { display: none; }
.toc-chapter > summary i { font-family: var(--font-display); font-style: normal; font-weight: 700;
  color: var(--accent); min-width: 2rem; }
.toc-chapter > summary em { font-style: normal; }
.toc-chapter > summary .dots { flex: 1; border-bottom: 1px dotted var(--ink-ghost);
  transform: translateY(-.25rem); }
.toc-chapter > summary u { text-decoration: none; font-family: var(--font-display);
  font-size: var(--fs-xs); color: var(--ink-faint); }
.toc-chapter ul.toc { margin: 0 0 var(--s3) 2.5rem; }
```

- [ ] **Step 5: Run the tests**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected OK.

- [ ] **Step 6: Commit**

```bash
git add parody_web/templates/parody_web/index.html parody_web/static/parody_web/css/book.css \
        parody_web/tests.py
git commit -m "index: typeset table of contents with collapsible chapters"
```

---

### Task 11: Chapter, subject index, search and remaining pages

**Files:**
- Modify: `chapter.html`, `book_index.html`, `search.html`, `systems.html`, `errata.html`,
  `registration/login.html`, `book.css`, `content.css`

- [ ] **Step 1: Update each template's chrome**

Every page keeps its `{% block body %}` content but drops any inline `style=` attributes and any
markup that duplicated the old floating header. `book_index.html` and `search.html` get
`{% block side %}` left empty (they are not chapter-scoped), so they render as a single centred column
via the existing grid.

- [ ] **Step 2: Restyle the subject index and search results**

In `content.css`, point `.book-index`, `.index-letter`, `.index-entry`, `.search-form`,
`.search-results`, `.search-hit`, `.snippet`, `.search-count` at the tokens, and set index letters and
result numbers in `var(--font-display)` while entry and snippet text stays serif.

- [ ] **Step 3: Run the tests**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran )"` — expected OK, all pre-existing
`BookIndexTests` and `SearchInsideTests` still passing.

- [ ] **Step 4: Commit**

```bash
git add parody_web/templates parody_web/static/parody_web/css
git commit -m "pages: chapter, subject index, search, systems, errata and login on the new system"
```

---

# Phase 5 — Verification and release

### Task 12: Full verification pass

- [ ] **Step 1: Run the whole suite**

Run: `python runtests.py 2>&1 | grep -E "^(OK|FAILED|Ran |ERROR)"`
Expected: all tests pass, count ≥ 110.

- [ ] **Step 2: Screenshot the matrix**

Start the example site (`cd example_site && python manage.py runserver 8765`). Capture index,
chapter, section, subject index and search at 1440px / 1100px / 390px, in light and dark, as anon and
as owner. Confirm at each width: no horizontal scroll, the reading measure is unchanged, the rail then
the sidebar drop in that order, and the contents disclosure still reaches the chapter contents.

- [ ] **Step 3: Check the regression-prone behaviours**

- An equation cross-ref lands the equation below the masthead (#297/#306).
- A subject-index deep link lands its term below the masthead.
- The `\tag` equation numbers render and inherit theme colour in dark mode.
- Preview gating still shows the truncated excerpt + sign-in gate to anonymous visitors.
- The edition switcher and draft banner still appear for a draft edition viewed as owner.

- [ ] **Step 4: Accessibility audit**

Tab through a section page: masthead links, contents disclosure, theme toggle, sidebar, body links,
rail, pager, footer — every stop must show a visible focus ring. Confirm the toggle has an accessible
name and that `prefers-reduced-motion` suppresses the equation flash.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A && git commit -m "fix: issues found in the verification pass"
```

---

### Task 13: Merge and release to rtcbook.org

Reduced chain — parody-web-only change, so steps 1, 2 and 5 of the full release chain are skipped.

- [ ] **Step 1: Bump the version**

`pyproject.toml`: `version = "0.30.0"` (feature release over 0.29.1).

```bash
git add pyproject.toml && git commit -m "0.30.0: redesigned book site (task #496)"
```

- [ ] **Step 2: Merge to main and push**

```bash
git checkout main && git merge --no-ff web-visual-design -m "Merge branch 'web-visual-design': redesigned book site" && git push origin main
```

This push also carries the two commits held back earlier (breadcrumb chapter rung, `.gitignore`).

- [ ] **Step 3: Publish parody-web to PyPI**

```bash
rm -rf dist && uv build && uvx twine upload dist/*
```

Credentials are in `~/.pypirc`; twine is not installed, hence `uvx`. CI does not auto-publish.

- [ ] **Step 4: Bump the deployment pin**

In `~/rtcbook-web/requirements.txt`, change `parody-web>=0.29.1,<0.30` to
`parody-web>=0.30.0,<0.31`, then commit and push `main` — the push triggers the Deploy workflow.

- [ ] **Step 5: Expect the propagation race**

PyPI's simple index propagates unevenly across Fastly edges and the EC2 box (us-west-2) lags behind a
local `curl` — a local check showing the new version is **not** evidence the box can see it. Budget
5+ minutes after upload. If the deploy fails with "No matching distribution found", re-dispatch it
(no new commit needed):

```bash
gh workflow run Deploy -R rtc-book/rtcbook-web
```

- [ ] **Step 6: Watch the deploy**

```bash
gh run watch -R rtc-book/rtcbook-web
```

- [ ] **Step 7: Verify live**

Load rtcbook.org and confirm: the new masthead and typeset contents render, fonts load (not fallback),
dark mode follows the OS and the toggle overrides it, a section page shows the sidebar, and an
equation cross-ref lands correctly. Check one preview section as an anonymous visitor.

---

## Self-Review

**Spec coverage.** Stylesheet split → Task 1. Fonts → Task 3. Theming → Task 2. Color incl. the
`--ink-faint`/`--ink-ghost` split → Task 4. Dark mode + image panels → Task 5. Type rule → Task 4.
Layout ladder → Task 8. Sidebar + rail → Task 9. Landing page → Task 10. Component sweep → Tasks 6, 7,
11. Syntax highlighting dark variant → Task 7. Accessibility → Tasks 4, 8, 12. Testing → every task
plus Task 12. Phasing → the five phase headings. Release → Task 13.

**Deviation from the spec, recorded deliberately.** The spec specified a *context processor* for theme
CSS. This plan uses a template tag plus `AppConfig.ready()` validation instead: a context processor
would force every consuming deployment to edit its `TEMPLATES` setting, which an installable app must
not require. Startup validation is preserved, so the spec's intent ("fails loudly, not silently") is
met.

**Type consistency.** `_chapter_nav(book, chapter, current=None)` and `_page_anchors(html)` are
defined in Task 9 and used only there. Context keys `chapter_nav` / `page_anchors` match between view,
template and test. Token names in Task 4 match every consumer in Tasks 5–11. `--head-h` is introduced
in Task 8 and consumed by Task 9's sticky offsets.
