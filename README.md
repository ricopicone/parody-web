# parody-web

A reusable **Django app** that serves a [parody](https://github.com/ricopicone/parody)
build artifact as a public book site, with section-level auth gating. It's the
*web* surface of the parody ecosystem:

- **`parody`** — core: builds the artifact (and the print/LaTeX side, for now)
- **`parody-web`** — *this*: renders an artifact as a website
- *(future)* `parody-print` — if/when the LaTeX side is split out of core

You `pip install parody-web` into a thin per-book Django project; the package is
generic, so one codebase serves every book site. Each book differs only by
config + content. First site: the partial *Real-Time Computing* book at
[rtcbook.org](https://rtcbook.org).

## Access model

The site imports the **full** artifact and gates by section: the public sees
only `online_only` sections (the openly-licensed subset); the **private** parts
require login, and only the owner has an account. One deployment serves both the
public partial book and — to the owner — the whole thing. (If you'd rather the
full text never touch the database, import the partial `parody build
--online-only` artifact instead — then there are no private sections.)

## Why a Django app (not a static site)

Parody artifact `html` is Django-template-flavored — it embeds `{% media %}`,
`{% static %}`, `{% cite %}` etc. This app renders it **natively** through the
Django template engine (`parody_web.templatetags.parody_web.render_book`), so
there's no second, lossy tag-resolution renderer to maintain.

## Use it in a project

```python
# settings.py
INSTALLED_APPS = [..., "parody_web"]
BOOK_SLUG = "real-time-computing"     # which imported book is the site root
```
```python
# urls.py
urlpatterns = [path("", include("parody_web.urls")), ...]
```
```bash
pip install parody-web
python manage.py migrate
python manage.py createsuperuser                       # the owner (only account)
python manage.py import_artifact rtc.json --slug real-time-computing
```

Provides: `Book`/`Chapter`/`Section` models, the `import_artifact` command
(upsert-by-slug, idempotent), index + section views, templates (override them in
your project), and the rendering template tags. Reads `settings.BOOK_SLUG`,
`MEDIA_URL`, `LOGIN_URL`.

A ready-to-copy thin project — settings, urls, Procfile, and AWS/SSM deploy glue
— lives in [`example_site/`](example_site/); generate a new book site from it.

## Data-entry tables

A lab manual authors an observation table as `::: {.editable-table}`. On the
site a signed-in reader types their readings into it, **Save** keeps them, and
they are still there next visit. A reader who is not signed in sees the table
with its inputs disabled and a line saying why.

**Download JSON** gives back that one table; **All my tables** (`/tables.json`)
gives every table in the book the reader has put something in — a term's
measurements in one file instead of a scavenger hunt through a dozen labs.

The file is the table as it appears on the page: a `columns` header row, and
`rows` as one flat record per row keyed by those headers, including the column
the row labels live in. Empty cells are `""` rather than missing, so a
half-filled table still loads as a table:

```python
import json, pandas as pd
d = json.load(open("mechatronics-lab-manual-lab-test-observations.json"))
df = pd.DataFrame(d["rows"], columns=d["columns"])
```

Each file also carries which book, which section (title, number and URL) and
when it was exported, and names its shape in `format` (`parody-table/1`,
`parody-tables/1`) so a later change to that shape is a new number rather than
a silent break.

Values are stored per cell, keyed to the reader and to `Section.key` rather
than to a row that re-import would delete — a term's measurements outlive the
book being rebuilt. Nothing is needed from the host but `migrate`.

## Serving a book from your own project

A host project (a course site, say) can serve a parody book while keeping its
own readers, gating, and per-user features. See
**[Host integration](docs/host-integration.md)** for the four seams: imported
per-exercise solutions/problems, the pluggable access policy
(`PARODY_WEB_ACCESS_POLICY`), the per-user overlay include points, and the
`Section.key` join key.

## Develop

```bash
pip install -e .
python runtests.py            # standalone test suite (tests/settings.py)
```

## Deploy

AWS via SSM + GitHub Actions, designed for **reuse across book projects**: each
book site is a small repo (copied from `example_site/`) that pins this package
and calls the shared reusable workflow (`deploy-reusable.yml`) — improve the
renderer or the deploy once, every site picks it up. Runbook:
[`example_site/deploy/AWS.md`](example_site/deploy/AWS.md).

## Status

`0.x` — interfaces may change. Renders the rtc artifact end to end with
section-level auth gating; 9 tests. `{% cite %}` currently renders `[key]`
(wire citeproc/a .bib for full citations). Not yet published to PyPI or
deployed to rtcbook.org (owner steps).
