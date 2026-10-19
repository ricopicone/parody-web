"""Endpoints for a reader's ink.

Every one of these asks the access policy exactly the question
`parody_web.views.section_pdf` asks, before it touches ink. Anything a reader
may not download, they may not annotate.

Ink is private: every query is filtered by `user=request.user`, so isolation is
structural rather than a check someone can forget to write.
"""

import json
import zlib

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from parody_web import printing
from parody_web.access import get_policy
from parody_web.models import Section
from parody_web.views import _pdf_filename, _pdf_response, _resolve_book, _twin_filename

from . import bookink, export
from .models import InkLayer


# A save carries the reader's whole section, not the one mark they just made,
# so the body grows with their notes: a pen stroke serialises to ~11 KB of
# outline path, and a densely marked section runs to several megabytes.
#
# DATA_UPLOAD_MAX_MEMORY_SIZE is the wrong ruler for that. It defaults to
# 2.5 MB — a sane ceiling for a form post, reached here after a few hundred
# strokes — and it is enforced inside `HttpRequest.body`, which raises
# SuspiciousOperation before a view can say anything useful. In production that
# meant a 400 the reader never saw, an admin email on every debounced save for
# the rest of their session, and their ink quietly discarded (task #667).
#
# So the ink endpoint reads the stream itself and applies its own, far more
# generous ceiling. Raising the global setting instead would hand the same
# allowance to every form on the site.
INK_MAX_BODY_BYTES = 25 * 1024 * 1024


def _ink_max_body_bytes():
    return getattr(settings, "PARODY_WEB_INK_MAX_BODY_BYTES",
                   INK_MAX_BODY_BYTES)


class _TooBig(Exception):
    """The body is past the ink ceiling — answer 413, don't raise."""


class _BadEncoding(Exception):
    """The body claims an encoding it does not actually have — answer 400."""


class _UnsupportedEncoding(Exception):
    """An encoding we do not speak — answer 415."""


def _gunzip_capped(raw, limit):
    """Decompress `raw`, stopping AT the ceiling rather than past it.

    Returns the bytes, or None if the payload inflates beyond `limit`.

    The cap has to be applied to the decompressed size — 25 MB of gzip is
    hundreds of megabytes of ink, so a ceiling measured on the compressed
    bytes would be no ceiling at all. And it has to be applied *during*
    decompression: refusing a bomb only after building it in memory would be
    its own outage on a 2 GB box. `max_length` is what makes that true — zlib
    stops producing at the cap and leaves the rest in `unconsumed_tail`.
    """
    machine = zlib.decompressobj(16 + zlib.MAX_WBITS)     # 16 = gzip wrapper
    out = machine.decompress(raw, limit + 1)
    if len(out) > limit or machine.unconsumed_tail:
        return None
    if not machine.eof:
        raise _BadEncoding("truncated gzip body")
    return out


def _read_ink_body(request):
    """The request body, read past DATA_UPLOAD_MAX_MEMORY_SIZE, decompressed.

    `request.read()` is the same stream `request.body` would drain, minus that
    setting's check; the stream is already bounded by CONTENT_LENGTH, and the
    ceiling below bounds it again in case that header lied.
    """
    limit = _ink_max_body_bytes()
    declared = int(request.META.get("CONTENT_LENGTH") or 0)
    if declared > limit:
        raise _TooBig

    body = request.read(limit + 1)
    if len(body) > limit:
        raise _TooBig

    encoding = (request.META.get("HTTP_CONTENT_ENCODING") or "").strip().lower()
    if not encoding or encoding == "identity":
        return body
    if encoding != "gzip":
        raise _UnsupportedEncoding(encoding)

    try:
        out = _gunzip_capped(body, limit)
    except zlib.error as exc:
        raise _BadEncoding(str(exc)) from exc
    if out is None:
        raise _TooBig
    return out


def _section_or_404(request, chapter_slug, section_slug):
    """Resolve and gate, the way section_pdf does.

    A refusal must not distinguish itself from an absence, or it would confirm
    that gated content exists.
    """
    book, _ = _resolve_book(request)
    section = get_object_or_404(
        Section, book=book, chapter__slug=chapter_slug, slug=section_slug)
    if not get_policy().can_download_section_pdf(request, section):
        raise Http404("no pdf for this section")
    return book, section


def _layers(request, book, section):
    """This reader's layers for this section — never anyone else's."""
    return InkLayer.objects.filter(
        user=request.user, book_slug=book.slug,
        edition_id=book.edition_id or "", section_key=section.key)


def versions_for(request, book, section, current=None):
    """Versions worth showing: the current one, plus any this reader has ink on.

    Not the release history — the reader cares about where their notes are.

    `current` may be passed in by a caller that already computed it; the key
    is a hash over the section's pages, so recomputing it is not free.
    """
    if current is None:
        current = printing.slice_key_for(book, section)
    rows = []
    seen = set()
    if current:
        rows.append({"key": current, "current": True, "updated_at": None})
        seen.add(current)
    if request.user.is_authenticated:
        for layer in _layers(request, book, section):
            if layer.slice_key in seen:
                rows[0]["updated_at"] = layer.updated_at.isoformat()
                continue
            rows.append({"key": layer.slice_key, "current": False,
                         "updated_at": layer.updated_at.isoformat()})
            seen.add(layer.slice_key)
    return rows


@require_http_methods(["GET", "PUT"])
@csrf_protect
def ink(request, chapter_slug, section_slug):
    """Read or replace this reader's strokes for one version of one section."""
    book, section = _section_or_404(request, chapter_slug, section_slug)
    if not request.user.is_authenticated:
        return HttpResponseForbidden("sign in to annotate")

    if request.method == "GET":
        key = request.GET.get("v") or printing.slice_key_for(book, section)
        layer = _layers(request, book, section).filter(slice_key=key).first()
        return JsonResponse({
            "slice_key": key,
            "strokes": layer.strokes if layer else {},
            "pads": layer.pads if layer else {},
            "twins": layer.twins if layer else {},
            "twin_keys": layer.twin_keys if layer else {},
            "versions": versions_for(request, book, section),
        })

    try:
        payload = json.loads(_read_ink_body(request) or b"{}")
    except _TooBig:
        return JsonResponse(
            {"error": "too much ink in one section to save at once",
             "limit_bytes": _ink_max_body_bytes()}, status=413)
    except _UnsupportedEncoding as exc:
        return JsonResponse(
            {"error": f"unsupported content encoding: {exc}",
             "supported": ["gzip", "identity"]}, status=415)
    except _BadEncoding:
        # A proxy mangled the body, or the client mislabelled it. Say so
        # plainly: the client downgrades to uncompressed on seeing this rather
        # than retrying the same broken request forever.
        return JsonResponse({"error": "body is not valid gzip"}, status=400)
    except ValueError:
        return JsonResponse({"error": "malformed json"}, status=400)

    key = payload.get("slice_key") or printing.slice_key_for(book, section)
    if not key:
        raise Http404("no pdf for this section")
    strokes = payload.get("strokes")
    if not isinstance(strokes, dict):
        return JsonResponse({"error": "strokes must be an object"}, status=400)
    pads = payload.get("pads")
    if pads is None:
        pads = {}
    if not isinstance(pads, dict):
        return JsonResponse({"error": "pads must be an object"}, status=400)
    if "twins" in payload and not _is_twin_ink(payload["twins"]):
        return JsonResponse(
            {"error": "twins must map a language to pages of strokes"}, status=400)
    keys = payload.get("twin_keys")
    if "twin_keys" in payload and not (
            isinstance(keys, dict) and all(isinstance(v, str) for v in keys.values())):
        return JsonResponse(
            {"error": "twin_keys must map a language to a key"}, status=400)

    # The page range and source version are recorded on write, while they are
    # still true: Section.print_pages is overwritten by the next import.
    pages = payload.get("pages") or section.print_pages
    defaults = {"strokes": strokes, "pads": pads, "pages": pages,
                "book_sha256": payload.get("book_sha256") or book.print_sha256}
    where = {"user": request.user, "book_slug": book.slug,
             "edition_id": book.edition_id or "", "section_key": section.key,
             "slice_key": key}
    with transaction.atomic():
        # created first if need be, so a second first save waits on the row
        # instead of both merging over nothing
        layer, _ = InkLayer.objects.select_for_update().get_or_create(
            **where, defaults={"strokes": {}, "pads": {}, "pages": pages,
                               "book_sha256": defaults["book_sha256"]})
        # Each language sent replaces that language's notes; one not sent is
        # kept. A tab shows one translation at most and sends only it, so an
        # English-only tab, a tab on the other language, or a viewer from
        # before translations cannot erase notes it never had on screen.
        if "twins" in payload:
            twins = {**(layer.twins if layer else {}), **payload["twins"]}
            defaults["twins"] = {lang: ink for lang, ink in twins.items() if ink}
        if "twin_keys" in payload:
            defaults["twin_keys"] = {**(layer.twin_keys if layer else {}),
                                     **payload["twin_keys"]}
        InkLayer.objects.update_or_create(**where, defaults=defaults)
    return JsonResponse({"saved": True, "slice_key": key})


def _is_twin_ink(twins):
    """{language: {page: [stroke, ...]}}, the shape `strokes` has per language."""
    return isinstance(twins, dict) and all(
        isinstance(pages, dict) and all(isinstance(v, list) for v in pages.values())
        for pages in twins.values())


def _resolve_version(request, book, section, key):
    """(book_sha256, pages) for a requested version, or None.

    The current version comes from the book; any other must come from a layer
    this reader owns, because that row is the only record of which archived
    book and which pages it was.
    """
    current = printing.slice_key_for(book, section)
    if not key or key == current:
        return book.print_sha256, section.print_pages
    if not request.user.is_authenticated:
        return None
    layer = _layers(request, book, section).filter(slice_key=key).first()
    if layer is None:
        return None
    return layer.book_sha256, layer.pages


@require_http_methods(["GET"])
def section_pdf_at_version(request, chapter_slug, section_slug):
    """This section's PDF at a named version."""
    book, section = _section_or_404(request, chapter_slug, section_slug)
    key = request.GET.get("v")
    resolved = _resolve_version(request, book, section, key)
    if resolved is None:
        raise Http404("no such version")
    book_sha, pages = resolved

    current = printing.slice_key_for(book, section)
    if not key or key == current:
        path = printing.section_pdf_path(book, section)
    else:
        path = printing.versioned_section_pdf(
            book, book_sha, pages, f"{section.chapter.slug}-{section.slug}")
    if path is None:
        raise Http404("no pdf for this section")
    return _pdf_response(path, _pdf_filename(book, section),
                         inline=bool(request.GET.get("inline")))


@require_http_methods(["POST"])
@csrf_protect
def carry_forward(request, chapter_slug, section_slug):
    """Copy an older version's strokes onto a newer one.

    A copy, never a move: the old annotated version stays exactly as it was.
    Refuses rather than overwrites — the reader asked to bring notes forward,
    not to lose the ones already here.
    """
    book, section = _section_or_404(request, chapter_slug, section_slug)
    if not request.user.is_authenticated:
        return HttpResponseForbidden("sign in to annotate")
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "malformed json"}, status=400)

    source = _layers(request, book, section).filter(
        slice_key=payload.get("from") or "").first()
    if source is None:
        raise Http404("no such version")
    target_key = payload.get("to") or printing.slice_key_for(book, section)
    if not target_key:
        raise Http404("no pdf for this section")

    existing = _layers(request, book, section).filter(slice_key=target_key).first()
    if existing is not None and existing.english_stroke_count:
        return JsonResponse(
            {"error": "that version already has notes"}, status=409)

    # A translation already written on here keeps its ink; the source's comes
    # over only for the languages this version has none in.
    # Each language's key goes with its ink, so a translation that changed
    # under the notes brought over is still told apart.
    here = {lang: pages for lang, pages in ((existing.twins if existing else None) or {}).items()
            if any(pages.values())}
    here_keys = {lang: key for lang, key in ((existing.twin_keys if existing else None) or {}).items()
                 if lang in here}
    InkLayer.objects.update_or_create(
        user=request.user, book_slug=book.slug,
        edition_id=book.edition_id or "", section_key=section.key,
        slice_key=target_key,
        defaults={"strokes": source.strokes, "pads": source.pads,
                  "twins": {**(source.twins or {}), **here},
                  "twin_keys": {**(source.twin_keys or {}), **here_keys},
                  "pages": section.print_pages or source.pages,
                  "book_sha256": book.print_sha256})
    return JsonResponse({"copied": source.stroke_count, "slice_key": target_key})


@require_http_methods(["GET"])
def annotated_section_pdf(request, chapter_slug, section_slug):
    """This section's PDF with the reader's own ink drawn into it.

    Composited server-side so what comes back is a real file — one a reader can
    print, mail, or keep — rather than something only this viewer can show.
    """
    import hashlib

    book, section = _section_or_404(request, chapter_slug, section_slug)
    if not request.user.is_authenticated:
        return HttpResponseForbidden("sign in to annotate")

    key = request.GET.get("v") or printing.slice_key_for(book, section)
    layer = _layers(request, book, section).filter(slice_key=key).first()
    if layer is None:
        raise Http404("nothing annotated here")

    resolved = _resolve_version(request, book, section, key)
    if resolved is None:
        raise Http404("no such version")
    book_sha, pages = resolved
    current = printing.slice_key_for(book, section)
    if not key or key == current:
        src = printing.section_pdf_path(book, section)
    else:
        src = printing.versioned_section_pdf(
            book, book_sha, pages, f"{section.chapter.slug}-{section.slug}")
    if src is None:
        raise Http404("no pdf for this section")

    cache = printing.print_cache_root()
    if cache is None:
        raise Http404("no pdf for this section")

    # ?twin=<language>: the English and the translation beside it, as the
    # reader saw them, each with its own ink. Only the current version pairs
    # with the translation the book serves now; anything else is the English.
    twin = None
    if request.GET.get("twin") and (not key or key == current):
        found = printing.twin_for(book, request.GET["twin"])
        paired = found and printing.twin_paired_pdf_path(book, section, found)
        if paired:
            twin = (found, paired)
    twin_strokes = (layer.twins or {}).get(twin[0].language, {}) if twin else {}

    # Keyed by the ink as well as the version, so editing a stroke produces a
    # new file rather than serving a stale composite.
    stamp = hashlib.sha256(json.dumps(
        [layer.strokes, layer.pads] + ([twin[0].sha256, twin_strokes] if twin else []),
        sort_keys=True).encode()).hexdigest()[:12]
    variant = f"-{twin[0].language}" if twin else ""
    dest = (cache / "annotated" / str(request.user.pk) / book.slug
            / f"{section.chapter.slug}-{section.slug}-{(key or '')[:12]}{variant}-{stamp}.pdf")
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{dest.name}.tmp")
        if twin:
            export.composite_side_by_side(src, twin[1], tmp, layer.strokes,
                                          twin_strokes, pads_by_page=layer.pads)
        else:
            export.composite(src, layer.strokes, tmp, pads_by_page=layer.pads)
        tmp.replace(dest)
    name = _pdf_filename(book, section)
    if twin:
        name = _twin_filename(name, twin[0].language, side_by_side=True)
    name = name.replace(".pdf", "-annotated.pdf")
    return _pdf_response(dest, name, inline=bool(request.GET.get("inline")))


@require_http_methods(["GET"])
def annotated_book_pdf(request):
    """The whole book, with every section's notes drawn on.

    What a student prints to take into an exam. Gated exactly as the plain
    book PDF is, then again per section inside the planner, so a section they
    may not read cannot arrive by way of their own notes.
    """
    import hashlib

    book, _ = _resolve_book(request)
    if not request.user.is_authenticated:
        return HttpResponseForbidden("sign in to annotate")
    if not get_policy().can_download_book_pdf(request, book):
        raise Http404("no pdf for this book")

    src = printing.book_pdf_path(book)
    cache = printing.print_cache_root()
    if src is None or cache is None:
        raise Http404("no pdf for this book")

    pages, pads, _skipped = bookink.plan_book_overlay(request, book)
    if not pages and not pads:
        raise Http404("nothing annotated in this book")

    stamp = hashlib.sha256(
        json.dumps([pages, pads], sort_keys=True).encode()).hexdigest()[:12]
    dest = (cache / "annotated-book" / str(request.user.pk) / book.slug
            / f"{(book.print_sha256 or 'nohash')[:12]}-{stamp}.pdf")
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{dest.name}.tmp")
        export.composite(src, {str(k): v for k, v in pages.items()}, tmp,
                         pads_by_page={str(k): v for k, v in pads.items()})
        tmp.replace(dest)
    name = _pdf_filename(book).replace(".pdf", "-annotated.pdf")
    return _pdf_response(dest, name, inline=bool(request.GET.get("inline")))
