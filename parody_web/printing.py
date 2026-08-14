"""Per-section print PDFs, sliced on demand from the full-book PDF.

The print PDF is NOT part of the media tree: nginx serves that with no auth,
and some books gate sections behind preview/owner rules. It lives in its own
root and reaches readers only through a view that has asked the access policy
first.

Slices are cut on demand and cached. The cache path carries the source PDF's
sha256, so a rebuilt (repaginated) book writes to a fresh directory and a stale
slice can never be served — there is no cache to bust by hand.

`pypdf` is an optional extra (`parody-web[print]`). Without it every entry
point here reports "unavailable" and the site renders no PDF affordance at all,
rather than erroring.
"""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def has_pypdf():
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


def print_root():
    """Directory holding the full-book PDFs, or None when unconfigured."""
    root = getattr(settings, "PARODY_WEB_PRINT_ROOT", "")
    return Path(root) if root else None


def print_cache_root():
    """Where slices are cached; defaults to ``.cache`` inside the print root."""
    cache = getattr(settings, "PARODY_WEB_PRINT_CACHE", "")
    if cache:
        return Path(cache)
    root = print_root()
    return (root / ".cache") if root else None


def xaccel_prefix():
    """nginx internal location that maps to the print root, or ""."""
    return getattr(settings, "PARODY_WEB_PRINT_XACCEL", "") or ""


def validate_print_settings(root, cache, xaccel):
    """Raise ImproperlyConfigured on a print configuration that cannot work.

    Called at startup (apps.ready) so a typo fails on boot rather than at the
    first reader's download — the same posture as PARODY_WEB_THEME.
    """
    if not root:
        return
    root_path = Path(root)
    if not root_path.is_dir():
        raise ImproperlyConfigured(
            f"PARODY_WEB_PRINT_ROOT: {root!r} is not a directory")
    if xaccel:
        # X-Accel-Redirect maps one internal location at the print root, so
        # anything served through it must live beneath that root.
        cache_path = Path(cache) if cache else root_path / ".cache"
        try:
            cache_path.resolve().relative_to(root_path.resolve())
        except ValueError:
            raise ImproperlyConfigured(
                "PARODY_WEB_PRINT_CACHE must live under "
                "PARODY_WEB_PRINT_ROOT when PARODY_WEB_PRINT_XACCEL is set "
                f"({cache_path} is outside {root_path})")
