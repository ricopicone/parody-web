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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("BOOKSITE_MEDIA_ROOT", BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
