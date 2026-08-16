"""Endpoints for a reader's ink.

Every one of these asks the access policy exactly the question
`parody_web.views.section_pdf` asks, before it touches ink. Anything a reader
may not download, they may not annotate.

Ink is private: every query is filtered by `user=request.user`, so isolation is
structural rather than a check someone can forget to write.
"""

import json

from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from parody_web import printing
from parody_web.access import get_policy
from parody_web.models import Section
from parody_web.views import _pdf_filename, _pdf_response, _resolve_book

from .models import InkLayer


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


def versions_for(request, book, section):
    """Versions worth showing: the current one, plus any this reader has ink on.

    Not the release history — the reader cares about where their notes are.
    """
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
            "versions": versions_for(request, book, section),
        })

    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "malformed json"}, status=400)

    key = payload.get("slice_key") or printing.slice_key_for(book, section)
    if not key:
        raise Http404("no pdf for this section")
    strokes = payload.get("strokes")
    if not isinstance(strokes, dict):
        return JsonResponse({"error": "strokes must be an object"}, status=400)

    # The page range and source version are recorded on write, while they are
    # still true: Section.print_pages is overwritten by the next import.
    pages = payload.get("pages") or section.print_pages
    InkLayer.objects.update_or_create(
        user=request.user, book_slug=book.slug,
        edition_id=book.edition_id or "", section_key=section.key,
        slice_key=key,
        defaults={"strokes": strokes, "pages": pages,
                  "book_sha256": payload.get("book_sha256") or book.print_sha256})
    return JsonResponse({"saved": True, "slice_key": key})


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
    if existing is not None and existing.stroke_count:
        return JsonResponse(
            {"error": "that version already has notes"}, status=409)

    InkLayer.objects.update_or_create(
        user=request.user, book_slug=book.slug,
        edition_id=book.edition_id or "", section_key=section.key,
        slice_key=target_key,
        defaults={"strokes": source.strokes,
                  "pages": section.print_pages or source.pages,
                  "book_sha256": book.print_sha256})
    return JsonResponse({"copied": source.stroke_count, "slice_key": target_key})
