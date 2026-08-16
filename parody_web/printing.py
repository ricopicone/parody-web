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
import shutil
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


def print_archive_root():
    """Durable store of released book PDFs, or None when unconfigured.

    MUST point outside the deployment checkout. deploy_ec2.sh runs
    `git fetch && git reset --hard` in a persistent directory, so an archive
    under the repo would survive that but be destroyed by any later
    `git clean -fdx` — taking with it the source PDF behind every annotation a
    reader has made.

    Unset means versioning is simply off: the current PDF still serves.
    """
    value = getattr(settings, "PARODY_WEB_PRINT_ARCHIVE", "")
    return Path(value) if value else None


def archived_pdf_path(book_slug, sha256):
    """Where a given released version lives, or None when unavailable."""
    root = print_archive_root()
    if not root or not sha256:
        return None
    return root / book_slug / f"{sha256}.pdf"


def archive_book_pdf(book):
    """Copy the book's current PDF into the archive. Idempotent.

    Called at import, which is the last moment the bytes are reachable: the
    next deploy overwrites them.
    """
    from .models import BookPrintVersion

    src = book_pdf_path(book)
    dest = archived_pdf_path(book.slug, book.print_sha256)
    if src is None or dest is None:
        return None
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    pages = None
    try:
        pages = len(_reader(str(dest), dest.stat().st_mtime_ns).pages)
    except Exception:  # noqa: BLE001 - a page count is not worth failing over
        pass
    version, _ = BookPrintVersion.objects.get_or_create(
        book=book, sha256=book.print_sha256,
        defaults={"filename": dest.name, "page_count": pages})
    return version


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


def _page_fingerprint(page):
    """Bytes that change when the page's drawing changes, and not otherwise."""
    contents = page.get_contents()
    if contents is None:
        data = b""
    elif hasattr(contents, "get_data"):
        data = contents.get_data()
    else:  # an array of streams: concatenate in order
        data = b"".join(s.get_object().get_data() for s in contents)
    box = page.mediabox
    corners = [float(v) for v in (box.left, box.bottom, box.right, box.top)]
    return data + repr(corners).encode()


def slice_key_for(book, section):
    """Deterministic identity for this section's pages.

    Deliberately NOT the sha256 of the sliced file. That would make every
    reader's version key depend on *our writer*: a pypdf upgrade that changed
    object ordering or stream compression would change every slice's hash at
    once, and every annotation on the site would suddenly point at a version
    that appears not to exist. Hashing the source pages' content streams
    depends only on the PDF parody produced.

    It is also the cheaper key — no slice has to be cut to compute it, which
    matters because it is asked for a whole page of sections at a time.

    The property the annotation feature rests on: a rebuild that does not touch
    this section yields the same key, so the reader's notes stay put.
    Repagination *does* change it, because the printed page number is drawn in
    the content stream — which is honest, the page really did change.
    """
    import hashlib

    if not section.print_pages or len(section.print_pages) != 2:
        return None
    src = book_pdf_path(book)
    if src is None:
        return None
    reader = _reader(str(src), src.stat().st_mtime_ns)
    start, end = section.print_pages
    digest = hashlib.sha256()
    for i in range(max(1, start) - 1, min(end, len(reader.pages))):
        digest.update(_page_fingerprint(reader.pages[i]))
    return digest.hexdigest()


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


def public_book_pdf_warnings():
    """Books whose full PDF is public while some of their sections are not.

    PARODY_WEB_PUBLIC_BOOK_PDF defaults to True, which is right for a wholly
    public book and wrong for a gated one — and the failure is silent, because
    serving the PDF looks exactly like success. So say something: a gated book
    that has not turned the setting off is handing out the very text its
    online-only artifact was built to withhold.
    """
    from django.conf import settings

    if not getattr(settings, "PARODY_WEB_PUBLIC_BOOK_PDF", True):
        return []
    from .models import Book

    messages = []
    for book in Book.objects.exclude(print_pdf="").prefetch_related("sections"):
        if any(s.preview for s in book.sections.all()):
            label = f"{book.slug}/{book.edition_id}" if book.edition_id \
                else book.slug
            messages.append(
                f"{label}: the full-book PDF is public "
                "(PARODY_WEB_PUBLIC_BOOK_PDF is True) but the book has "
                "preview-gated sections — the PDF hands out text the site "
                "withholds. Set PARODY_WEB_PUBLIC_BOOK_PDF = False.")
    return messages
