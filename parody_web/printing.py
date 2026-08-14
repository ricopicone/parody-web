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

import os
from functools import lru_cache
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


@lru_cache(maxsize=4)
def _reader(path_str, token):
    """Parsed PdfReader, cached per (file, token).

    pypdf holds the whole document, so a cold-cache crawl over a 500-page
    illustrated book would otherwise re-parse tens of MB per section. `token`
    is the file's mtime, so a rebuilt book invalidates the entry rather than
    being served from a reader for the previous PDF.
    """
    from pypdf import PdfReader

    return PdfReader(path_str)


def book_pdf_path(book):
    """The full-book PDF on disk, or None when unavailable."""
    root = print_root()
    if not root or not book.print_pdf or not has_pypdf():
        return None
    # basename only: the artifact must never be able to escape the print root
    path = root / Path(book.print_pdf).name
    return path if path.is_file() else None


def slice_pdf(src, dest, start, end):
    """Write pages [start, end] (1-based, inclusive) of `src` to `dest`.

    Written to a temp file and renamed, so a concurrent request can never read
    a half-written PDF.
    """
    from pypdf import PdfWriter

    reader = _reader(str(src), src.stat().st_mtime_ns)  # mtime = cache token
    total = len(reader.pages)
    first = max(1, start)
    last = min(end, total)
    writer = PdfWriter()
    for i in range(first - 1, last):
        writer.add_page(reader.pages[i])
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        writer.write(f)
    os.replace(tmp, dest)


def section_pdf_path(book, section):
    """Path to this section's PDF, slicing and caching it on first request.

    None when anything the slice needs is missing — no pypdf, no print root, no
    PDF on disk, no page range. Callers render no affordance in that case.
    """
    if not section.print_pages or len(section.print_pages) != 2:
        return None
    src = book_pdf_path(book)
    if src is None:
        return None
    cache = print_cache_root()
    if cache is None:
        return None
    start, end = section.print_pages
    dest = (cache / book.slug / (book.edition_id or "_")
            / (book.print_sha256[:12] or "nohash")
            / f"{section.chapter.slug}-{section.slug}.pdf")
    if not dest.is_file():
        slice_pdf(src, dest, start, end)
    return dest
