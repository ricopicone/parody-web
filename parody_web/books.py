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

    Resolved per call rather than cached at import: override_settings has to
    take effect in tests — the same reasoning as access.get_policy.
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
    # order_by() before distinct(): Book.Meta orders by (slug, edition_order),
    # and an ordering column joins the SELECT, so DISTINCT would otherwise see
    # one row per *edition* and call a single book ambiguous.
    slugs = sorted(set(Book.objects.order_by().values_list("slug", flat=True)))
    if not slugs:
        raise Http404("no book imported")
    if len(slugs) > 1:
        # Editions of one book are fine — several *books* are not: picking one
        # arbitrarily would serve the wrong book rather than fail.
        raise ImproperlyConfigured(
            f"several books are imported ({', '.join(slugs)}) but neither "
            f"PARODY_WEB_BOOK_RESOLVER nor BOOK_SLUG says which to serve")
    return slugs[0]
