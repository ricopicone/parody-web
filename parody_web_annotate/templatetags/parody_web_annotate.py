"""Template access to the reader's ink context.

A tag rather than a context processor: a processor runs on every render of
every page, and this needs to read the PDF to compute a version key. The tag
runs only where a partial asks for it, and memoises on the request so the
three PDF-view partials cost one computation between them.
"""

import json

from django import template
from django.urls import reverse

from parody_web import printing

from ..views import versions_for

register = template.Library()

_CACHE_ATTR = "_parody_ink_context"


def _layer(request, book, section, slice_key):
    from ..models import InkLayer

    return InkLayer.objects.filter(
        user=request.user, book_slug=book.slug,
        edition_id=book.edition_id or "", section_key=section.key,
        slice_key=slice_key).first()


def _has_ink(layer, language=""):
    """Has this reader drawn on what is shown: the English, and the
    translation beside it when there is one?"""
    return bool(layer and (layer.english_stroke_count
                           or (language and layer.twin_stroke_count(language))))


def _twin_key(book, section, twin):
    """The key of the translated pages shown beside the English."""
    found = printing.twin_for(book, twin["language"])
    return (found and printing.twin_paired_key(book, section, found)) or ""


@register.simple_tag(takes_context=True)
def ink_context(context):
    """Everything the stage, head and toolbar partials need.

    `enabled` is false for a reader who cannot annotate — anonymous, or a
    section with no PDF. They get parody-web's plain iframe, not a dead
    toolbar.
    """
    request = context.get("request")
    section = context.get("section")
    book = context.get("book")
    if request is None or section is None or book is None:
        return {"enabled": False}

    cached = getattr(request, _CACHE_ATTR, None)
    if cached is not None:
        return cached

    ctx = {"enabled": False}
    if request.user.is_authenticated:
        current = printing.slice_key_for(book, section)
        # ?v= lets a reader open an older version they annotated; anything we
        # do not recognise falls back to the current one rather than 500ing.
        asked = request.GET.get("v") or ""
        slice_key = current
        if asked and asked != current:
            from ..models import InkLayer
            if InkLayer.objects.filter(
                    user=request.user, book_slug=book.slug,
                    edition_id=book.edition_id or "",
                    section_key=section.key, slice_key=asked).exists():
                slice_key = asked
        if slice_key:
            # The translation beside the English (the view's `twin`), only on
            # the current version: it pairs with the English the book serves
            # now, not with an archived one.
            twin = context.get("twin") if slice_key == current else None
            annotated = (
                reverse("parody_web_annotate:annotated_section_pdf",
                        args=[section.chapter.slug, section.slug])
                + (f"?v={slice_key}" if slice_key != current else "")
                + (f"?twin={twin['language']}" if twin else ""))
            shown = _layer(request, book, section, slice_key)
            has_ink = _has_ink(shown, twin["language"] if twin else "")
            versions = versions_for(request, book, section, current=current)
            # The most recent version this reader has ink on, when it is not
            # the current one — the offer to bring notes forward.
            carry = next((v["key"] for v in versions
                          if not v["current"] and v["updated_at"]), "")
            # English notes on the current version are what carrying forward
            # would conflict with; a translation written on alone is not.
            here = shown if slice_key == current else _layer(request, book, section, current)
            has_current = bool(here and here.english_stroke_count)
            ctx = {
                "enabled": True,
                "base": reverse("parody_web:section",
                                args=[section.chapter.slug, section.slug]),
                "pdf_url": (
                    reverse("parody_web_annotate:section_pdf_at_version",
                            args=[section.chapter.slug, section.slug])
                    + (f"?v={slice_key}" if slice_key != current else "")),
                "slice_key": slice_key,
                "book_sha": book.print_sha256,
                "pages": json.dumps(section.print_pages or []),
                "versions": versions,
                # Offered once, and only when there is nothing on this version
                # to conflict with.
                "carry_from": "" if has_current else carry,
                # Set only when this reader actually has marks on the version
                # they are looking at, so the link never promises notes that
                # are not there. Core's plain download stays the default.
                "download_url": annotated if has_ink else "",
                "twin_url": f"{twin['paired_url']}?inline=1" if twin else "",
                "twin_key": _twin_key(book, section, twin) if twin else "",
                "twin_language": twin["language"] if twin else "",
                "twin_name": twin["name"] if twin else "",
                # What ⌘P prints with nothing annotated: what is on screen.
                "print_url": (twin["sbs_url"] or "") if twin and not has_ink else "",
            }
    setattr(request, _CACHE_ATTR, ctx)
    return ctx


@register.simple_tag(takes_context=True)
def book_ink(context):
    """Whether this reader has notes anywhere in the book, and what is stale.

    Memoised on the request: the book home page and the section rail both ask,
    and it walks every layer the reader owns.
    """
    from .. import bookink

    request = context.get("request")
    book = context.get("book")
    if request is None or book is None:
        return {"any": False, "pages": 0, "stale": []}
    cached = getattr(request, "_parody_book_ink", None)
    if cached is not None:
        return cached
    result = bookink.summary(request, book)
    setattr(request, "_parody_book_ink", result)
    return result
