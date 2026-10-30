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

import hashlib
import logging
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


logger = logging.getLogger(__name__)


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


@lru_cache(maxsize=256)
def _file_sha256(path_str, size, mtime_ns):
    """The file's sha256, computed once per version of the file (size and
    mtime are part of the key, so a replaced file is hashed again)."""
    digest = hashlib.sha256()
    with open(path_str, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _recorded(path, sha256):
    """``path`` when it is a file whose bytes are the ones the database
    recorded (``sha256``), else None.

    A deploy swaps the files (git reset) minutes before it imports the
    artifacts describing them; in between, the old page ranges cut the new
    PDF, and the wrong pages were cached, paired and archived. Refusing bytes
    that are not the recorded ones makes that window a few minutes without
    PDFs instead. PARODY_WEB_VERIFY_PRINT_BYTES = False turns it off (the
    standalone tests, whose fixtures record made-up hashes).
    """
    if not path.is_file():
        return None
    if not getattr(settings, "PARODY_WEB_VERIFY_PRINT_BYTES", True):
        return path
    st = path.stat()
    if _file_sha256(str(path), st.st_size, st.st_mtime_ns) == sha256:
        return path
    _refused(str(path), st.st_size, st.st_mtime_ns, sha256)
    return None


@lru_cache(maxsize=256)
def _refused(path_str, size, mtime_ns, sha256):
    """Say once per file version that its bytes are not the recorded ones:
    every section PDF, annotation and read-along of the book is gone while
    it lasts, which is right for a deploy's few minutes and a fault after."""
    logger.warning("%s is not the PDF recorded (sha256 %s); not serving it",
                   path_str, (sha256 or "none")[:12])


def book_pdf_path(book):
    """The full-book PDF on disk, or None when unavailable or not the PDF the
    book's artifact describes."""
    root = print_root()
    if not root or not book.print_pdf or not has_pypdf():
        return None
    # basename only: the artifact must never be able to escape the print root
    return _recorded(root / Path(book.print_pdf).name, book.print_sha256)


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
    if dest.is_file() and _recorded(dest, book.print_sha256) is None:
        dest.unlink()  # archived before bytes were checked, and wrong: again
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


def versioned_section_pdf(book, book_sha256, pages, cache_name):
    """A section slice cut from an ARCHIVED book version.

    Unlike section_pdf_path this never falls back to the live book. A version
    we cannot produce must be absent, not silently substituted: the reader
    asked for the pages they annotated, and different pages under that name
    would be worse than none.
    """
    if not pages or len(pages) != 2 or not has_pypdf():
        return None
    src = archived_pdf_path(book.slug, book_sha256)
    if src is None or not src.is_file():
        return None
    cache = print_cache_root()
    if cache is None:
        return None
    start, end = pages
    dest = (cache / book.slug / (book.edition_id or "_")
            / f"v{book_sha256[:12]}" / f"{cache_name}-{start}-{end}.pdf")
    if not dest.is_file():
        slice_pdf(src, dest, start, end)
    return dest


def twin_for(book, language):
    """The book's translated twin in ``language`` when it can be served, else None.

    Only a twin of the English PDF the book serves now: a twin of an older
    build pairs the wrong pages, and is absent rather than wrong.
    """
    from .twins import LANGUAGE_NAMES

    if language not in LANGUAGE_NAMES:
        return None
    twin = book.twins.filter(language=language).first()
    return twin if twin is not None and _servable(book, twin) else None


def translations_available(book):
    """The twins ``twin_for`` would serve, in language order (one query)."""
    return [t for t in book.twins.all() if _servable(book, t)]


def _servable(book, twin):
    from .twins import LANGUAGE_NAMES

    return bool(twin.language in LANGUAGE_NAMES and book.print_sha256 and has_pypdf()
                and twin.english_sha256 == book.print_sha256
                and twin_pdf_path(twin) is not None)


def twin_pdf_path(twin, side_by_side=False, key=False):
    """The whole twin (or its side-by-side sheets) on disk, or None — also
    when the twin on disk is not the one recorded. The sheets carry no hash of
    their own; they come out of the same build as the twin, so they go with it.

    ``key``: the key twin instead, the same pages with the blanks filled
    (None when the release built none), checked against its own hash."""
    root = print_root()
    pdf, sha = (twin.key_pdf, twin.key_sha256) if key else (twin.pdf, twin.sha256)
    if key:
        name = twin.key_side_by_side_pdf if side_by_side else twin.key_pdf
    else:
        name = twin.side_by_side_pdf if side_by_side else twin.pdf
    if not root or not name or not pdf:
        return None
    # basename only, as for the English PDF
    if _recorded(root / Path(pdf).name, sha) is None:
        return None
    path = root / Path(name).name
    return path if path.is_file() else None


def twin_has_key(twin):
    """Whether this twin's key can be served."""
    return bool(twin is not None and twin.key_pdf and twin_pdf_path(twin, key=True))


def _twin_page_count(twin, src):
    """The twin's page count: its abspages hold one entry per twin page, so
    an import with them needs no PDF read for it."""
    if twin.abspages:
        return len(twin.abspages)
    return len(_reader(str(src), src.stat().st_mtime_ns).pages)


def twin_section_pdf_path(book, section, twin, side_by_side=False, key=False):
    """This section's pages of the twin (or of its side-by-side sheets).

    Cut by the twin's own page ranges: the twin starts at its first translated
    section, so the English range would cut the wrong pages. None when the
    twin does not cover the section, or anything the slice needs is missing.
    """
    pages = (twin.sections or {}).get(f"{section.chapter.slug}/{section.slug}")
    if not pages or len(pages) != 2:
        return None
    src = twin_pdf_path(twin, side_by_side, key)
    cache = print_cache_root()
    if src is None or cache is None or not has_pypdf():
        return None
    start, end = pages
    sha = twin.key_sha256 if key else twin.sha256
    variant = (f"twin-{twin.language}-{sha[:12]}" + ("-key" if key else "")
               + ("-sbs" if side_by_side else ""))
    # by its range too: the same twin imported again with other ranges
    dest = (cache / book.slug / (book.edition_id or "_") / variant
            / f"{section.chapter.slug}-{section.slug}-{start}-{end}.pdf")
    if dest.is_file():
        return dest  # cut before, from this very twin (its hash names the directory)
    if start > _twin_page_count(twin, src):
        return None  # a range past the twin's end: no pages to cut, so no PDF
    slice_pdf(src, dest, start, end)
    return dest


def _twin_pages_for(section, twin, twin_count):
    """For each English page of ``section``, the twin page that holds it
    (1-based), or None where no twin page does.

    By the twin's ``abspages`` when it has them. A twin imported before those
    were kept is paired from its own first page of the section onward, which
    holds while the twin's pages run on as the English ones do.
    """
    start, end = section.print_pages
    abspages = twin.abspages if isinstance(twin.abspages, list) else []
    if abspages and all(isinstance(p, int) for p in abspages):
        where = {english: i + 1 for i, english in enumerate(abspages)}
        pages = [where.get(english) for english in range(start, end + 1)]
    else:
        own = (twin.sections or {}).get(f"{section.chapter.slug}/{section.slug}")
        if not own or len(own) != 2:
            return [None] * (end - start + 1)
        pages = [own[0] + k for k in range(end - start + 1)]
    return [p if p is not None and 1 <= p <= twin_count else None for p in pages]


def _twin_lists(twin, section):
    """Whether the twin lists this section: pairing goes by English page, and
    a section the twin does not list (but whose pages it holds) is one the site
    offers no translation of anywhere, so none is paired for it either."""
    return f"{section.chapter.slug}/{section.slug}" in (twin.sections or {})


def twin_paired_key(book, section, twin):
    """Identity of the twin pages beside this section's English, or None.

    What a reader's ink on the translation was written over: it changes when
    those pages do (a retranslation, a rebuild that moved them) and not
    otherwise, by the same content-stream fingerprint as ``slice_key_for``.
    The English version key cannot tell, because a twin can be rebuilt
    against the same English.
    """
    if not section.print_pages or len(section.print_pages) != 2 or not _twin_lists(twin, section):
        return None
    src = twin_pdf_path(twin)
    if src is None or not has_pypdf():
        return None
    pages = _twin_pages_for(section, twin, _twin_page_count(twin, src))
    if not any(pages):
        return None
    return _paired_key(str(src), src.stat().st_mtime_ns, twin.sha256, tuple(pages))


@lru_cache(maxsize=1024)
def _paired_key(src, mtime_ns, twin_sha256, pages):
    """The fingerprint of these twin pages, once per twin version (the twin's
    hash, which twin_pdf_path has just checked the file against) and pages:
    a page view used to re-read the whole twin for it."""
    reader = _reader(src, mtime_ns)
    digest = hashlib.sha256()
    for page in pages:
        digest.update(_page_fingerprint(reader.pages[page - 1]) if page else b"no twin page")
    return digest.hexdigest()


def twin_paired_pdf_path(book, section, twin, key=False):
    """The twin page beside each English page of this section, one for one.

    What the reader shows next to the English: page k of this PDF holds what
    English page k of the section holds, so the two scroll together. A page
    with no twin (the twin covers only published sections) is a blank page
    the size of its English one, so every page after it still pairs. Unlike
    ``twin_section_pdf_path``, which cuts the twin's own range for the
    section, a page the twin assigned to the next section (a sentence split
    across pages kept whole) still sits beside its English page.

    None when the twin does not list the section or holds none of its pages,
    or anything the pairing needs is missing.

    ``key``: the key twin's pages, paired the same way. Its pages ARE the
    twin's, filled (parody's key takes exactly the room a blank does), so ink
    a reader wrote beside the blank twin lies on it unchanged — which is why
    ``twin_paired_key``, the identity that ink is filed under, is the blank
    twin's in both cases.
    """
    if not section.print_pages or len(section.print_pages) != 2 or not _twin_lists(twin, section):
        return None
    src = twin_pdf_path(twin, key=key)
    english = book_pdf_path(book)
    cache = print_cache_root()
    if src is None or english is None or cache is None or not has_pypdf():
        return None
    pages = _twin_pages_for(section, twin, _twin_page_count(twin, src))
    if not any(pages):
        return None
    start, end = section.print_pages
    # by the pairing too: the same twin re-imported with its abspages can
    # pair differently from the fallback that cut the cached file
    pairing = hashlib.sha256(repr(pages).encode()).hexdigest()[:8]
    sha = twin.key_sha256 if key else twin.sha256
    dest = (cache / book.slug / (book.edition_id or "_")
            / f"twin-{twin.language}-{sha[:12]}{'-key' if key else ''}-paired"
            / f"{section.chapter.slug}-{section.slug}-{start}-{end}-{pairing}.pdf")
    if not dest.is_file():
        from pypdf import PdfWriter

        reader = _reader(str(src), src.stat().st_mtime_ns)
        english_reader = _reader(str(english), english.stat().st_mtime_ns)
        writer = PdfWriter()
        for english_page, twin_page in zip(range(start, end + 1), pages):
            if twin_page is not None:
                writer.add_page(reader.pages[twin_page - 1])
                continue
            box = english_reader.pages[min(english_page, len(english_reader.pages)) - 1].mediabox
            writer.add_blank_page(width=float(box.width), height=float(box.height))
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
        with open(tmp, "wb") as f:
            writer.write(f)
        os.replace(tmp, dest)
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
