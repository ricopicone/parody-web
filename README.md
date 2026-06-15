# parody-book-host

A minimal, standalone Django site that serves a **parody artifact** as a public
book — e.g. the partial *Real-Time Computing* book at
[rtcbook.org](https://rtcbook.org).

It is deliberately small and decoupled from the homepage monolith: it has no
auth, grades, enrollment, or annotations. It imports **one** artifact and
renders it. Feed it the *partial* artifact (`parody build --online-only`) so a
copyright-restricted book can be published publicly without the full text ever
entering this database.

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

# Build the partial artifact in the content repo, then import it here:
#   (in the rtc content repo)  parody build . rtc.json --online-only --media-root .
python manage.py import_artifact /path/to/rtc.json --slug real-time-computing
# Stage the artifact's media/ tree at BOOKSITE_MEDIA_ROOT (default ./media).

python manage.py runserver         # http://127.0.0.1:8000
```

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

- The book index (table of contents), with editions/ISBN/companion metadata.
- Each section: the rendered html, plus a per-section **Online resources** block
  (`online_resources`) when present.
- The artifact decides what is published: only `online_only` sections (and any
  section's online-resources) appear in a `--online-only` artifact.

## Status

Built 2026-06-14 (parody task #267). Renders the rtc partial artifact (online-only
sections + online-resources) end to end. Not yet deployed to rtcbook.org
(DNS/hosting is a follow-up). Bibliography for `{% cite %}` currently renders
`[key]`; wire citeproc/a .bib for full citations when needed.
