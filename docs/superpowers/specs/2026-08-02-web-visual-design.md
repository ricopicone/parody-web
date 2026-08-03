# Web visual design — parody-web

**Task:** parody #496 — "Improve web visual design"
**Date:** 2026-08-02
**Repo:** parody-web (all changes; no parody changes, no artifact schema change)

## Problem

parody-web renders a book site that is functionally complete and visually undesigned. Every style
lives in a single 235-line inline `<style>` block in `base.html`: no tokens, no stylesheet file, no
dark mode, no masthead, no footer. Three unrelated palettes coexist — default browser-blue links, a
`#7a6ff0` purple accent, and a warm-taupe box accent explicitly marked in code as a placeholder
"until real theme colours land". Section pages give a reader no sense of position within a chapter,
which matters because readers arrive mid-book from search and from the QR codes printed in the book.
The landing page dumps every chapter *and every section* as one flat list.

## Goals

- One deliberate visual identity that any parody book inherits, with a small set of per-book overrides.
- A real design-token layer: color, type, space, rules — light and dark.
- Reading affordances: masthead, chapter navigation, footer, and a landing page that reads as a book's
  table of contents.
- All existing content components retuned to the system, with nothing regressing.

## Non-goals

- No changes to parody, the artifact schema, or the print/PDF path.
- No cross-repo release chain (see "Theming" below).
- No JS framework, no CSS build step, no node toolchain. parody-web stays a plain installable Django app.
- Not redesigning content semantics — only presentation. Numbering, cross-refs, and gating behavior are unchanged.

## Decisions

Settled during brainstorming, with the reasoning worth keeping:

| Decision | Choice | Why |
|---|---|---|
| Ambition | Full redesign | Chosen over polish-only; the site needed structure, not just paint. |
| Identity | Strong opinionated default + per-book hooks | parody-web is reused per book; RTC gets an override, not a bespoke skin. |
| Direction | Editorial-technical with typewriter display | Serif body for long-form reading; monospace for structure. |
| Display face | **Courier Prime** (OFL) | A true typewriter; one family covers headings, labels *and* code listings, which this book is full of. |
| Body face | **Source Serif 4** (OFL) | Comfortable at length, pairs without competing. |
| Accent | **Indigo `#3550c8`** | Cool against warm paper — the tension is what keeps the typewriter look from tipping into nostalgia. |
| Dark mode | Yes, images on light panels | See "Dark mode" — never mangles a figure. |
| Reading chrome | Sidebar + margin rail | Fixes the position problem; rail carries the T1/D1 badges that already float right. |
| Landing page | Typeset contents | Solves the flat-dump problem rather than restyling it. |
| Theme config | parody-web Django setting | Theme is a host concern; keeps this task in one repo, no republish to retune an accent. |

### Type rule

Derived from a stress test against the four longest real RTC chapter titles (up to 94 characters):
**monospace for numbers, labels, and headings; serif for anything that runs long** — contents entries,
breadcrumb text, list text, prose. Monospaced running text at list size is where the identity breaks.
Chapter headings wrap to three lines instead of two; accepted, and it reads as better hierarchy.

## Architecture

### Stylesheets

Extract the inline block into `parody_web/static/parody_web/css/`:

- `tokens.css` — custom properties only; `:root` (light), `prefers-color-scheme: dark`, and
  `:root[data-theme="dark"] / [data-theme="light"]` overrides so a manual toggle wins in both directions.
- `book.css` — reset, typography, page layout, masthead, sidebar, rail, footer, nav.
- `content.css` — book-content components: figures, tables, boxes, listings, math, index, search.

`base.html` retains only: font preloads, the three `<link>`s, the validated theme `<style>`, and the
no-flash theme script.

### Fonts

Self-hosted WOFF2, latin-subset, vendored under `parody_web/static/parody_web/fonts/`:

- Courier Prime — Regular, Bold, Italic, Bold Italic (4 files, SIL OFL)
- Source Serif 4 — variable roman + variable italic (2 files, SIL OFL)

`font-display: swap`. Preload exactly two: Source Serif 4 roman and Courier Prime Bold. Same-origin,
so no CSP work; `collectstatic` already runs in the deploy. Licenses ship alongside the font files.

### Theming

`settings.PARODY_WEB_THEME`, shaped `{"light": {token: value}, "dark": {token: value}}`. A context
processor validates and emits a `:root{}` / `:root[data-theme="dark"]{}` block into `<head>`.

Validation is strict and fails loudly — `ImproperlyConfigured` at startup, not silent fallback:

- Token names must appear in `ALLOWED_THEME_TOKENS` (accent, accent-soft, accent-wash, paper,
  paper-sunk, ink, ink-muted, font-display, font-body).
- Values must match a strict pattern: a hex color, or a font-family list of quoted names plus a generic.

This is what keeps a deployment from injecting arbitrary CSS through a settings dict.

## Color

Faint text was corrected during design: the intended `#8d8a80` scores only 3.17:1 on the paper and
fails AA for normal text. It splits in two — a darker token for text, the original kept for
non-text decoration only (leader dots, hairlines).

| Token | Light | Dark | Note |
|---|---|---|---|
| `--paper` | `#fbf9f5` | `#16171a` | page |
| `--paper-sunk` | `#f4f0e7` | `#1e2025` | code blocks, tinted boxes |
| `--paper-panel` | `#ffffff` | `#ffffff` | images only — deliberately light in both themes |
| `--ink` | `#1c1b19` | `#e8e6e1` | 15.6:1 / 14.5:1 |
| `--ink-muted` | `#56534c` | `#a8a49c` | 7.6:1 |
| `--ink-faint` | `#6f6c64` | `#78756e` | 4.8:1 — text |
| `--ink-ghost` | `#8d8a80` | `#5a5852` | decoration only, never text |
| `--rule` | `#e8e3d9` | `#2c2e34` | hairlines |
| `--accent` | `#3550c8` | `#93a6f5` | 6.3:1 / 7.8:1 |
| `--accent-soft` | `#ccd4f3` | `#2f3a63` | link underlines |
| `--accent-wash` | `#eef1fb` | `#1b1f2e` | tinted panels |

### Dark mode

A refinement on what was originally proposed, and the spec follows the refinement: **only images need
light panels.** Tables, display math, and code are live text that recolor correctly, and forcing them
onto light panels in dark mode would look worse, not better. So `--paper-panel` (always light, both
themes) applies to `img`, `figure > img`, and image-rendered tables/algorithms
(`figure[id^="tbl:"] img`, `figure[id^="al:"] img`) — images with white or transparent backgrounds
baked in by LaTeX. Everything else follows the theme.

Toggle: a masthead button setting `data-theme` on `<html>` plus `localStorage["parody-theme"]`;
absent means follow the system. An inline head script applies it before first paint.

Dark variants are also needed for two hardcoded light values that exist today: the syntax-highlighting
palette, and the `#fdf2b8` equation-target flash.

## Type

```
--font-display: "Courier Prime", "Courier New", monospace;   /* headings, numbers, labels, code, UI */
--font-body:    "Source Serif 4", Charter, Georgia, serif;   /* prose, lists, breadcrumb text */

--fs-xs .72rem   labels, badges          --fs-h3  1.35rem
--fs-sm .82rem   captions, meta          --fs-h2  1.6rem
--fs-base 1.0625rem  body (17px)         --fs-h1  1.9rem
--fs-lg 1.25rem                          --measure 34rem
```

Body line-height 1.62; headings 1.18 with `-0.03em` tracking (Courier Prime sets loose by default).

## Layout

### Section page

Grid: `sidebar | column | rail`, collapsing in four steps:

| Width | Layout |
|---|---|
| ≥1440px | sidebar + column + rail |
| 1180–1440 | sidebar + column; rail folds, T1/D1 badges float beside the column as today |
| 900–1180 | column only; chapter contents move into the masthead disclosure |
| <900 | single column, condensed masthead, contents in a slide-over, stacked pager |

The reading measure is constant at every step — the rail costs it nothing, because sidebar (200px) +
rail (144px) + gaps is ~400px of a 1440px viewport.

**Sidebar** — the chapter's sections, current one marked. No new queries: `section_detail` already
computes `_all_sections_ordered(book)`, so siblings are a filter on data in hand. Extract a shared
`_chapter_nav(book, chapter, current=None)` helper used by both `section_detail` and `chapter_detail`.

**Rail** — T1/D1 version badges and an "on this page" list of subsection anchors, derived server-side
from the rendered section HTML (`<h2 id=…>`/`<h3 id=…>`), not client-side; JS-free is more robust and
directly testable.

### Landing page

Cover, title block, buy/search/printed-code controls, then the contents typeset as a book's TOC —
mono numerals, leader rules, chapters collapsed via `<details>` with the first expanded. Both the
search box and the printed-code box stay: the book's QR codes point here.

### Masthead and footer

Sticky slim masthead: book title (home), contents disclosure, index, search, edition switcher, theme
toggle. The contents disclosure is present at every width — below 1180px it simply becomes the only
route to the chapter contents, once the sidebar has dropped. A real footer carries edition, copyright,
and owner sign-in — replacing today's naked floating `owner sign in` div.

## Component sweep

Every component currently in the inline block, retuned to tokens: example boxes (taupe placeholder
retires), Further Reading boxes, sign-in gate, code box, continue/download buttons, T1/D1 version
icons, draft banner, booktabs tables incl. grouped headers and `.cmid` segments, subfigures,
subtables, figure/listing captions, rights placeholders, subject-index columns, search results and
`<mark>`, key/menu chips, preview mask, equation-target flash, syntax highlighting (+ dark variant).

## Accessibility

- Every text token pair meets WCAG AA in both themes; the table above records measured ratios.
- Visible focus states throughout (none exist today).
- Sidebar, contents disclosure, and theme toggle keyboard-operable; disclosure uses native `<details>`
  or a button with correct `aria-expanded`.
- `prefers-reduced-motion` honored by the equation-target flash.

## Testing

The 95 existing tests must stay green. New tests:

- stylesheets and font preloads present in `<head>`
- theme setting emits the expected `:root` tokens; an unknown token name and a malformed value each
  raise `ImproperlyConfigured`
- section page renders chapter siblings with exactly one marked current
- "on this page" anchors extracted from section HTML
- landing page emits collapsed `<details>` per chapter, first expanded
- masthead and footer present; owner sign-in moved out of the floating div

Visual verification: run `example_site`, screenshot index / chapter / section / subject index / search
at 3 widths × light and dark × owner and anon.

## Phases

1. **Foundation** — extract stylesheets and tokenize *the existing values*, theme setting + validation,
   dark-mode plumbing. Deliberately no visual change: this phase is a pure refactor.
2. **Identity** — fonts, type scale and palette applied; every content component onto tokens, incl.
   the syntax-highlighting dark variant.
3. **Chrome** — masthead, footer, sidebar, rail, responsive ladder, view helpers.
4. **Pages** — landing page typeset contents, chapter page, subject index, search.
5. **Verification** — full test pass, screenshots, contrast and keyboard audit.

Each phase is independently reviewable and leaves the site working.

## Risks

- **Courier Prime at display size on long titles** — validated against the four longest real chapter
  titles; holds, given the type rule above.
- **MathJax color inheritance** — CHTML renders with `currentColor` and should follow the theme;
  verify `\tag` equation numbers specifically, since they are injected by `numbering.py`.
- **Sticky masthead vs. existing scroll anchors** — `.eqanchor` and `.index` set `scroll-margin-top`
  (3rem/5rem) tuned for no masthead; both must be re-tuned to the masthead height or the equation
  cross-ref landing from #297/#306 regresses.
- **Diff size** — mitigated by phasing; phase 1 is a pure refactor with no visual change, which makes
  the subsequent visual diffs readable.
