# parody-book-host

A minimal, standalone Django site that serves a **parody artifact** as a public
book — e.g. the partial *Real-Time Computing* book at
[rtcbook.org](https://rtcbook.org).

It is deliberately small and decoupled from the homepage monolith: it has no
grades, enrollment, or annotations. It imports **one** artifact and renders it.

**Access model.** It imports the *full* artifact and gates by section: the
public sees only `online_only` sections (the openly-licensed subset); the
**private parts** of the book require login, and only the owner has an account.
So one deployment serves both the public partial book and — to you — the whole
thing. (If you would rather the full text never touch this database at all,
import the partial `parody build --online-only` artifact instead; then there
are simply no private sections to gate.)

## Why a Django host (not a static site)

Parody artifact `html` is Django-template-flavored — it embeds `{% media %}`,
`{% static %}`, `{% cite %}` etc. (the same tags ricopic.one resolves at view
time). This host renders that html **natively** through the Django template
engine (`book.templatetags.book_tags.render_book`), so there is no second,
lossy tag-resolution implementation to maintain.

## Usage

```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # the owner (the only account)

# Build the FULL artifact in the content repo, then import it here:
#   (in the rtc content repo)  parody build . rtc.json --media-root .
python manage.py import_artifact /path/to/rtc.json --slug real-time-computing
# Stage the artifact's media/ tree at BOOKSITE_MEDIA_ROOT (default ./media).

python manage.py runserver         # http://127.0.0.1:8000
```

The public sees only `online_only` sections; sign in at `/accounts/login/` to
read the whole book.

## Deploy

Platform-agnostic basics: [`DEPLOY.md`](DEPLOY.md). The supported production
path is **AWS via SSM + GitHub Actions**, designed for **multi-book reuse** (one
repo, deployed per book; update once, redeploy all): [`deploy/AWS.md`](deploy/AWS.md).

Re-running `import_artifact` is idempotent (upsert by slug; rows absent from the
artifact are pruned).

## Configuration (env vars)

- `BOOKSITE_SECRET_KEY` — set in any real deployment.
- `BOOKSITE_DEBUG` — `1` (default) / `0`.
- `BOOKSITE_ALLOWED_HOSTS` — comma-separated (e.g. `rtcbook.org,www.rtcbook.org`).
- `BOOKSITE_BOOK_SLUG` — which imported book is the site root (defaults to the
  only/first book).
- `BOOKSITE_MEDIA_ROOT` — where the artifact's `media/` tree lives.

## What it renders

- The book index (table of contents), with editions/ISBN/companion metadata —
  the public TOC lists only `online_only` sections; the owner sees all.
- Each section: the rendered html, plus a per-section **Online resources** block
  (`online_resources`) when present. Private (non-`online_only`) sections are
  served only to the signed-in owner; anonymous requests redirect to login.

## Status

Built 2026-06-14 (parody task #267). Renders the rtc artifact end to end with
section-level auth gating (public = online-only subset; owner = full book). Not
yet deployed to rtcbook.org (DNS/hosting/owner-account = follow-up). Bibliography
for `{% cite %}` currently renders `[key]`; wire citeproc/a .bib for full
citations when needed.
