#!/usr/bin/env bash
# Server-side deploy for one book site. Invoked on the target instance by
# GitHub Actions via SSM SendCommand (see .github/workflows/deploy.yml).
#
# Idempotent and book-agnostic: every book-specific value comes from the
# per-site env file (SITE_ENV, default /etc/parody-book-host/site.env), so the
# SAME repo + script deploys any book site. Update the host once, redeploy all.
#
# site.env provides (see deploy/site.env.example):
#   APP_DIR, VENV, SERVICE                — where the app + venv live, systemd unit
#   BOOK_SLUG                             — which book this site serves
#   CONTENT_REPO, ARTIFACT_ASSET          — GitHub repo + release asset to import
#   MEDIA_ASSET                           — optional media zip asset
#   RELEASE_TAG                           — release to pull (default: latest)
#   BOOKSITE_* / DATABASE_URL / GH_TOKEN  — app settings + a token for private repos
set -euo pipefail

SITE_ENV="${SITE_ENV:-/etc/parody-book-host/site.env}"
[ -f "$SITE_ENV" ] && set -a && . "$SITE_ENV" && set +a

: "${APP_DIR:?set APP_DIR in site.env}"
: "${BOOK_SLUG:?set BOOK_SLUG in site.env}"
VENV="${VENV:-$APP_DIR/.venv}"
SERVICE="${SERVICE:-parody-book-host}"
GIT_REF="${GIT_REF:-origin/main}"

echo "==> deploy $BOOK_SLUG to $APP_DIR @ $GIT_REF"
cd "$APP_DIR"
git fetch --quiet origin
git reset --hard "$GIT_REF"

"$VENV/bin/pip" install -q -r requirements.txt
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py collectstatic --noinput

# Pull the book's content artifact (+ media) from its content-repo release.
if [ -n "${CONTENT_REPO:-}" ] && [ -n "${ARTIFACT_ASSET:-}" ]; then
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  TAG_ARGS=(); [ -n "${RELEASE_TAG:-}" ] && TAG_ARGS=("$RELEASE_TAG")
  GH_TOKEN="${GH_TOKEN:-}" gh release download "${TAG_ARGS[@]}" \
    --repo "$CONTENT_REPO" --pattern "$ARTIFACT_ASSET" --dir "$TMP" --clobber
  if [ -n "${MEDIA_ASSET:-}" ]; then
    GH_TOKEN="${GH_TOKEN:-}" gh release download "${TAG_ARGS[@]}" \
      --repo "$CONTENT_REPO" --pattern "$MEDIA_ASSET" --dir "$TMP" --clobber || true
    [ -f "$TMP/$MEDIA_ASSET" ] && unzip -oq "$TMP/$MEDIA_ASSET" \
      -d "${BOOKSITE_MEDIA_ROOT:?set BOOKSITE_MEDIA_ROOT for media}"
  fi
  # optional site-provided extra media (icons, cover, errata figures)
  [ -d "$APP_DIR/deploy/extra-media" ] && \
    cp -f "$APP_DIR/deploy/extra-media"/* "${BOOKSITE_MEDIA_ROOT}/" 2>/dev/null || true
  PREVIEW_ARG=""
  [ -f "$APP_DIR/deploy/preview-hashes.txt" ] && \
    PREVIEW_ARG="--preview-hashes $APP_DIR/deploy/preview-hashes.txt"
  REFS_ARG=""
  [ -f "$APP_DIR/deploy/references.json" ] && \
    REFS_ARG="--references $APP_DIR/deploy/references.json"
  COVER_ARG=""
  [ -f "$APP_DIR/deploy/extra-media/cover.jpg" ] && COVER_ARG="--cover cover.jpg"
  ERRATA_ARG=""
  [ -f "$APP_DIR/deploy/errata.html" ] && ERRATA_ARG="--errata $APP_DIR/deploy/errata.html"
  "$VENV/bin/python" manage.py import_artifact "$TMP/$ARTIFACT_ASSET" --slug "$BOOK_SLUG" $PREVIEW_ARG $REFS_ARG $COVER_ARG $ERRATA_ARG
else
  echo "==> no CONTENT_REPO/ARTIFACT_ASSET set; skipping content import"
fi

sudo systemctl restart "$SERVICE"
echo "==> deployed $BOOK_SLUG"
