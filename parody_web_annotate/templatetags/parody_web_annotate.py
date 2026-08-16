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
            versions = versions_for(request, book, section, current=current)
            # The most recent version this reader has ink on, when it is not
            # the current one — the offer to bring notes forward.
            carry = next((v["key"] for v in versions
                          if not v["current"] and v["updated_at"]), "")
            has_current = any(v["current"] and v["updated_at"] for v in versions)
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
            }
    setattr(request, _CACHE_ATTR, ctx)
    return ctx
