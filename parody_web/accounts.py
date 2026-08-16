"""Who the reader is, for the masthead's account chip.

parody-web knows a reader only as `request.user`. A host knows far more —
homepage-django has a Profile with a processed avatar — but parody-web must
not import a host's models, so the picture arrives through one setting:

    PARODY_WEB_AVATAR = "core.avatars.avatar_for"   # callable(user) -> url|None

Same seam as PARODY_WEB_ACCESS_POLICY and PARODY_WEB_BOOK_RESOLVER. Unset
means no picture, and the chip falls back to an initial — which is why the
setting is optional rather than the feature being conditional on it.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string


def get_avatar_resolver():
    """The configured callable, or None."""
    path = getattr(settings, "PARODY_WEB_AVATAR", "")
    if not path:
        return None
    try:
        return import_string(path)
    except ImportError as exc:
        raise ImproperlyConfigured(
            f"PARODY_WEB_AVATAR = {path!r} could not be imported: {exc}"
        ) from exc


def avatar_url(user):
    """A picture for this reader, or None.

    A host resolver that raises is treated as "no picture": a broken avatar
    must not take the whole page down with it.
    """
    resolver = get_avatar_resolver()
    if resolver is None or not getattr(user, "is_authenticated", False):
        return None
    try:
        return resolver(user) or None
    except Exception:  # noqa: BLE001
        return None


def display_name(user):
    """What to call the reader: their real name if the host has one."""
    if not getattr(user, "is_authenticated", False):
        return ""
    full = (user.get_full_name() or "").strip() if hasattr(user, "get_full_name") else ""
    return full or user.get_username()


def initial(user):
    """One letter for the fallback chip."""
    name = display_name(user)
    return name[:1].upper() if name else "?"
