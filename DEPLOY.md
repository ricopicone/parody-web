# Deploying the book-host (rtcbook.org)

The book-host is a small dynamic Django app (it needs a database + login, because
it holds the full book and gates the private sections). The current rtcbook.org
is a static Jekyll/Pages site; this replaces it. The app is platform-agnostic —
it uses a `Procfile`, `DATABASE_URL`, and WhiteNoise, so it runs on Heroku,
Render, Railway, Fly (buildpacks), or a Dokku/EC2 box.

## 1. Provision a host + Postgres

Create the app and attach a Postgres database so `DATABASE_URL` is set. (sqlite
is fine locally but ephemeral on most hosts — auth/content would vanish on
restart.)

## 2. Set environment variables

| var | value |
|---|---|
| `BOOKSITE_SECRET_KEY` | a long random string |
| `BOOKSITE_DEBUG` | `0` |
| `BOOKSITE_ALLOWED_HOSTS` | `rtcbook.org,www.rtcbook.org` |
| `BOOKSITE_CSRF_TRUSTED_ORIGINS` | `https://rtcbook.org,https://www.rtcbook.org` |
| `BOOKSITE_BOOK_SLUG` | `real-time-computing` |
| `BOOKSITE_MEDIA_ROOT` | a persistent path / volume for figures |
| `DATABASE_URL` | (set by the Postgres add-on) |

`release` runs `migrate` + `collectstatic` automatically (see `Procfile`).

## 3. Create the owner account

```bash
<run on the host>  python manage.py createsuperuser
```

This is the **only** account. The public sees only `online_only` sections; the
owner sees the whole book. There is no public registration.

## 4. Build + import the book artifact

In the rtc content repo (parody installed):

```bash
parody build . rtc.json --media-root build_media   # FULL artifact
# (or: parody build . rtc.json --online-only ...  to NOT hold the full text)
```

Get `rtc.json` + the `build_media/media/` tree onto the host (release asset,
object storage, or committed), then:

```bash
python manage.py import_artifact rtc.json --slug real-time-computing
# place the media tree at BOOKSITE_MEDIA_ROOT
```

Re-import is idempotent. Recommended pipeline: the rtc content repo's CI builds
the artifact + `media.zip` on tag; a small deploy step here fetches, imports,
and unpacks them (mirrors homepage-django's `content-manifest` approach).

## 5. DNS

Point `rtcbook.org` (and `www`) at the new host and provision TLS. Remove the
old GitHub/GitLab Pages CNAME for the domain once the new host serves.

## 6. Verify

- `https://rtcbook.org/` lists only the online-only sections (anonymous).
- A private section redirects to `/accounts/login/`.
- After owner sign-in, the full table of contents and all sections render.

## Owner-only checklist (cannot be automated from here)

- [ ] host + Postgres provisioned
- [ ] env vars set (esp. `SECRET_KEY`, `ALLOWED_HOSTS`, `DEBUG=0`)
- [ ] owner superuser created
- [ ] artifact + media imported/staged
- [ ] DNS moved to the new host + TLS
