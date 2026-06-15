"""Settings for the parody book-host — a minimal, standalone Django site that
renders a parody artifact (e.g. the partial rtc book at rtcbook.org).

It deliberately serves ONE book and imports only the artifact it is given, so a
public deployment of a copyright-restricted book can be fed the partial
(``parody build --online-only``) artifact and never hold the full text.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Dev default; set BOOKSITE_SECRET_KEY in any real deployment.
SECRET_KEY = os.getenv("BOOKSITE_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = os.getenv("BOOKSITE_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.getenv("BOOKSITE_ALLOWED_HOSTS", "*").split(",")

# Which book slug to serve as the site root (defaults to the only/first book).
BOOK_SLUG = os.getenv("BOOKSITE_BOOK_SLUG", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "book",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves static files directly (no separate static host needed).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "booksite.urls"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# Auth: private (non-online-only) sections require login. Only the owner has an
# account (create one superuser); the public sees only online-only sections.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

WSGI_APPLICATION = "booksite.wsgi.application"

# Postgres in production via DATABASE_URL (auth + content must persist across
# restarts); sqlite is the zero-config local fallback.
if os.getenv("DATABASE_URL"):
    import dj_database_url
    DATABASES = {"default": dj_database_url.config(
        conn_max_age=600, ssl_require=True)}
else:
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }}

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("BOOKSITE_MEDIA_ROOT", BASE_DIR / "media"))

# Behind a TLS-terminating proxy in production; harden cookies + redirects.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.getenv("BOOKSITE_SSL_REDIRECT", "1") == "1"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    CSRF_TRUSTED_ORIGINS = [
        o for o in os.getenv("BOOKSITE_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
